#!/usr/bin/env python3
"""
Szybka normalizacja trajektorii Vicon (CSV z dwiema sekcjami):
- centrowanie w miednicy (LASI/RASI),
- ujednolicenie yaw (preferowane przez wektor przód-tył z ASIS↔PSIS; fallback: oś bioder LASI→RASI),
- skalowanie globalne do stałej szerokości ASIS (domyślnie = 1.0 jednostki znormalizowanej),
- rekonstrukcja pliku: sekcja kątów (Angles) kopiowana 1:1, Trajectories nadpisane wartościami
  (domyślnie bez CentreOfMass/CentreOfMassFloor).

Nowość (mirror katalogów):
- podaj katalog wejściowy i wyjściowy; zachowujemy strukturę podkatalogów i nazwy plików,
- domyślnie: wejście `csv/`, wyjście `normalized/` → `csv/nazwa_kroku/file.csv` → `normalized/nazwa_kroku/file.csv`.

Użycie (drzewo):
  python 1fast_normalize.py --in-root csv --out-root normalized

Użycie (pojedynczy plik):
  python 1fast_normalize.py --in path/to/file.csv [--out normalized/path/to/file.csv]

Autor: "magisterka" toolchain
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional, Sequence, Dict

import numpy as np
import pandas as pd
from utils import (
    SectionMeta,
    detect_delimiter,
    find_section_indices,
    parse_markers,
)

# ------------------------- Rdzeń: normalizacja -------------------------
@dataclass
class NormConfig:
    window: Optional[Tuple[int, int]] = (0, 50)   # okno do estymacji skali (w klatkach)
    target_pelvis: float = 1.0                    # docelowa szerokość ASIS po skalowaniu
    unit_label: str = "norm"                      # etykieta jednostek w wyjściu (np. 'norm' lub 'mm')
    skip_markers: Sequence[str] = ("CentreOfMass", "CentreOfMassFloor")
    force_keep: Sequence[str] = ()                # markery, które MUSZĄ być w wyjściu, nawet jeśli w skip


@dataclass
class TrajData:
    frames: np.ndarray            # (T,)
    subframes: np.ndarray         # (T,)
    markers_full: List[str]
    markers_clean: List[str]
    kept_idx: List[int]           # indeksy markerów w oryginalnej liście (po filtrze)
    needed_idx: List[int]         # kept ∪ potrzebne do normalizacji (LASI/RASI/LPSI/RPSI)
    X: np.ndarray                 # (T, M_needed, 3) – dane wejściowe dla needed


NEEDED_FOR_NORM = ("LASI", "RASI", "LPSI", "RPSI")


def load_traj_fast(path: Path, lines: List[str], meta: SectionMeta, cfg: NormConfig, delim: str) -> TrajData:
    m_full, m_clean = parse_markers(lines[meta.marker_idx], delim)  # z zachowaniem pustych miejsc

    # które markery zostawiamy w WYJŚCIU (tylko te z nazwą)
    skip = set(cfg.skip_markers) - set(cfg.force_keep)
    kept_idx = [i for i, name in enumerate(m_clean) if name and name not in skip]

    # mapowanie nazwa -> pierwszy indeks tripletu
    name_to_trip: Dict[str, int] = {}
    for i, name in enumerate(m_clean):
        if name and name not in name_to_trip:
            name_to_trip[name] = i

    # wymagane do normalizacji (mogą nie być w kept)
    needed_idx_set = set(kept_idx)
    for req in NEEDED_FOR_NORM:
        if req in name_to_trip:
            needed_idx_set.add(name_to_trip[req])
    needed_idx = sorted(needed_idx_set)

    # sprawdź absolutne minimum
    if "LASI" not in name_to_trip or "RASI" not in name_to_trip:
        raise ValueError("Brak markerów LASI/RASI w sekcji Trajectories – nie można znormalizować.")

    # Indeksy kolumn do wczytania z CSV (0:Frame,1:Sub Frame, dalej triplet'y)
    def triplet_cols(k: int) -> List[int]:
        base = 2 + 3 * k
        return [base, base + 1, base + 2]

    usecols = [0, 1]
    for k in needed_idx:
        usecols += triplet_cols(k)

    nrows = meta.data_end - meta.data_start

    # Nazwy kolumn zgodne z needed_idx
    cols = ["Frame", "Sub Frame"]
    for k in needed_idx:
        name = m_clean[k] if m_clean[k] else f"UNK{k}"
        cols += [f"{name}:X", f"{name}:Y", f"{name}:Z"]

    try:
        df = pd.read_csv(
            path,
            skiprows=meta.data_start,
            nrows=nrows,
            header=None,
            usecols=usecols,
            names=cols,
            dtype=np.float32,
            engine="c",
            sep=delim,
        )
    except Exception:
        df = pd.read_csv(
            path,
            skiprows=meta.data_start,
            nrows=nrows,
            header=None,
            usecols=usecols,
            names=cols,
            dtype=np.float32,
            engine="python",
        )

    frames = df["Frame"].to_numpy()
    subf   = df["Sub Frame"].to_numpy()

    mats = []
    for k in needed_idx:
        name = m_clean[k] if m_clean[k] else f"UNK{k}"
        mats.append(df[[f"{name}:X", f"{name}:Y", f"{name}:Z"]].to_numpy()[:, None, :])
    X = np.concatenate(mats, axis=1)

    return TrajData(frames, subf, m_full, m_clean, kept_idx, needed_idx, X)


def normalize_tensor(td: TrajData, cfg: NormConfig) -> np.ndarray:
    """Zwraca znormalizowany tensor (T, M_needed, 3) w kolejności td.needed_idx.
    Operacje: root-centering (pelvis), yaw-align (ASIS↔PSIS jeżeli dostępne), skala do target_pelvis.
    """
    T, M, _ = td.X.shape

    # Indeksy pomocnicze
    name_to_needed_pos: Dict[str, int] = {}
    for pos, orig_idx in enumerate(td.needed_idx):
        name_to_needed_pos[td.markers_clean[orig_idx]] = pos

    def get_marker(name: str) -> Optional[np.ndarray]:
        p = name_to_needed_pos.get(name)
        return td.X[:, p, :] if p is not None else None

    LASI = get_marker("LASI")
    RASI = get_marker("RASI")
    if LASI is None or RASI is None:
        raise ValueError("Brak wymaganych markerów LASI/RASI do centrowania i skali.")

    pelvis = (LASI + RASI) * 0.5  # (T,3)

    # Root-centering
    Xc = td.X - pelvis[:, None, :]

    # Yaw: preferuj przód-tył z PSIS
    LPSI = get_marker("LPSI")
    RPSI = get_marker("RPSI")
    if LPSI is not None and RPSI is not None:
        asis_mid = pelvis
        psis_mid = (LPSI + RPSI) * 0.5
        fwd = asis_mid[:, :2] - psis_mid[:, :2]   # XY
        # kąt między +X a fwd; chcemy wyrównać do +Y → obrót o (pi/2 - phi)
        phi = np.arctan2(fwd[:, 1], fwd[:, 0])
        theta = (np.pi / 2.0) - phi
    else:
        # fallback: osiuj oś LASI→RASI do +X (jak w szkicu)
        hipvec = (RASI - LASI)[:, :2]
        theta = -np.arctan2(hipvec[:, 1], hipvec[:, 0])

    # wektoryzowany obrót wokół Z dla wszystkich markerów
    c = np.cos(theta).astype(np.float32)[:, None]
    s = np.sin(theta).astype(np.float32)[:, None]

    x = Xc[:, :, 0]
    y = Xc[:, :, 1]
    z = Xc[:, :, 2]  # bez zmian przy yaw

    xr = x * c - y * s
    yr = x * s + y * c

    Xr = np.stack([xr, yr, z], axis=2)  # (T,M,3)

    # Skala: mediana szerokości ASIS w oknie
    if cfg.window is not None:
        s0, s1 = cfg.window
    else:
        s0, s1 = 0, min(T, 50)
    asis_dist = np.linalg.norm((RASI - LASI)[s0:s1], axis=1)
    ref = float(np.median(asis_dist))
    if ref <= 0:
        raise ValueError("Nieprawidłowa szerokość ASIS (mediana = 0).")
    scale = cfg.target_pelvis / ref
    Xn = Xr * scale

    return Xn.astype(np.float32, copy=False)

# ------------------------- Zapis pliku -------------------------

def write_rebuilt(
    in_lines: List[str], angles: SectionMeta, traj: SectionMeta,
    td: TrajData, Xn: np.ndarray, cfg: NormConfig, out_path: Path, delim_in: str
):
    """Szybkie odtworzenie pliku:
    - sekcję kątów kopiujemy w całości (od początku do tuż przed tytułem Trajectories),
    - sekcję Trajectories piszemy na nowo (markery filtrowane, jednostki wg cfg.unit_label),
      dane w kolejności oryginalnych markerów *po filtrze*.
    """
    out_delim = ","
    out_path.parent.mkdir(parents=True, exist_ok=True)

    m_full, m_clean = td.markers_full, td.markers_clean
    kept_idx = td.kept_idx

    # map: oryginalny idx markera -> pozycja w macierzy Xn (needed)
    orig_to_needed_pos = {orig: pos for pos, orig in enumerate(td.needed_idx)}

    with open(out_path, "w", encoding="utf-8", newline="") as fout:
        w = csv.writer(fout, delimiter=out_delim)

        # ===== Sekcja 1: kąty =====
        # od początku pliku do linii title Trajectories (exclusive)
        for i in range(0, traj.title_idx):
            w.writerow(in_lines[i].rstrip("\r\n").split(delim_in))

        # ===== Sekcja 2: Trajectories =====
        w.writerow(in_lines[traj.title_idx].rstrip("\r\n").split(delim_in))  # Title
        w.writerow(in_lines[traj.count_idx].rstrip("\r\n").split(delim_in))  # Count

        # Markers line: 'name,,,' co 3 kolumny, z pełnymi nazwami jak w oryginale
        row_markers = ["", ""]
        for k in kept_idx:
            row_markers += [m_full[k], "", ""]
        w.writerow(row_markers)

        # Header: Frame, Sub Frame, X,Y,Z per marker
        row_header = ["Frame", "Sub Frame"]
        for _ in kept_idx:
            row_header += ["X", "Y", "Z"]
        w.writerow(row_header)

        # Units
        unit = cfg.unit_label
        row_units = ["", ""]
        for _ in kept_idx:
            row_units += [unit, unit, unit]
        w.writerow(row_units)

        # ===== Dane =====
        T = Xn.shape[0]
        # wartości w kolejności kept_idx
        for t in range(T):
            out_vals: List[float] = []
            for k in kept_idx:
                pos = orig_to_needed_pos.get(k)
                if pos is None:
                    out_vals += ["", "", ""]
                else:
                    out_vals += [
                        f"{Xn[t, pos, 0]:.6f}",
                        f"{Xn[t, pos, 1]:.6f}",
                        f"{Xn[t, pos, 2]:.6f}",
                    ]
            w.writerow([int(td.frames[t]), int(td.subframes[t])] + out_vals)


# ------------------------- Główny pipeline jednego pliku -------------------------

def process_file(path: Path, out_path: Path, cfg: NormConfig) -> Path:
    lines = path.read_text(encoding="utf-8").splitlines(True)
    delim = detect_delimiter(lines)
    angles, traj = find_section_indices(lines)

    td = load_traj_fast(path, lines, traj, cfg, delim)
    Xn = normalize_tensor(td, cfg)

    write_rebuilt(lines, angles, traj, td, Xn, cfg, out_path, delim)
    return out_path


# ------------------------- CLI / Batch -------------------------

def main():
    p = argparse.ArgumentParser(description="Fast Vicon CSV normalizer (pelvis center, yaw, scale). Mirror katalogów.")
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument("--in", dest="inp", type=Path, help="Ścieżka do pojedynczego pliku CSV")

    p.add_argument("--out", dest="out", type=Path, help="Ścieżka wyjściowa (dla pojedynczego pliku)")

    p.add_argument("--in-root", dest="in_root", type=Path, default=Path("../data/csv/manual/calculated"),
                   help="Katalog wejściowy (domyślnie 'csv')")
    p.add_argument("--out-root", dest="out_root", type=Path, default=Path("../data/csv/manual/normalized"),
                   help="Katalog wyjściowy (domyślnie 'normalized')")
    p.add_argument("--suffix", default="", help="Opcjonalny sufiks nazwy pliku (np. _norm). Domyślnie pusty")

    p.add_argument("--window", nargs=2, type=int, metavar=("START","STOP"), default=(0, 50),
                   help="Okno [start, stop) do estymacji skali ASIS (w klatkach)")
    p.add_argument("--target-pelvis", type=float, default=1.0, help="Docelowa szerokość ASIS po skalowaniu")
    p.add_argument("--unit-label", type=str, default="norm", help="Etykieta jednostek w sekcji Trajectories (np. 'norm' lub 'mm')")
    p.add_argument("--skip-marker", action="append", default=None,
                   help="Marker do pominięcia w wyjściu (można podać wiele). Domyślnie: CentreOfMass, CentreOfMassFloor")
    p.add_argument("--keep-marker", action="append", default=None,
                   help="Wymuś utrzymanie danego markera (nawet jeśli w skip). Można podać wiele.")

    args = p.parse_args()

    skip = tuple(args.skip_marker) if args.skip_marker else ("CentreOfMass", "CentreOfMassFloor")
    keep = tuple(args.keep_marker) if args.keep_marker else ()

    cfg = NormConfig(window=tuple(args.window), target_pelvis=args.target_pelvis,
                     unit_label=args.unit_label, skip_markers=skip, force_keep=keep)

    # Tryb pojedynczego pliku → jeśli nie podano --out, zmirroruj strukturę względem in-root do out-root
    if args.inp:
        inp = args.inp
        if args.out is not None:
            out_path = args.out
        else:
            try:
                rel = inp.resolve().relative_to(args.in_root.resolve())
            except Exception:
                rel = Path(inp.name)
            out_path = (args.out_root / rel)
            if args.suffix:
                out_path = out_path.with_name(out_path.stem + args.suffix + out_path.suffix)
        res = process_file(inp, out_path, cfg)
        print(f"[OK] {inp} -> {res}")
        return

    # Tryb drzewa: przejdź całe in_root
    files = sorted(args.in_root.rglob('*.csv'))
    print(f"Znaleziono {len(files)} plików w {args.in_root}.")
    for f in files:
        try:
            rel = f.resolve().relative_to(args.in_root.resolve())
            out = args.out_root / rel
            if args.suffix:
                out = out.with_name(out.stem + args.suffix + out.suffix)
            res = process_file(f, out, cfg)
            print(f"[OK] {f} -> {res}")
        except Exception as e:
            print(f"[BŁĄD] {f}: {e}")


if __name__ == "__main__":
    main()
