#!/usr/bin/env python3
"""
Filtr + downsampling dla znormalizowanych plików Vicon/Nexus (CSV, 2 sekcje).
Wersja ostateczna: Poprawiony błąd zasięgu i gwarancja tej samej długości obu sekcji.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, resample_poly


def interpolate_nans(X: np.ndarray) -> np.ndarray:
    """Uzupełnia NaN liniowo wzdłuż osi czasu (wierszy)."""
    df = pd.DataFrame(X)
    df = df.interpolate(method="linear", axis=0, limit_direction="both")
    return df.to_numpy()


# ---------- Struktura sekcji ----------
@dataclass
class SectionMeta:
    header_idx: int;
    title_idx: int;
    count_idx: int;
    marker_idx: int
    units_idx: int;
    data_start: int;
    data_end: int


def find_sections(lines: List[str]) -> Tuple[SectionMeta, SectionMeta]:
    hdrs = [i for i, ln in enumerate(lines) if ln.strip().startswith("Frame,Sub Frame")]
    if len(hdrs) < 2: raise RuntimeError("Nie znaleziono dwóch sekcji 'Frame,Sub Frame'.")

    def meta(h_idx: int, next_h: Optional[int]) -> SectionMeta:
        return SectionMeta(h_idx, h_idx - 3, h_idx - 2, h_idx - 1, h_idx + 1, h_idx + 2,
                           next_h - 3 if next_h is not None else len(lines))

    a, t = meta(hdrs[0], hdrs[1]), meta(hdrs[1], None)
    if "deg" not in lines[a.units_idx].lower() and "mm" in lines[a.units_idx].lower():
        a, t = t, a
    return a, t


def parse_triplet_markers(marker_line: str) -> Tuple[List[str], List[str]]:
    row = marker_line.rstrip("\n").split(",");
    data = row[2:];
    n = len(data) // 3
    full, clean = [], []
    for k in range(n):
        name = (data[3 * k] or "").strip()
        full.append(name)
        clean.append(name.rsplit(":", 1)[1].strip() if ":" in name else name)
    return full, clean


# ---------- Filtr i resampling ----------
def design_lowpass(fs: float, target_fs: float, cutoff: float, order: int = 4):
    max_cut = 0.45 * target_fs;
    fc = min(cutoff, max_cut);
    nyq = 0.5 * fs;
    wn = fc / nyq
    if not (0 < wn < 1): raise ValueError(f"Nieprawidłowe parametry filtra: fc={fc}, fs={fs}")
    b, a = butter(order, wn, btype='low', analog=False)
    return b, a, fc


def filter_and_resample_block(X: np.ndarray, fs: float, target_fs: float, cutoff: float, order: int) -> np.ndarray:
    if np.isnan(X).any(): X = interpolate_nans(X)
    if fs == target_fs:
        b, a, _ = design_lowpass(fs, target_fs, cutoff, order)
        return filtfilt(b, a, X, axis=0)
    b, a, _ = design_lowpass(fs, target_fs, cutoff, order)
    Xf = filtfilt(b, a, X, axis=0)
    up = int(round(target_fs));
    down = int(round(fs))
    Y = resample_poly(Xf, up=up, down=down, axis=0)
    return Y


# ---------- IO ----------
def read_traj_matrix(path: Path, traj: SectionMeta):
    lines = path.read_text(encoding="utf-8").splitlines(True)
    full, clean = parse_triplet_markers(lines[traj.marker_idx])
    kept_idx = [i for i, name in enumerate(clean) if name]
    usecols = [0, 1] + [c for k in kept_idx for c in (2 + 3 * k, 3 + 3 * k, 4 + 3 * k)]
    nrows = traj.data_end - traj.data_start
    colnames = ["Frame", "Sub Frame"] + [f"{clean[i]}:{ax}" for i in kept_idx for ax in "XYZ"]
    df = pd.read_csv(path, skiprows=traj.data_start, nrows=nrows, header=None,
                     usecols=usecols, names=colnames, dtype=np.float32, engine="c", on_bad_lines='skip')
    data_cols = [f"{clean[i]}:{ax}" for i in kept_idx for ax in "XYZ"]
    X = df[data_cols].to_numpy()
    return lines, full, clean, kept_idx, df["Frame"].to_numpy(), df["Sub Frame"].to_numpy(), X


def write_out(lines_in: List[str], angles: SectionMeta, traj: SectionMeta,
              Xa: np.ndarray, Xt: np.ndarray, out_path: Path, target_fs: float):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='') as fout:
        w = csv.writer(fout)
        num_frames = len(Xa)
        frames_col = np.arange(1, num_frames + 1);
        subframes_col = np.zeros(num_frames, dtype=int)

        # ===== ANGLES =====
        fout.write(lines_in[angles.title_idx])
        fout.write(f"{int(round(target_fs))}\n")
        fout.write(lines_in[angles.marker_idx])
        fout.write(lines_in[angles.header_idx])
        fout.write(lines_in[angles.units_idx])
        for i in range(num_frames): w.writerow([frames_col[i], subframes_col[i]] + [f"{v:.6f}" for v in Xa[i]])

        # ===== TRAJECTORIES =====
        fout.write(lines_in[traj.title_idx])
        fout.write(f"{int(round(target_fs))}\n")
        fout.write(lines_in[traj.marker_idx])
        fout.write(lines_in[traj.header_idx])
        fout.write(lines_in[traj.units_idx])
        for i in range(num_frames): w.writerow([frames_col[i], subframes_col[i]] + [f"{v:.6f}" for v in Xt[i]])


# ---------- Główny proces ----------
def process_one(path: Path, in_root: Path, out_root: Path, target_fps: float,
                src_fps_opt: Optional[float], cutoff: float, order: int):
    lines = path.read_text(encoding='utf-8').splitlines(True)
    angles, traj = find_sections(lines)

    if src_fps_opt is not None:
        fs = float(src_fps_opt)
    else:
        try:
            fs = float(lines[traj.count_idx].strip())
        except Exception:
            fs = 100.0

    _, _, _, _, _, _, Xa = read_traj_matrix(path, angles)
    Xa_f = filter_and_resample_block(Xa, fs=fs, target_fs=target_fps, cutoff=cutoff, order=order)

    _, _, _, _, _, _, Xt = read_traj_matrix(path, traj)
    Xt_f = filter_and_resample_block(Xt, fs=fs, target_fs=target_fps, cutoff=cutoff, order=order)

    if Xa_f.shape[0] != Xt_f.shape[0]:
        min_len = min(Xa_f.shape[0], Xt_f.shape[0])
        print(
            f"    [Ostrzeżenie] Niezgodność długości po resamplingu: Kąty={Xa_f.shape[0]}, Trajektorie={Xt_f.shape[0]}. Wyrównywanie do {min_len}.")
        Xa_f = Xa_f[:min_len]
        Xt_f = Xt_f[:min_len]

    # KLUCZOWA ZMIANA 2: Używamy `in_root` zamiast `args.in_root`
    out_path = out_root / path.relative_to(in_root)

    write_out(lines, angles, traj, Xa_f, Xt_f, out_path, target_fps)
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description="Filter + downsample Angles & Trajectories in normalized Vicon CSV (mirror tree).")
    ap.add_argument('--in-root', type=Path, default=Path('../data/csv/manual/normalized'),
                    help="Katalog wejściowy (domyślnie 'normalized')")
    ap.add_argument('--out-root', type=Path, default=Path('../data/csv/manual/downsampled'),
                    help="Katalog wyjściowy (domyślnie 'downsampled')")
    ap.add_argument('--target-fps', type=float, default=50.0, help='Docelowy FPS (np. 50)')
    ap.add_argument('--src-fps', type=float, default=None,
                    help='Źródłowy FPS; jeśli brak, spróbuj wykryć z pliku (Count)')
    ap.add_argument('--cutoff', type=float, default=8.0, help='Częstotliwość odcięcia low-pass (Hz)')
    ap.add_argument('--order', type=int, default=4, help='Rząd filtra Butterwortha')
    args = ap.parse_args()

    files = sorted(args.in_root.rglob('*.csv'))
    print(f"Znaleziono {len(files)} plików w {args.in_root}.")

    for f in files:
        try:
            out = process_one(f, args.in_root, args.out_root, target_fps=args.target_fps,
                              src_fps_opt=args.src_fps, cutoff=args.cutoff, order=args.order)
            print(f"[OK] {f} -> {out}")
        except Exception as e:
            print(f"[BŁĄD] {f}: {e}")


if __name__ == '__main__':
    main()