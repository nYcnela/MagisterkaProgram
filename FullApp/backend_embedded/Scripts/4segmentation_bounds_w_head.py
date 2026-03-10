import argparse
from typing import Tuple, List, Optional
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks
import json

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import (
    SectionMeta, AnglesData, MotionData,
    detect_delimiter, find_section_indices,
    load_angles_fast, load_trajectories_fast,
    detect_gender_from_filename, detect_step_from_filename
)

# --------------------------------------------------------------------------
# SEKCJA 2: ALGORYTMY DETEKCJI
# --------------------------------------------------------------------------

# --- Granice wg metody ukłonu: minima po bokach piku + progi procentowe ---
def find_bow_bounds(signal: np.ndarray, peak_idx: int,
                    alpha_start: float = 0.15,
                    alpha_end: float = 0.15) -> Tuple[int, int]:
    minima_indices, _ = find_peaks(-signal)

    left_mins = [m for m in minima_indices if m < peak_idx]
    left_boundary = max(left_mins) if left_mins else 0

    right_mins = [m for m in minima_indices if m > peak_idx]
    right_boundary = min(right_mins) if right_mins else len(signal) - 1

    peak_val = signal[peak_idx]
    start_floor = signal[left_boundary]
    end_floor = signal[right_boundary]

    thr_start = start_floor + alpha_start * (peak_val - start_floor)
    thr_end = end_floor + alpha_end * (peak_val - end_floor)

    start = peak_idx
    while start > left_boundary and signal[start] > thr_start:
        start -= 1

    end = peak_idx
    while end < right_boundary and signal[end] > thr_end:
        end += 1

    return start, end

# >>> NOWE: uniwersalne granice zdarzenia oparte na piku (używa find_bow_bounds)
def find_event_bounds(signal: np.ndarray,
                      peak_idx: int,
                      alpha_start: float = 0.05,
                      alpha_end: float = 0.05,
                      start_offset_frames: int = 0,
                      end_offset_frames: int = 0) -> Tuple[int, int]:
    s, e = find_bow_bounds(signal, peak_idx, alpha_start=alpha_start, alpha_end=alpha_end)
    s = max(0, s + int(start_offset_frames))
    e = max(s + 1, e - int(end_offset_frames))
    return int(s), int(e)

def detect_bow_events(
        Lknee: np.ndarray, Rknee: np.ndarray, fs: float,
        Lshoulder: Optional[np.ndarray] = None, Rshoulder: Optional[np.ndarray] = None,
        *,
        min_prominence: float = 18.0,
        bow_prominence: Optional[float] = None,
        pair_window_s: float = 0.50,
        bow_sync_s: float = 0.10,
        bow_depth_tol: float = 0.15,
        bow_min_abs: float = 25.0,
        shoulder_thresh: float = 10.0,
        shoulder_percentile: int = 90,
        male_shoulder_win_low_s: float = 0.00,
        male_shoulder_win_high_s: float = 0.35,
        gender: str = "female",
) -> List[Tuple[int, str]]:
    eff_prom = float(bow_prominence) if bow_prominence is not None else float(min_prominence)
    L_idx, _ = find_peaks(Lknee, prominence=eff_prom)
    R_idx, _ = find_peaks(Rknee, prominence=eff_prom)

    events = [{'frame': int(i), 'leg': 'L', 'depth': float(Lknee[i])} for i in L_idx] + \
             [{'frame': int(i), 'leg': 'R', 'depth': float(Rknee[i])} for i in R_idx]
    events.sort(key=lambda x: x['frame'])

    max_frame_dist = int(pair_window_s * fs)
    bow_frame_dist = int(bow_sync_s * fs)
    used_indices = set()
    final_events = []

    MAX_BOW_DURATION_S = 3.5

    adaptive_thr_R, adaptive_thr_L = None, None
    if gender == "male" and Lshoulder is not None and Rshoulder is not None:
        adaptive_thr_R = max(shoulder_thresh, np.percentile(Rshoulder, shoulder_percentile))
        adaptive_thr_L = max(shoulder_thresh, np.percentile(Lshoulder, shoulder_percentile))

    for i in range(len(events)):
        if i in used_indices:
            continue
        e1 = events[i]

        partner_idx = -1
        for j in range(i + 1, len(events)):
            if (events[j]['frame'] - e1['frame']) > max_frame_dist: break
            if events[j]['leg'] != e1['leg']:
                partner_idx = j
                break

        if partner_idx != -1:
            e2 = events[partner_idx]
            event_handled = False

            if gender == "female":
                is_synced = abs(e1['frame'] - e2['frame']) <= bow_frame_dist
                is_deep_enough = e1['depth'] >= bow_min_abs and e2['depth'] >= bow_min_abs
                avg_depth = 0.5 * (e1['depth'] + e2['depth'])
                are_depths_similar = avg_depth > 0 and abs(e1['depth'] - e2['depth']) < bow_depth_tol * avg_depth

                if is_synced and is_deep_enough and are_depths_similar:
                    s1, e1b = find_bow_bounds(Lknee if e1['leg'] == "L" else Rknee, e1['frame'])
                    s2, e2b = find_bow_bounds(Lknee if e2['leg'] == "L" else Rknee, e2['frame'])
                    bow_start, bow_end = min(s1, s2), max(e1b, e2b)

                    if (bow_end - bow_start) / fs < MAX_BOW_DURATION_S:
                        final_events.append((bow_start, "bow start"))
                        final_events.append((bow_end, "bow end"))
                        used_indices.update([i, partner_idx])
                        event_handled = True

            elif gender == "male" and adaptive_thr_L is not None:
                lead, other = (e1, e2) if e1['frame'] <= e2['frame'] else (e2, e1)
                shoulder_signal = Rshoulder if lead['leg'] == 'R' else Lshoulder
                shoulder_thresh_val = adaptive_thr_R if lead['leg'] == 'R' else adaptive_thr_L

                win_start = lead['frame'] + int(male_shoulder_win_low_s * fs)
                win_end = lead['frame'] + int(male_shoulder_win_high_s * fs)

                if shoulder_signal is not None and win_start < win_end:
                    win_end = min(win_end, len(shoulder_signal))
                    if np.max(shoulder_signal[win_start:win_end]) > shoulder_thresh_val:
                        s1, e1b = find_bow_bounds(Lknee if e1['leg'] == "L" else Rknee, e1['frame'])
                        s2, e2b = find_bow_bounds(Lknee if e2['leg'] == "L" else Rknee, e2['frame'])
                        bow_start, bow_end = min(s1, s2), max(e1b, e2b)

                        if (bow_end - bow_start) / fs < MAX_BOW_DURATION_S:
                            final_events.append((bow_start, f"bow start, {lead['leg']} lead"))
                            final_events.append((bow_end, f"bow end, {lead['leg']} lead"))
                            used_indices.update([i, partner_idx])
                            event_handled = True

    final_events.sort(key=lambda x: x[0])
    return final_events

def bow_events_to_windows(bow_events: List[Tuple[int, str]], fs: float, pad_s: float = 0.12):
    pad = int(pad_s * fs)
    wins, start = [], None
    for f, lab in sorted(bow_events, key=lambda x: x[0]):
        if "bow start" in lab:
            start = f
        elif "bow end" in lab and start is not None:
            wins.append((max(0, start - pad), f + pad))
            start = None
    return wins

def detect_side_steps(Lhip, Rhip, fs,
                      prominence=12.0,
                      angle_thresh=-14.0,
                      max_gap_s=1.0):
    if Lhip is None or Rhip is None or len(Lhip) < fs:
        return []
    max_gap_frames = int(max_gap_s * fs)
    L_idx, _ = find_peaks(-np.asarray(Lhip), prominence=prominence)
    R_idx, _ = find_peaks(-np.asarray(Rhip), prominence=prominence)
    L_idx = [i for i in L_idx if Lhip[i] < angle_thresh]
    R_idx = [i for i in R_idx if Rhip[i] < angle_thresh]
    events = [(i, "L") for i in L_idx] + [(i, "R") for i in R_idx]
    events.sort(key=lambda x: x[0])
    detected = []
    for k in range(len(events) - 1):
        f1, leg1 = events[k]
        f2, leg2 = events[k + 1]
        if leg1 != leg2 and (f2 - f1) <= max_gap_frames:
            detected.append((f1, "side step L" if leg1 == "L" else "side step R"))
    return detected

def merge_steps_with_side_labels(step_events, side_step_events, fs, overlap_s=0.25):
    def get_leg(label: str):
        if "L" in label: return "L"
        if "R" in label: return "R"
        return None

    def is_step_start(label: str): return "step" in label and "start" in label
    def is_step_end(label: str):   return "step" in label and "end" in label

    side_dict = {}
    for f, lbl in side_step_events:
        leg = get_leg(lbl)
        side_dict.setdefault(leg, []).append(f)

    events = list(step_events)
    used = set()

    for i, (f_start, lbl_start) in enumerate(events):
        if not is_step_start(lbl_start) or i in used:
            continue
        leg = get_leg(lbl_start)

        for j in range(i + 1, len(events)):
            f_end, lbl_end = events[j]
            if is_step_end(lbl_end) and get_leg(lbl_end) == leg:
                same_type = ("accented" in lbl_start) == ("accented" in lbl_end)
                if same_type:
                    has_side = any(f_start <= fs_ <= f_end for fs_ in side_dict.get(leg, []))
                    if has_side:
                        if "accented" in lbl_start:
                            events[i] = (f_start, lbl_start.replace("accented", "accented, side"))
                            events[j] = (f_end, lbl_end.replace("accented", "accented, side"))
                        else:
                            events[i] = (f_start, lbl_start.replace("step", "step (side)"))
                            events[j] = (f_end, lbl_end.replace("step", "step (side)"))
                    used.add(i); used.add(j)
                    break
    return sorted(events, key=lambda x: x[0])


# To jest funkcja z Twojego PIERWSZEGO skryptu - ona jest naszym źródłem prawdy o pikach
def detect_gait_peaks_only(Lknee, Rknee, fs, Lshoulder, Rshoulder, gender, **kwargs):
    """
    Ta funkcja jest wzięta 1:1 z Twojego pierwszego skryptu.
    Jej jedynym zadaniem jest znalezienie listy ZAUFANYCH pików.
    Zwraca listę: [(frame, 'L step'), (frame, 'R step (accented)'), ...]
    """
    # ... wklej tutaj CAŁĄ zawartość funkcji find_accented_gait_events z PIERWSZEGO skryptu ...
    # Upewnij się, że na końcu zwraca posortowaną listę `final_events`

    # Przykładowy szkielet (wklej tutaj swoją implementację)
    min_prominence = 18.0  # Użyj wartości, które dawały idealne wyniki
    L_idx, _ = find_peaks(Lknee, prominence=min_prominence)
    R_idx, _ = find_peaks(Rknee, prominence=min_prominence)

    # ... cała logika parowania i etykietowania z pierwszego skryptu ...

    events = []
    for i in L_idx: events.append({'frame': i, 'leg': 'L', 'depth': Lknee[i]})
    for i in R_idx: events.append({'frame': i, 'leg': 'R', 'depth': Rknee[i]})
    events.sort(key=lambda x: x['frame'])

    # ... itd. (pełna logika)
    # Na końcu funkcja powinna zwrócić coś w stylu:
    # final_events.sort(key=lambda x: x[0])
    # return final_events

    # Poniżej jest pełna implementacja z Twojego pierwszego kodu dla wygody:
    min_prominence = 18.0
    pair_window_s = 0.50
    bow_sync_s = 0.10
    bow_depth_tol = 0.15
    shoulder_thresh = 10.0
    shoulder_percentile = 90

    L_idx, _ = find_peaks(Lknee, prominence=min_prominence)
    R_idx, _ = find_peaks(Rknee, prominence=min_prominence)

    events = []
    for i in L_idx: events.append({'frame': i, 'leg': 'L', 'depth': Lknee[i]})
    for i in R_idx: events.append({'frame': i, 'leg': 'R', 'depth': Rknee[i]})
    events.sort(key=lambda x: x['frame'])

    max_frame_dist = int(pair_window_s * fs)
    bow_frame_dist = int(bow_sync_s * fs)
    used_indices = set()
    final_events = []

    if gender == "male" and Lshoulder is not None and Rshoulder is not None:
        adaptive_thr_R = max(shoulder_thresh, np.percentile(Rshoulder, shoulder_percentile))
        adaptive_thr_L = max(shoulder_thresh, np.percentile(Lshoulder, shoulder_percentile))
    else:
        adaptive_thr_R, adaptive_thr_L = None, None

    for i in range(len(events)):
        if i in used_indices: continue
        event1 = events[i]
        best_partner_idx = -1
        for j in range(i + 1, len(events)):
            event2 = events[j]
            if (event2['frame'] - event1['frame']) > max_frame_dist: break
            if event2['leg'] != event1['leg']:
                best_partner_idx = j
                break

        if best_partner_idx != -1:
            event2 = events[best_partner_idx]
            if gender == "female":
                # Użyj tych samych parametrów co detect_bow_events
                bow_min_abs = 60.0  # minimalna głębokość dla obu kolan
                bow_depth_tol_strict = 0.08  # ściślejsza tolerancja głębokości
                is_synced = abs(event1['frame'] - event2['frame']) <= bow_frame_dist
                is_deep_enough = event1['depth'] >= bow_min_abs and event2['depth'] >= bow_min_abs
                avg_depth = 0.5 * (event1['depth'] + event2['depth'])
                are_depths_similar = avg_depth > 0 and abs(event1['depth'] - event2['depth']) < bow_depth_tol_strict * avg_depth
                
                if is_synced and is_deep_enough and are_depths_similar:
                    final_events.append((min(event1['frame'], event2['frame']), "bow (female)"))
                    used_indices.add(i);
                    used_indices.add(best_partner_idx)
                    continue

            lead_leg = event1['leg'] if event1['frame'] < event2['frame'] else event2['leg']
            frame_lead = event1['frame'] if event1['frame'] < event2['frame'] else event2['frame']
            other_leg = event2['leg'] if event1['frame'] < event2['frame'] else event1['leg']
            frame_other = event2['frame'] if event1['frame'] < event2['frame'] else event1['frame']

            final_events.append((frame_lead, f"{lead_leg} step (accented)"))
            final_events.append((frame_other, f"{other_leg} accent"))

            if gender == "male":
                margin = int(0.35 * fs)
                if lead_leg == "R":
                    f_start, f_end = frame_lead, min(len(Rshoulder), frame_lead + margin)
                    if np.max(Rshoulder[f_start:f_end]) > adaptive_thr_R:
                        final_events[-2] = (frame_lead, "bow (male, R lead)")
                elif lead_leg == "L":
                    f_start, f_end = frame_lead, min(len(Lshoulder), frame_lead + margin)
                    if np.max(Lshoulder[f_start:f_end]) > adaptive_thr_L:
                        final_events[-2] = (frame_lead, "bow (male, L lead)")
            used_indices.add(i);
            used_indices.add(best_partner_idx)
        else:
            final_events.append((event1['frame'], f"{event1['leg']} step"))
            used_indices.add(i)

    final_events.sort(key=lambda x: x[0])
    return final_events


def convert_peaks_to_boundaries(
        peak_events: List[Tuple[int, str]],
        Lknee: np.ndarray,
        Rknee: np.ndarray,
        fs: float,
        alpha_start: float = 0.05,
        alpha_end: float = 0.05
) -> List[Tuple[int, str]]:
    """
    Bierze listę gotowych, zaufanych pików i zamienia każdy z nich
    na parę zdarzeń (start, end) używając logiki find_event_bounds.
    """
    boundary_events = []
    signals = {'L': Lknee, 'R': Rknee}

    for peak_frame, peak_label in peak_events:
        # Pomiń zdarzenia, które nie są krokami (np. ukłony wykryte w starej funkcji)
        if "step" not in peak_label and "accent" not in peak_label:
            # Możemy je przenieść bez zmian, jeśli chcemy
            # boundary_events.append((peak_frame, peak_label))
            continue

        # Wykryj, której nogi dotyczy zdarzenie
        leg = None
        if "L " in peak_label or peak_label.startswith("L"):
            leg = 'L'
        elif "R " in peak_label or peak_label.startswith("R"):
            leg = 'R'

        if leg:
            signal = signals[leg]
            # Użyj swojej logiki do znalezienia granic na podstawie piku
            start_frame, end_frame = find_event_bounds(
                signal,
                peak_idx=peak_frame,
                alpha_start=alpha_start,
                alpha_end=alpha_end
            )

            # Dodaj nowe etykiety start/end
            boundary_events.append((start_frame, f"{peak_label} start"))
            boundary_events.append((end_frame, f"{peak_label} end"))

    return sorted(boundary_events, key=lambda x: x[0])

# >>> ZMIANA: kroki/akcenty też liczą granice metodą ukłonu (find_event_bounds)
def find_accented_gait_events(
        Lknee: np.ndarray, Rknee: np.ndarray, fs: float,
        Lshoulder: Optional[np.ndarray], Rshoulder: Optional[np.ndarray],
        shoulder_thresh: float = 10.0,
        shoulder_percentile: int = 90,
        min_prominence: float = 18.0,
        pair_window_s: float = 0.50,
        bow_depth_tol: float = 0.20,
        gender: str = "female",
        start_alpha: float = 0.05,
        end_alpha: float = 0.05,
        start_offset_frames: int = 0,
        end_offset_frames: int = 0,
        suppress_windows: Optional[List[Tuple[int, int]]] = None,
        min_step_distance_s: float = 0.30,
        male_shoulder_prominence: float = 6.0,
        male_shoulder_win_low_s: float = 0.10,
        male_shoulder_win_high_s: float = 0.35,
        male_lead_knee_min_deg: float = 28.0,
        male_other_knee_max_ratio: float = 0.60,
        near_simul_s: float = 0.12,          # NEW: „prawie jednoczesne” piki
) -> List[Tuple[int, str]]:

    def suppressed(f: int) -> bool:
        if not suppress_windows: return False
        for a, b in suppress_windows:
            if a <= f <= b: return True
        return False

    min_dist = max(1, int(min_step_distance_s * fs))
    L_idx, _ = find_peaks(Lknee, prominence=min_prominence, distance=min_dist)
    R_idx, _ = find_peaks(Rknee, prominence=min_prominence, distance=min_dist)
    L_idx = [int(i) for i in L_idx if not suppressed(int(i))]
    R_idx = [int(i) for i in R_idx if not suppressed(int(i))]

    events = [{'frame': int(i), 'leg': 'L', 'depth': float(Lknee[i])} for i in L_idx] + \
             [{'frame': int(i), 'leg': 'R', 'depth': float(Rknee[i])} for i in R_idx]
    events.sort(key=lambda x: x['frame'])

    max_frame_dist = int(pair_window_s * fs)
    near_simul = int(near_simul_s * fs)
    bow_frame_dist = int(0.12 * fs)

    thr_L = thr_R = None
    if gender == "male" and Lshoulder is not None and Rshoulder is not None:
        thr_R = max(shoulder_thresh, float(np.percentile(Rshoulder, shoulder_percentile)))
        thr_L = max(shoulder_thresh, float(np.percentile(Lshoulder, shoulder_percentile)))

    # pomocnicze
    same_leg_between = lambda a, b, leg: any((a < k < b) and (events[k]['leg'] == leg)
                                             for k in range(a+1, b))
    def nearest_opposite(i):
        f0, leg0 = events[i]['frame'], events[i]['leg']
        cand = [j for j in range(i+1, len(events))
                if (events[j]['leg'] != leg0) and (events[j]['frame'] - f0) <= max_frame_dist]
        if not cand: return -1
        # wybierz najbliższy w czasie
        j = min(cand, key=lambda j: abs(events[j]['frame'] - f0))
        # nie paruj „przez” kolejny pik tej samej nogi
        if same_leg_between(i, j, leg0): return -1
        return j

    out: List[Tuple[int, str]] = []
    used = set()

    for i in range(len(events)):
        if i in used: continue
        e1 = events[i]
        j = nearest_opposite(i)

        if j != -1:
            e2 = events[j]

            # — odfiltruj kobiecy ukłon (prawie jednoczesne i głębokie po obydwu) —
            is_deep_enough_for_bow = (e1['depth'] > 45.0 and e2['depth'] > 45.0)
            if gender == "female" and is_deep_enough_for_bow and abs(e1['frame'] - e2['frame']) <= bow_frame_dist:
                avg_depth = 0.5 * (e1['depth'] + e2['depth'])
                if avg_depth > 0 and abs(e1['depth'] - e2['depth']) / avg_depth < bow_depth_tol:
                    used.update({i, j})
                    continue

            # wybór „lead”: normalnie wcześniejszy, ale przy prawie jednoczesnych → głębszy
            if abs(e1['frame'] - e2['frame']) <= near_simul:
                lead, other = (e1, e2) if e1['depth'] >= e2['depth'] else (e2, e1)
            else:
                lead, other = (e1, e2) if e1['frame'] <= e2['frame'] else (e2, e1)

            lead_sig  = Lknee if lead ['leg']=='L' else Rknee
            other_sig = Lknee if other['leg']=='L' else Rknee

            s1, e1b = find_event_bounds(lead_sig,  lead['frame'],
                                        alpha_start=start_alpha, alpha_end=end_alpha,
                                        start_offset_frames=start_offset_frames, end_offset_frames=end_offset_frames)
            s2, e2b = find_event_bounds(other_sig, other['frame'],
                                        alpha_start=start_alpha, alpha_end=end_alpha,
                                        start_offset_frames=start_offset_frames, end_offset_frames=end_offset_frames)

            # męski ukłon (ramię po stronie lead wyraźnie w górę)
            bow_male = False
            if gender == "male" and thr_L is not None and thr_R is not None:
                low_margin = int(male_shoulder_win_low_s * fs)
                margin     = int(male_shoulder_win_high_s * fs)
                if lead['leg']=='R' and Rshoulder is not None:
                    f0,f1 = max(0, lead['frame']+low_margin), min(len(Rshoulder), lead['frame']+margin)
                    if f0 < f1 and (np.max(Rshoulder[f0:f1]) - Rshoulder[lead['frame']] > male_shoulder_prominence) \
                       and lead['depth'] > male_lead_knee_min_deg and other['depth'] < lead['depth']*male_other_knee_max_ratio:
                        bow_male = True
                if lead['leg']=='L' and Lshoulder is not None:
                    f0,f1 = max(0, lead['frame']+low_margin), min(len(Lshoulder), lead['frame']+margin)
                    if f0 < f1 and (np.max(Lshoulder[f0:f1]) - Lshoulder[lead['frame']] > male_shoulder_prominence) \
                       and lead['depth'] > male_lead_knee_min_deg and other['depth'] < lead['depth']*male_other_knee_max_ratio:
                        bow_male = True

            if bow_male:
                out.extend([(s2, f"{other['leg']} accent start"),
                            (e2b, f"{other['leg']} accent end")])
            else:
                out.extend([(s1, f"{lead['leg']} step (accented) start"),
                            (e1b, f"{lead['leg']} step (accented) end")])
                out.extend([(s2, f"{other['leg']} accent start"),
                            (e2b, f"{other['leg']} accent end")])

            used.update({i, j})

        else:
            if suppressed(e1['frame']):
                used.add(i); continue
            sig = Lknee if e1['leg']=='L' else Rknee
            s,e = find_event_bounds(sig, e1['frame'],
                                    alpha_start=start_alpha, alpha_end=end_alpha,
                                    start_offset_frames=start_offset_frames, end_offset_frames=end_offset_frames)
            out.extend([(s, f"{e1['leg']} step start"), (e, f"{e1['leg']} step end")])
            used.add(i)

    return sorted(out, key=lambda x: x[0])


def detect_arms_up_peaks(LshoulderY, RshoulderY, fs,
                         prominence=14.0,
                         min_distance_s=1.5,
                         min_height_thresh=45.0,
                         alpha_start: float = 0.32,
                         alpha_end: float = 0.2) -> List[Tuple[int, str]]:

    if LshoulderY is None or RshoulderY is None or len(LshoulderY) < fs:
        return []

    LshoulderY = np.asarray(LshoulderY)
    RshoulderY = np.asarray(RshoulderY)
    avg_shoulder = (LshoulderY + RshoulderY) / 2.0

    min_dist_frames = int(min_distance_s * fs)
    peak_indices, _ = find_peaks(avg_shoulder, prominence=prominence, distance=min_dist_frames)
    minima, _ = find_peaks(-avg_shoulder)

    out: List[Tuple[int, str]] = []
    for peak_idx in peak_indices:
        if LshoulderY[peak_idx] > min_height_thresh and RshoulderY[peak_idx] > min_height_thresh:
            prev_mins = [m for m in minima if m < peak_idx]
            next_mins = [m for m in minima if m > peak_idx]
            left_min = max(prev_mins) if prev_mins else 0
            right_min = min(next_mins) if next_mins else len(avg_shoulder) - 1

            start = left_min
            end = right_min
            peak_val = avg_shoulder[peak_idx]

            if 0.0 < alpha_start <= 1.0:
                lvl_s = avg_shoulder[left_min] + alpha_start * (peak_val - avg_shoulder[left_min])
                s_candidates = np.where(avg_shoulder[left_min:peak_idx + 1] >= lvl_s)[0]
                if len(s_candidates) > 0:
                    start = left_min + s_candidates[0]

            if 0.0 < alpha_end <= 1.0:
                lvl_e = avg_shoulder[right_min] + alpha_end * (peak_val - avg_shoulder[right_min])
                e_candidates = np.where(avg_shoulder[peak_idx:right_min + 1] <= lvl_e)[0]
                if len(e_candidates) > 0:
                    end = peak_idx + e_candidates[0]

            out.extend([(start, "arms up start"), (end, "arms up end")])

    return sorted(out, key=lambda x: x[0])

def detect_full_turns(pelvis_z, fs, angle_thresh=300.0, label="turn",
                      min_turn_duration_s=0.5, max_turn_duration_s=4.0,
                      min_raw_range=180.0) -> List[Tuple[int, str]]:
    """
    Wykrywa pełne obroty na podstawie kąta yaw miednicy.
    
    Args:
        pelvis_z: sygnał kąta yaw miednicy
        fs: częstotliwość próbkowania
        angle_thresh: minimalny kąt obrotu po unwrap (stopnie)
        min_turn_duration_s: minimalny czas trwania obrotu
        max_turn_duration_s: maksymalny czas trwania obrotu
        min_raw_range: minimalna amplituda w surowym sygnale (przed unwrap)
                       - filtruje fałszywe obroty z oscylującego sygnału
    """
    if pelvis_z is None or np.isnan(pelvis_z).all(): return []
    
    pelvis_z = np.asarray(pelvis_z, dtype=float)
    yaw_unwrapped = np.unwrap(np.radians(pelvis_z))
    yaw_deg = np.degrees(yaw_unwrapped)

    events: List[Tuple[int, str]] = []
    n, i = len(yaw_deg), 0
    
    min_frames = int(min_turn_duration_s * fs)
    max_frames = int(max_turn_duration_s * fs)
    
    while i < n - 1:
        if i + 1 >= n: break
        start_val = yaw_deg[i]
        initial_delta = yaw_deg[i + 1] - yaw_deg[i]
        if abs(initial_delta) < 1e-9:
            i += 1
            continue
        j = i + 1
        while j < n and (yaw_deg[j] - yaw_deg[j - 1]) * initial_delta > 0:
            if abs(yaw_deg[j] - start_val) >= angle_thresh:
                duration_frames = j - i
                
                # Sprawdź czy czas trwania jest rozsądny
                if duration_frames < min_frames or duration_frames > max_frames:
                    j += 1
                    continue
                
                # Sprawdź amplitudę w surowym sygnale (przed unwrap)
                # To filtruje fałszywe obroty z oscylującego sygnału
                raw_range = np.max(pelvis_z[i:j+1]) - np.min(pelvis_z[i:j+1])
                if raw_range < min_raw_range:
                    j += 1
                    continue
                
                direction = "right" if (yaw_deg[j] - start_val) > 0 else "left"
                events.extend([(i, f"{label} start ({direction})"), (j, f"{label} end ({direction})")])
                i = j
                break
            j += 1
        i = j if j > i + 1 else i + 1
    return events

def detect_head_nod(Lhead: np.ndarray, fs: float,
                    rise_thresh_ratio: float = 0.4,
                    smooth_win_s: float = 0.20,
                    min_bow_duration_s: float = 0.3,
                    max_bow_duration_s: float = 3.0,
                    return_ratio: float = 0.75,
                    min_amplitude: float = 20.0) -> List[Tuple[int, str]]:
    """
    Wykrywa ukłony głowy (pochylenie i powrót) na podstawie WZROSTU kąta LHead.
    Po zmianie definicji kąta: ukłon = wzrost kąta (górka), nie spadek.
    Koniec pochylenia uznaje dopiero, gdy głowa wróci blisko poziomu wyjściowego.
    
    min_amplitude: minimalna różnica między maksymalnym kątem a baseline [stopnie]
    """
    if Lhead is None or len(Lhead) < 10:
        return []

    signal = np.asarray(Lhead, dtype=float)

    # --- Wygładzanie sygnału, żeby nie reagował na szum ---
    win = int(max(3, smooth_win_s * fs))
    if win % 2 == 0:
        win += 1
    smooth = np.convolve(signal, np.ones(win)/win, mode="same")

    # --- Pochodna sygnału (ruch głowy) ---
    d = np.gradient(smooth)

    pos_thr = np.percentile(np.abs(d), 90) * rise_thresh_ratio

    events = []
    in_bow = False
    start_idx = None
    baseline_val = None
    max_val = None

    for i in range(1, len(d)):
        if not in_bow:
            # Start pochylenia – wyraźny WZROST kąta (teraz górka)
            if d[i] > pos_thr:
                in_bow = True
                start_idx = i
                baseline_val = smooth[max(0, i - int(0.2 * fs))]  # poziom sprzed pochylenia
                max_val = smooth[i]
        else:
            # Aktualizuj maksymalny kąt (największe pochylenie = najwyższa wartość)
            if smooth[i] > max_val:
                max_val = smooth[i]

            # Głowa wróciła do poziomu bazowego (spadła z powrotem o return_ratio)
            if smooth[i] <= baseline_val + (max_val - baseline_val) * (1 - return_ratio):
                end_idx = i
                duration = (end_idx - start_idx) / fs
                amplitude = max_val - baseline_val
                # Sprawdź czy ukłon trwa odpowiednio długo I ma wystarczającą amplitudę
                if min_bow_duration_s <= duration <= max_bow_duration_s and amplitude >= min_amplitude:
                    events.append((start_idx, "head nod start"))
                    events.append((end_idx, "head nod end"))
                in_bow = False
                start_idx = None
                baseline_val = None
                max_val = None

    return events

def calculate_head_nod_angles(events, Lhead, fs=50):
    """
    Dodaje do eventów 'head nod end' pole 'max_head_angle'
    (czyli największe pochylenie głowy w trakcie ukłonu = teraz maksimum kąta).
    """
    enriched = []
    for i, ev in enumerate(events):
        label = ev["label"].lower()
        if "head nod end" in label:
            # znajdź odpowiadający 'head nod start'
            start_event = None
            for j in range(i - 1, -1, -1):
                if "head nod start" in events[j]["label"].lower():
                    start_event = events[j]
                    break
            if start_event:
                start_idx = int(start_event["time"] * fs)
                end_idx = int(ev["time"] * fs)
                if 0 <= start_idx < end_idx <= len(Lhead):
                    max_angle = float(np.max(Lhead[start_idx:end_idx + 1]))
                    ev = {**ev, "max_head_angle": max_angle}
        enriched.append(ev)
    return enriched


# --------------------------------------------------------------------------
# SEKCJA 3: GŁÓWNA LOGIKA PRZETWARZANIA I WIZUALIZACJI
# --------------------------------------------------------------------------

def process_file(
    csv_path: Path,
    output_path: Optional[Path],
    fs: float,
    *,
    write_plot: bool = True,
    in_root: Optional[Path] = None,
    json_root: Optional[Path] = None,
    gender: str = "auto",
    step_type: str = "auto",
):
    """
    Wczytuje, analizuje i generuje wykres dla pojedynczego pliku CSV,
    używając dwuetapowej logiki detekcji kroków.

    Args:
        gender: "auto" = wykryj z nazwy pliku (m_ prefix), "female"/"male" = użyj wprost.
        step_type: "auto" = wykryj z nazwy pliku (krok keyword), "krok_podstawowy"/"static" = użyj wprost.
    """
    print(f"Przetwarzanie pliku: {csv_path.name}...")
    try:
        # --------------------------------------------------------------------
        # KROK 1: WCZYTYWANIE DANYCH (bez zmian)
        # --------------------------------------------------------------------
        lines = csv_path.read_text(encoding="utf-8").splitlines(True)
        step_type = detect_step_from_filename(csv_path) if step_type == "auto" else step_type
        gender = detect_gender_from_filename(csv_path) if gender == "auto" else gender

        delim = detect_delimiter(lines)
        angles, traj = find_section_indices(lines)
        angles_data = load_angles_fast(csv_path, lines, angles, delim)
        t = angles_data.frames / fs

        idxL = angles_data.markers_clean.index("LKneeAngles")
        idxR = angles_data.markers_clean.index("RKneeAngles")
        Lknee_flexion = angles_data.X[:, idxL, 0]
        Rknee_flexion = angles_data.X[:, idxR, 0]

        idxLS = angles_data.markers_clean.index("LShoulderAngles")
        idxRS = angles_data.markers_clean.index("RShoulderAngles")
        Lshoulder = angles_data.X[:, idxLS, 0]
        Rshoulder = angles_data.X[:, idxRS, 0]

        LshoulderY = angles_data.X[:, idxLS, 1]
        RshoulderY = angles_data.X[:, idxRS, 1]

        idxLP = angles_data.markers_clean.index("LPelvisAngles")
        LPelvisZ = angles_data.X[:, idxLP, 2]

        LHip_idx = angles_data.markers_clean.index("LHipAngles")
        RHip_idx = angles_data.markers_clean.index("RHipAngles")
        LHipY = angles_data.X[:, LHip_idx, 1]
        RHipY = angles_data.X[:, RHip_idx, 1]

        idxHeadL = angles_data.markers_clean.index("LHeadAngles")
        Lhead = angles_data.X[:, idxHeadL, 0]

        # --------------------------------------------------------------------
        # KROK 2: ZMODYFIKOWANA LOGIKA DETEKCJI ZDARZEŃ
        # --------------------------------------------------------------------

        # 2A) UKŁONY - Wykrywamy jako pierwsze, aby stworzyć "okna wyciszenia"
        bow_events = detect_bow_events(
            Lknee_flexion, Rknee_flexion, fs, Lshoulder, Rshoulder,
            gender=gender,
            bow_prominence=18.0,
            bow_min_abs=60.0,
            bow_sync_s=0.10,
            bow_depth_tol=0.08,
        )
        bow_windows = bow_events_to_windows(bow_events, fs, pad_s=0.12)

        # 2B) KROKI - NOWA, BEZPIECZNA METODA DWUETAPOWA
        # Najpierw wykrywamy TYLKO piki Twoją sprawdzoną metodą z pierwszego skryptu.
        gait_peaks = detect_gait_peaks_only(
            Lknee_flexion, Rknee_flexion, fs, Lshoulder, Rshoulder,
            gender=gender
            # Ważne: Twoja oryginalna funkcja musi być w stanie ignorować piki w "bow_windows".
            # Jeśli nie potrafi, trzeba dodać prosty filtr po jej wykonaniu.
        )
        # Filtrujemy piki, które wpadły w okna ukłonów, jeśli funkcja sama tego nie robi
        gait_peaks = [(frame, label) for frame, label in gait_peaks
                      if not any(start <= frame <= end for start, end in bow_windows)]

        # Następnie konwertujemy KAŻDY zaufany pik na granice start/end.
        gait_events = convert_peaks_to_boundaries(
            gait_peaks,
            Lknee_flexion,
            Rknee_flexion,
            fs
        )

        arm_events: List[Tuple[int, str]] = []
        turn_events: List[Tuple[int, str]] = []

        # 2C) KROKI W BOK, RAMIONA I OBROTY
        if gender == "female":
            side_step_events = detect_side_steps(LHipY, RHipY, fs)
            # Uwaga: `merge_steps_with_side_labels` wymagałby modyfikacji do pracy z etykietami start/end.
            # Na razie pomijamy łączenie, aby uniknąć błędów.
            gait_events = merge_steps_with_side_labels(gait_events, side_step_events, fs)
            arm_events = detect_arms_up_peaks(LshoulderY, RshoulderY, fs)
            if step_type == "static":
                turn_events = detect_full_turns(LPelvisZ, fs)

        head_nod_events: List[Tuple[int, str]] = []
        # Wykrywanie ukłonów głowy - dla obu płci
        head_nod_events = detect_head_nod(Lhead, fs)

        # 2D) POŁĄCZENIE WSZYSTKICH ZDARZEŃ
        all_events = sorted(gait_events + bow_events + arm_events + turn_events + head_nod_events, key=lambda x: x[0])

        # --------------------------------------------------------------------
        # KROK 3: WIZUALIZACJA I ZAPIS
        # --------------------------------------------------------------------
        if write_plot:
            import matplotlib.pyplot as plt

            plt.figure(figsize=(28, 9))
            plt.plot(t, Lknee_flexion, label="L knee flexion/extension", color="blue")
            plt.plot(t, Rknee_flexion, label="R knee flexion/extension", color="red")

            if gender == "male":
                plt.plot(t, Lshoulder, label="L shoulder lift", color="cyan", linestyle="--")
                plt.plot(t, Rshoulder, label="R shoulder lift", color="orange", linestyle="--")
                adaptive_thr_R = max(10.0, np.percentile(Rshoulder, 90))
                adaptive_thr_L = max(10.0, np.percentile(Lshoulder, 90))
                plt.axhline(adaptive_thr_R, color="orange", linestyle=":", alpha=0.7, label="R shoulder thr")
                plt.axhline(adaptive_thr_L, color="cyan", linestyle=":", alpha=0.7, label="L shoulder thr")
            if gender == "female":
                plt.plot(t, LshoulderY, label="L shoulder lift Y", color="cyan", linestyle="--")
                plt.plot(t, RshoulderY, label="R shoulder lift Y", color="orange", linestyle="--")
                if step_type == "static":
                    plt.plot(t, LPelvisZ, label="Pelvis Z", color="green", linestyle="--")

            def leg_from_label(lbl: str) -> Optional[str]:
                low = lbl.lower()
                if " step" in low or " accent" in low or "lead" in low or "side step" in low:
                    if " r " in f" {lbl} " or lbl.startswith("R"):
                        return "R"
                    if " l " in f" {lbl} " or lbl.startswith("L"):
                        return "L"
                return None

            ax = plt.gca()
            for frame, label in all_events:
                time_stamp = frame / fs
                leg = leg_from_label(label)
                color = (
                    "red" if leg == "R" else
                    "blue" if leg == "L" else
                    "orange" if "bow" in label else
                    "green" if "arms" in label else
                    "purple" if "turn" in label else
                    "blue"
                )

                ax.axvline(time_stamp, color=color, linestyle="--", alpha=0.9, linewidth=1.2)
                place_bottom = (leg == "R") or ("arms" in label.lower()) or ("turn" in label.lower())
                if place_bottom:
                    ax.text(
                        time_stamp,
                        -0.10,
                        label,
                        rotation=90,
                        va="top",
                        ha="center",
                        color=color,
                        fontsize=11,
                        weight='bold' if "bow" in label else 'normal',
                        transform=ax.get_xaxis_transform(),
                    )
                else:
                    ax.text(
                        time_stamp,
                        1.05,
                        label,
                        rotation=90,
                        va="bottom",
                        ha="center",
                        color=color,
                        fontsize=11,
                        weight='normal',
                        transform=ax.get_xaxis_transform(),
                    )

            plt.plot(t, Lhead, label="L head", color="green")

            plt.xticks(np.arange(0, t.max() + 0.5, 0.5))
            plt.grid(axis='x', linestyle=':', alpha=0.7)
            plt.xlabel("Time [s]", fontsize=12)
            plt.ylabel("Angle [deg]", fontsize=12)
            plt.legend(fontsize=11)
            plt.title(f"Analiza zdarzeń: {csv_path.stem}", fontsize=14)
            plt.tight_layout()

            if output_path is None:
                raise ValueError("output_path is required when write_plot=True")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path)
            plt.close()
            print(f"Wykres zapisano w: {output_path}")

        # --- ZAPIS JSONA (bez zmian) ---
        base_in_root = in_root if in_root is not None else getattr(args, "in_root", None)
        base_json_root = json_root if json_root is not None else getattr(args, "json_root", None)
        if base_in_root is None or base_json_root is None:
            raise ValueError("in_root and json_root must be provided (or available via CLI args).")

        relative_path = csv_path.relative_to(base_in_root)
        out_json = base_json_root / relative_path.with_suffix(".json")
        out_json.parent.mkdir(parents=True, exist_ok=True)

        step_lengths_norm: List[dict] = []
        try:
            traj_data = load_trajectories_fast(csv_path, lines, traj, delim)
            step_end_events = [(fr, lab) for fr, lab in gait_events if "step" in lab.lower() and "end" in lab.lower()]
            bow_end_events_male = [(fr, lab) for fr, lab in bow_events if
                                   "bow end" in lab.lower() and "lead" in lab.lower()]
            events_with_length = step_end_events + bow_end_events_male

            for fr, lab in events_with_length:
                axis = 0 if "side" in lab.lower() or "bow end" in lab.lower() else 1
                direction = "side" if axis == 0 else "forward"
                val = calculate_step_length_normalized(traj_data, fr, axis=axis)
                if val is not None:
                    step_lengths_norm.append(
                        {"time": float(fr) / fs, "label": lab, "value": float(val), "units": traj_data.units,
                         "direction": direction})
        except Exception as e:
            print(f"[UWAGA] Nie udało się policzyć długości kroku: {e}")

        step_dict = {(e["time"], e["label"]): e for e in step_lengths_norm}
        events = [{"time": float(frame) / fs, "label": label} for frame, label in all_events]
        merged_events = [{**ev, **step_dict.get((ev["time"], ev["label"]), {})} for ev in events]

        merged_events = calculate_knee_angles(merged_events, Lknee_flexion, Rknee_flexion)
        merged_events = calculate_shoulder_angles(merged_events, LshoulderY, RshoulderY)
        if gender == "male":
            merged_events = calculate_shoulder_bow_angles(merged_events, Lshoulder, Rshoulder)
            merged_events = calculate_head_nod_angles(merged_events, Lhead)

        json_data = {"file": str(csv_path), "gender": gender, "step_type": step_type, "fs": fs, "events": merged_events}
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"JSON zapisano w: {out_json}")

    except Exception as e:
        print(f"Nie udało się przetworzyć pliku {csv_path.name}. Błąd: {e}")

# ---------------- DODATKOWE FUNKCJE POMIAROWE (bez zmian merytorycznych) ----------------

def calculate_step_length_normalized(traj_data: MotionData, end_frame: int, axis: int) -> Optional[float]:
    try:
        idx_L = traj_data.markers_clean.index("LANK")
        idx_R = traj_data.markers_clean.index("RANK")
    except (ValueError, AttributeError):
        return None
    i = int(np.argmin(np.abs(traj_data.frames - end_frame)))
    if i < 0 or i >= traj_data.X.shape[0]:
        return None
    L = traj_data.X[i, idx_L, :]
    R = traj_data.X[i, idx_R, :]
    if (traj_data.units or "").lower() == "norm":
        return float(abs(L[axis] - R[axis]))
    else:
        dx = float(R[0] - L[0]); dz = float(R[2] - L[2])
        return float(np.hypot(dx, dz))

def calculate_knee_angles(events, Lknee, Rknee, fs=50):
    enriched = []
    for i, ev in enumerate(events):
        label = ev["label"].lower()
        if "end" in label and ("step" in label or "accent" in label or "bow" in label):
            start_label = label.replace("end", "start").strip()
            start_event = None
            for j in range(i-1, -1, -1):
                if events[j]["label"].lower().startswith(start_label.split()[0]) and "start" in events[j]["label"].lower():
                    start_event = events[j]; break
            if start_event:
                start_idx = int(start_event["time"] * fs)
                end_idx = int(ev["time"] * fs)
                if "l " in label:
                    max_angle = float(np.max(Lknee[start_idx:end_idx+1]))
                elif "r " in label:
                    max_angle = float(np.max(Rknee[start_idx:end_idx+1]))
                else:
                    max_angle = float(max(np.max(Lknee[start_idx:end_idx+1]), np.max(Rknee[start_idx:end_idx+1])))
                ev = {**ev, "max_knee_angle": max_angle}
        enriched.append(ev)
    return enriched

def calculate_shoulder_angles(events, Lshoulder, Rshoulder, fs=50):
    enriched = []
    for i, ev in enumerate(events):
        label = ev["label"].lower()
        if "end" in label and "arms" in label:
            start_label = label.replace("end", "start").strip()
            start_event = None
            for j in range(i - 1, -1, -1):
                if events[j]["label"].lower().startswith(start_label.split()[0]) and "start" in events[j]["label"].lower():
                    start_event = events[j]; break
            if start_event:
                start_idx = int(start_event["time"] * fs)
                end_idx = int(ev["time"] * fs)
                max_angle = float(max(np.max(Lshoulder[start_idx:end_idx + 1]), np.max(Rshoulder[start_idx:end_idx + 1])))
                ev = {**ev, "max_arms_angle": max_angle}
        enriched.append(ev)
    return enriched

def calculate_shoulder_bow_angles(events, Lshoulder, Rshoulder, fs=50):
    enriched = []
    for i, ev in enumerate(events):
        label = ev["label"].lower()
        if "end" in label and "bow" in label and "lead" in label:
            start_label = label.replace("end", "start").strip()
            start_event = None
            for j in range(i - 1, -1, -1):
                if events[j]["label"].lower().startswith(start_label.split()[0]) and "start" in events[j]["label"].lower():
                    start_event = events[j]; break
            if start_event:
                start_idx = int(start_event["time"] * fs)
                end_idx = int(ev["time"] * fs)
                if "l lead" in label:
                    max_angle = float(np.max(Lshoulder[start_idx:end_idx + 1]))
                else:
                    max_angle = float(np.max(Rshoulder[start_idx:end_idx + 1]))
                ev = {**ev, "max_arm_angle": max_angle}
        enriched.append(ev)
    return enriched

# --------------------------------------------------------------------------
# SEKCJA 4: URUCHOMIENIE
# --------------------------------------------------------------------------

# Katalog główny projektu (parent of Scripts/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(
        description="Analizuje pliki CSV, wykrywa START/END zdarzeń (kroki, ukłony, ręce, obroty) i generuje wykresy."
    )
    parser.add_argument("--in-root", type=Path, default=PROJECT_ROOT / "data/csv/manual/downsampled",
                        help="Katalog wejściowy zawierający podkatalogi z plikami CSV.")
    parser.add_argument("--out-root", type=Path, default=PROJECT_ROOT / "Plots/manual/4segmentation_step_bounds",
                        help="Katalog wyjściowy, do którego zostaną zapisane wykresy.")
    parser.add_argument("--fs", type=float, default=50.0,
                        help="Częstotliwość próbkowania w Hz.")
    parser.add_argument("--json-root", type=Path, default=PROJECT_ROOT / "data/json/manual/pipeline/4_segmentation_bounds",
                        help="Katalog na zapis JSONów.")
    parser.add_argument("--skip-plots", action="store_true",
                        help="Pomiń generowanie PNG (szybszy tryb pod realtime).")
    global args
    args = parser.parse_args()

    if not args.in_root.is_dir():
        print(f"Błąd: Katalog wejściowy '{args.in_root}' nie istnieje.")
        return

    csv_files = list(args.in_root.glob("*/*.csv"))
    if not csv_files:
        print(f"Nie znaleziono żadnych plików CSV w katalogu '{args.in_root}' o oczekiwanej strukturze.")
        return

    for in_csv in sorted(csv_files):
        if args.skip_plots:
            process_file(in_csv, None, args.fs, write_plot=False)
            continue

        relative_path = in_csv.relative_to(args.in_root)
        out_png = args.out_root / relative_path.with_suffix(".png")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        process_file(in_csv, out_png, args.fs, write_plot=True)

if __name__ == "__main__":
    main()
