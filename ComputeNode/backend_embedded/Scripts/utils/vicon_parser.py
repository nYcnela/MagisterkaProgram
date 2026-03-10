"""
Wspólne narzędzia do parsowania plików CSV z Vicon/Nexus.
Obsługuje format z dwiema sekcjami: Angles i Trajectories.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd


# =============================================================================
# DATACLASSES - struktury danych
# =============================================================================

@dataclass
class SectionMeta:
    """Metadane sekcji w pliku CSV Vicon."""
    header_idx: int      # linia z "Frame,Sub Frame"
    title_idx: int       # linia z tytułem sekcji (np. "Trajectories")
    count_idx: int       # linia z liczbą klatek
    marker_idx: int      # linia z listą markerów
    units_idx: int       # linia z jednostkami
    data_start: int      # pierwsza linia danych
    data_end: int        # pierwsza linia ZA danymi (exclusive)


@dataclass
class AnglesData:
    """Dane kątowe z sekcji Angles."""
    frames: np.ndarray
    subframes: np.ndarray
    markers_full: List[str]
    markers_clean: List[str]
    kept_idx: List[int]
    X: np.ndarray        # (T, M, 3) - dane XYZ dla każdego markera
    units: str


@dataclass
class TrajData:
    """Dane trajektorii z sekcji Trajectories."""
    frames: np.ndarray
    subframes: np.ndarray
    markers_full: List[str]
    markers_clean: List[str]
    kept_idx: List[int]
    X: np.ndarray        # (T, M, 3) - dane XYZ dla każdego markera
    units: str


# Alias dla kompatybilności wstecznej
MotionData = TrajData


# =============================================================================
# PARSOWANIE PLIKU CSV
# =============================================================================

def detect_delimiter(lines: List[str]) -> str:
    """Wykrywa delimiter (przecinek lub średnik) w pliku CSV."""
    for ln in lines[:200]:
        m = re.search(r'Frame\s*([,;])\s*Sub Frame', ln)
        if m:
            return m.group(1)
    return ';' if any(';' in ln for ln in lines[:50]) else ','


def find_section_indices(lines: List[str]) -> Tuple[SectionMeta, SectionMeta]:
    """
    Znajduje metadane dwóch sekcji: (angles, trajectories).
    
    Zakłada układ:
        <Title>
        <Count>
        <Markers>
        Frame,Sub Frame
        <Units>
        <Data...>
    """
    hdrs = [i for i, ln in enumerate(lines) 
            if re.match(r'^\s*Frame\s*[,;]\s*Sub Frame\b', ln)]
    
    if len(hdrs) < 2:
        raise RuntimeError("Nie znaleziono dwóch sekcji 'Frame,Sub Frame' w pliku.")

    def build_meta(h_idx: int, next_header: Optional[int]) -> SectionMeta:
        return SectionMeta(
            header_idx=h_idx,
            title_idx=h_idx - 3,
            count_idx=h_idx - 2,
            marker_idx=h_idx - 1,
            units_idx=h_idx + 1,
            data_start=h_idx + 2,
            data_end=next_header - 3 if next_header is not None else len(lines)
        )

    angles = build_meta(hdrs[0], hdrs[1])
    traj = build_meta(hdrs[1], None)
    
    # pierwsza sekcja to deg (Angles), druga to mm (Trajectories)
    if "deg" not in lines[angles.units_idx].lower() and "mm" in lines[angles.units_idx].lower():
        angles, traj = traj, angles
    
    return angles, traj


def parse_markers(marker_line: str, delim: str) -> Tuple[List[str], List[str]]:
    """
    Parsuje linię markerów.
    
    Returns:
        (markers_full, markers_clean) - pełne nazwy i oczyszczone (bez prefixu)
    """
    arr = marker_line.rstrip("\n").split(delim)[2:]
    n_triplets = len(arr) // 3
    full, clean = [], []
    
    for k in range(n_triplets):
        name = (arr[3 * k] or "").strip()
        full.append(name)
        clean.append(name.rsplit(":", 1)[1].strip() if ":" in name else name)
    
    return full, clean


# =============================================================================
# ŁADOWANIE DANYCH
# =============================================================================

def load_angles_fast(path: Path, lines: List[str], meta: SectionMeta, delim: str) -> AnglesData:
    """Szybkie ładowanie danych kątowych z sekcji Angles."""
    m_full, m_clean = parse_markers(lines[meta.marker_idx], delim)
    kept_idx = [i for i, name in enumerate(m_clean) if name]
    usecols = [0, 1] + [c for k in kept_idx for c in (2 + 3*k, 3 + 3*k, 4 + 3*k)]
    nrows = meta.data_end - meta.data_start
    
    cols = ["Frame", "Sub Frame"] + [
        f"{m_clean[k] if m_clean[k] else f'UNK{k}'}:{ax}" 
        for k in kept_idx for ax in "XYZ"
    ]
    
    df = pd.read_csv(
        path, skiprows=meta.data_start, nrows=nrows, header=None,
        usecols=usecols, names=cols, dtype=np.float32, 
        engine="c", sep=delim, on_bad_lines='skip'
    )
    
    frames = df["Frame"].to_numpy()
    subf = df["Sub Frame"].to_numpy()
    mats = [
        df[[f"{m_clean[k] if m_clean[k] else f'UNK{k}'}:{ax}" for ax in "XYZ"]].to_numpy()[:, None, :]
        for k in kept_idx
    ]
    units = lines[meta.units_idx].strip() if meta.units_idx is not None else "deg"
    
    return AnglesData(frames, subf, m_full, m_clean, kept_idx, np.concatenate(mats, axis=1), units)


def load_trajectories_fast(path: Path, lines: List[str], meta: SectionMeta, delim: str) -> TrajData:
    """Szybkie ładowanie danych trajektorii z sekcji Trajectories."""
    m_full, m_clean = parse_markers(lines[meta.marker_idx], delim)
    kept_idx = [i for i, name in enumerate(m_clean) if name]
    usecols = [0, 1] + [c for k in kept_idx for c in (2 + 3*k, 3 + 3*k, 4 + 3*k)]
    nrows = meta.data_end - meta.data_start
    
    cols = ["Frame", "Sub Frame"] + [
        f"{m_clean[k] if m_clean[k] else f'UNK{k}'}:{ax}" 
        for k in kept_idx for ax in "XYZ"
    ]
    
    df = pd.read_csv(
        path, skiprows=meta.data_start, nrows=nrows, header=None,
        usecols=usecols, names=cols, dtype=np.float32,
        engine="c", sep=delim, on_bad_lines='skip'
    )
    
    frames = df["Frame"].to_numpy()
    subf = df["Sub Frame"].to_numpy()
    mats = [
        df[[f"{m_clean[k] if m_clean[k] else f'UNK{k}'}:{ax}" for ax in "XYZ"]].to_numpy()[:, None, :]
        for k in kept_idx
    ]
    
    # Wykryj jednostki
    units_line = lines[meta.units_idx] if meta.units_idx is not None else ""
    if re.search(r"\bnorm\b", units_line, re.I):
        units = "norm"
    elif re.search(r"\bmm\b", units_line, re.I):
        units = "mm"
    else:
        units = ""
    
    return TrajData(frames, subf, m_full, m_clean, kept_idx, np.concatenate(mats, axis=1), units)


# Alias dla kompatybilności
load_trajs_fast = load_trajectories_fast


# =============================================================================
# HELPERY - wykrywanie z nazwy pliku
# =============================================================================

def detect_gender_from_filename(path: str | Path) -> str:
    """
    Wykrywa płeć na podstawie nazwy pliku.
    
    Returns:
        'male' jeśli plik zaczyna się od 'm_', 'female' w przeciwnym razie
    """
    fname = Path(path).name.lower()
    return "male" if fname.startswith("m_") else "female"


def detect_step_from_filename(path: str | Path) -> str:
    """
    Wykrywa typ ruchu na podstawie nazwy pliku.
    
    Returns:
        'step' jeśli plik zawiera 'krok', 'static' w przeciwnym razie
    """
    fname = Path(path).name.lower()
    return "step" if "krok" in fname else "static"


# =============================================================================
# FUNKCJE POMOCNICZE DO INTERPOLACJI
# =============================================================================

def interpolate_nans(X: np.ndarray) -> np.ndarray:
    """Uzupełnia NaN liniowo wzdłuż osi czasu (wierszy)."""
    df = pd.DataFrame(X)
    df = df.interpolate(method="linear", axis=0, limit_direction="both")
    return df.to_numpy()
