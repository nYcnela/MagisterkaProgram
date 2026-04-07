import argparse
from pathlib import Path
import numpy as np
import json

import pandas as pd

from utils import (
    SectionMeta, AnglesData, TrajData,
    detect_delimiter, find_section_indices, 
    load_angles_fast, load_trajs_fast,
)

def export_stability_events(intervals_dict, angles_dict, t):
    """
    Eksportuje wykryte okresy stabilności jako listę eventów (bez opakowania w dict).
    """
    events = []

    for key, intervals in intervals_dict.items():
        angles = angles_dict[key]

        # joint type
        if "Shoulder" in key:
            joint = "shoulder"
        elif "Elbow" in key:
            joint = "elbow"
        else:
            joint = "unknown"

        # side
        side = "L" if key.startswith("L") else "R"

        # axis
        if key.endswith("X"):
            axis = "X"
        elif key.endswith("Y"):
            axis = "Y"
        else:
            axis = "?"

        for start_idx, end_idx in intervals:
            seg = angles[start_idx:end_idx + 1]
            if len(seg) == 0:
                continue
            min_angle = round(float(np.min(seg)), 2)
            max_angle = round(float(np.max(seg)), 2)

            events.append({
                "label": f"{side} {joint} {axis} stable start",
                "time": round(float(t[start_idx]), 2),
                "min_angle": min_angle,
                "max_angle": max_angle
            })
            events.append({
                "label": f"{side} {joint} {axis} stable end",
                "time": round(float(t[end_idx]), 2),
                "min_angle": min_angle,
                "max_angle": max_angle
            })

    return events


def stable_intervals(
        signal: np.ndarray,
        fps: float,
        min_thresh: float = 10.0,  # Minimalny próg stabilności (w stopniach)
        max_thresh: float = 20.0 , # Maksymalny próg stabilności (w stopniach)
        window_size: float = 0.8,
        min_duration: float = 0.8,
        thresh_factor: float = 0.5,  # Jaką część odchylenia standardowego uznać za próg
) -> list[tuple[int, int]]:
    """
    Zwraca listę (start_idx, end_idx) dla stabilnych fragmentów sygnału.
    Używa ADAPTACYJNEGO progu stabilności opartego na odchyleniu standardowym sygnału.
    """
    win = int(window_size * fps)
    min_len = int(min_duration * fps)

    if len(signal) < win:
        return []

    signal_std = np.std(signal)
    adaptive_thresh = signal_std * thresh_factor

    thresh = np.clip(adaptive_thresh, min_thresh, max_thresh)
    print(f"  -> Dla sygnału o std={signal_std:.2f}, użyto progu stabilności: {thresh:.2f}")

    # --- Reszta logiki pozostaje bez zmian ---
    s = pd.Series(signal)
    rolling_max = s.rolling(window=win, center=True, min_periods=int(win * 0.8)).max()
    rolling_min = s.rolling(window=win, center=True, min_periods=int(win * 0.8)).min()
    rolling_range = rolling_max - rolling_min

    stable_mask = (rolling_range < thresh).fillna(False).to_numpy()

    intervals = []
    i = 0
    while i < len(stable_mask):
        if stable_mask[i]:
            j = i
            while j < len(stable_mask) and stable_mask[j]:
                j += 1

            if (j - i) >= min_len:
                intervals.append((i, j))
            i = j
        else:
            i += 1

    return intervals

def build_arm_stability_metrics(intervals_dict, angles_dict, t):
    """
    Buduje strukturę arm_stability_metrics w formacie:
    {
        "Lshoulder_x": {
            "stable_period_1": {...},
            "stable_period_2": {...}
        },
        "Rshoulder_x": {},
        ...
    }
    """
    metrics = {
        "Lshoulder_x": {},
        "Rshoulder_x": {},
        "Lshoulder_y": {},
        "Rshoulder_y": {},
        "LElbow_x": {},
        "RElbow_x": {}
    }

    for key, intervals in intervals_dict.items():
        if key not in angles_dict:
            continue

        signal = angles_dict[key]
        joint_key = (
            key.replace("ShoulderX", "shoulder_x")
               .replace("ShoulderY", "shoulder_y")
               .replace("ElbowX", "Elbow_x")
        )

        for i, (start_idx, end_idx) in enumerate(intervals, start=1):
            start_time = float(t[start_idx])
            end_time = float(t[end_idx])
            seg = signal[start_idx:end_idx+1]

            metrics[joint_key][f"stable_period_{i}"] = {
                "start_time_seconds": round(start_time, 2),
                "end_time_seconds": round(end_time, 2),
                "duration_seconds": round(end_time - start_time, 2),
                "angle_range_degrees": {
                    "min": round(float(seg.min()), 2),
                    "max": round(float(seg.max()), 2)
                }
            }

    return metrics

# --------------------------------------------------------------------------
# SEKCJA 3: GŁÓWNA LOGIKA PRZETWARZANIA I WIZUALIZACJI
# --------------------------------------------------------------------------
def process_file(csv_path: Path, in_root: Path, in_json_root: Path, out_json_root: Path, fs: float):
    """
    Otwiera istniejący JSON z katalogu 4segmentation_bounds,
    dodaje analizę ramion i zapisuje pełny wynik do katalogu 7arms_position_recognition.
    """
    print(f"Processing CSV: {csv_path.name}")

    # Ścieżka JSON wejściowego (z katalogu 4_segmentation_bounds)
    relative_path = csv_path.resolve().relative_to(in_root.resolve()).with_suffix(".json")
    source_json_path = in_json_root / relative_path

    if not source_json_path.is_file():
        print(f"  -> WARNING: Corresponding JSON file not found at '{source_json_path}'. Skipping.")
        return

    try:
        # --- Wczytaj dane z CSV ---
        lines = csv_path.read_text(encoding="utf-8").splitlines(True)
        delim = detect_delimiter(lines)
        angles, traj = find_section_indices(lines)
        angles_data = load_angles_fast(csv_path, lines, angles, delim)
        t = angles_data.frames / fs

        # Wyciągnięcie przykładowych sygnałów
        LShoulder_idx = angles_data.markers_clean.index("LShoulderAngles")
        RShoulder_idx = angles_data.markers_clean.index("RShoulderAngles")
        LElbow_idx = angles_data.markers_clean.index("LElbowAngles")
        RElbow_idx = angles_data.markers_clean.index("RElbowAngles")

        LShoulderX = angles_data.X[:, LShoulder_idx, 0]
        RShoulderX = angles_data.X[:, RShoulder_idx, 0]
        LShoulderY = angles_data.X[:, LShoulder_idx, 1]  # Y
        RShoulderY = angles_data.X[:, RShoulder_idx, 1]  # Y
        LElbowX = angles_data.X[:, LElbow_idx, 0]  # X
        RElbowX = angles_data.X[:, RElbow_idx, 0]  # X

        # Oblicz interwały stabilności
        intervals_dict = {
            "LShoulderX": stable_intervals(LShoulderX, fs, min_thresh=20, max_thresh=25),
            "RShoulderX": stable_intervals(RShoulderX, fs, min_thresh=20, max_thresh=25),
            "LShoulderY": stable_intervals(LShoulderY, fs, min_thresh=10, max_thresh=20),
            "RShoulderY": stable_intervals(RShoulderY, fs, min_thresh=10, max_thresh=20),
            "LElbowX": stable_intervals(LElbowX, fs, min_thresh=5, max_thresh=15, window_size=1.0, min_duration=1.0, thresh_factor=0.4),
            "RElbowX": stable_intervals(RElbowX, fs, min_thresh=5, max_thresh=15, window_size=1.0, min_duration=1.0, thresh_factor=0.4)
        }
        angles_dict = {
            "LShoulderX": LShoulderX,
            "RShoulderX": RShoulderX,
            "LShoulderY": LShoulderY,
            "RShoulderY": RShoulderY,
            "LElbowX": LElbowX,
            "RElbowX": RElbowX
        }

        # Eksport analizy ramion jako lista eventów
        # arm_stability_events = export_stability_events(intervals_dict, angles_dict, t)
        arm_stability_metrics = build_arm_stability_metrics(intervals_dict, angles_dict, t)

        # --- Wczytaj istniejący JSON z 4segmentation_bounds ---
        with open(source_json_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)

        # Dodaj do sekcji "events"
        if "events" not in existing_data:
            existing_data["events"] = []

        # Posortuj wszystkie eventy po czasie
        existing_data["events"].sort(key=lambda x: x.get("time", float("inf")))
        existing_data["arm_stability_metrics"] = arm_stability_metrics

        # --- Zapisz do katalogu 7arms_position_recognition ---
        target_json_path = out_json_root / relative_path
        target_json_path.parent.mkdir(parents=True, exist_ok=True)

        with open(target_json_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)

        print(f"  -> SUCCESS: Created '{target_json_path}' with arm stability data.")

    except Exception as e:
        print(f"  -> ERROR: Failed to process file {csv_path.name}. Reason: {e}")

# --------------------------------------------------------------------------
# SEKCJA 4: URUCHOMIENIE SKRYPTU Z LINII KOMEND
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analizuje pliki CSV z danymi o ruchu i dodaje analizę ramion do JSON."
    )
    parser.add_argument("--in-root", type=Path, default=Path("../data/csv/manual/downsampled"),
                        help="Katalog wejściowy zawierający podkatalogi z plikami CSV.")
    parser.add_argument("--in-json-root", type=Path, default=Path("../data/json/manual/pipeline/4_segmentation_bounds"),
                        help="Katalog wejściowy zawierający istniejące JSON-y z segmentacją.")
    parser.add_argument("--out-json-root", type=Path, default=Path("../data/json/manual/pipeline/7_arms_position"),
                        help="Katalog wyjściowy, do którego zostaną zapisane JSON-y z analizą ramion.")
    parser.add_argument("--fs", type=float, default=50.0,
                        help="Częstotliwość próbkowania w Hz.")

    args = parser.parse_args()

    if not args.in_root.is_dir():
        print(f"Błąd: Katalog wejściowy '{args.in_root}' nie istnieje.")
        return

    csv_files = list(args.in_root.glob("*/*.csv"))
    if not csv_files:
        print(f"Nie znaleziono żadnych plików CSV w katalogu '{args.in_root}'.")
        return

    for in_csv in csv_files:
        process_file(in_csv, args.in_root, args.in_json_root, args.out_json_root, args.fs)




if __name__ == "__main__":
    main()
