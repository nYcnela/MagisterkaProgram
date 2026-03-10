from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from .contracts import FrameWindow

MODEL_INSTRUCTION = (
    "You are the teacher of the Polish Polonaise dance. "
    "Based on the student's movement description, give one short sentence of supportive corrective feedback, "
    "then give a score from 1 to 5, where 5 is best."
)


@dataclass(frozen=True)
class MetricRef:
    duration_mean: float
    duration_std: float
    knee_mean: float
    knee_std: float
    length_mean: Optional[float] = None
    length_std: Optional[float] = None


@dataclass(frozen=True)
class PatternStepRefs:
    step_left: Optional[MetricRef]
    step_right: Optional[MetricRef]
    step_accent_left: Optional[MetricRef]
    step_accent_right: Optional[MetricRef]
    accent_left: Optional[MetricRef]
    accent_right: Optional[MetricRef]


def _safe_stats(block: Dict[str, Any], key: str) -> tuple[Optional[float], Optional[float]]:
    sub = block.get(key, {}) if isinstance(block, dict) else {}
    if not isinstance(sub, dict):
        return None, None
    if "average" not in sub:
        return None, None
    avg = float(sub.get("average", 0.0))
    std = float(sub.get("stdev", 1.0))
    if std <= 1e-9:
        std = 1.0
    return avg, std


def _build_ref(perf: Dict[str, Any], key: str) -> Optional[MetricRef]:
    if key not in perf or not isinstance(perf[key], dict):
        return None
    block = perf[key]

    d_m, d_s = _safe_stats(block, "duration_seconds")
    k_m, k_s = _safe_stats(block, "max_knee_angle")
    l_m, l_s = _safe_stats(block, "step_length_normalized")

    if d_m is None or d_s is None or k_m is None or k_s is None:
        return None

    return MetricRef(
        duration_mean=d_m,
        duration_std=d_s,
        knee_mean=k_m,
        knee_std=k_s,
        length_mean=l_m,
        length_std=l_s,
    )


def load_pattern_step_refs(pattern_file: Path) -> PatternStepRefs:
    obj = json.loads(pattern_file.read_text(encoding="utf-8"))
    perf = dict(obj.get("performance_metrics") or {})

    step_left = _build_ref(perf, "L step")
    step_right = _build_ref(perf, "R step")
    step_acc_left = _build_ref(perf, "L step (accented)")
    step_acc_right = _build_ref(perf, "R step (accented)")
    accent_left = _build_ref(perf, "L accent")
    accent_right = _build_ref(perf, "R accent")

    if step_left is None:
        step_left = step_acc_left
    if step_right is None:
        step_right = step_acc_right
    if accent_left is None:
        accent_left = step_acc_left
    if accent_right is None:
        accent_right = step_acc_right

    return PatternStepRefs(
        step_left=step_left,
        step_right=step_right,
        step_accent_left=step_acc_left,
        step_accent_right=step_acc_right,
        accent_left=accent_left,
        accent_right=accent_right,
    )


def _extract_marker(frames, marker_name: str) -> np.ndarray:
    out = np.full((len(frames), 3), np.nan, dtype=np.float64)
    for i, fr in enumerate(frames):
        m = fr.markers.get(marker_name)
        if m is None:
            continue
        out[i, 0] = float(m.x)
        out[i, 1] = float(m.y)
        out[i, 2] = float(m.z)
    return out


def _interp_nan_1d(x: np.ndarray) -> np.ndarray:
    y = np.asarray(x, dtype=np.float64).copy()
    n = y.shape[0]
    idx = np.arange(n)
    mask = np.isfinite(y)
    if not mask.any():
        return np.zeros_like(y)
    if mask.sum() == 1:
        y[:] = y[mask][0]
        return y
    y[~mask] = np.interp(idx[~mask], idx[mask], y[mask])
    return y


def _interp_nan_xyz(mat: np.ndarray) -> np.ndarray:
    out = np.asarray(mat, dtype=np.float64).copy()
    for c in range(3):
        out[:, c] = _interp_nan_1d(out[:, c])
    return out


def _moving_average(x: np.ndarray, win: int) -> np.ndarray:
    if win <= 1:
        return x
    kernel = np.ones(win, dtype=np.float64) / float(win)
    return np.convolve(x, kernel, mode="same")


def _knee_flexion_deg(hip: np.ndarray, knee: np.ndarray, ankle: np.ndarray) -> np.ndarray:
    v1 = hip - knee
    v2 = ankle - knee
    n1 = np.linalg.norm(v1, axis=1)
    n2 = np.linalg.norm(v2, axis=1)
    denom = np.maximum(n1 * n2, 1e-9)
    cosang = np.sum(v1 * v2, axis=1) / denom
    cosang = np.clip(cosang, -1.0, 1.0)
    angle = np.degrees(np.arccos(cosang))
    return 180.0 - angle


def _detect_peaks(signal: np.ndarray, fs: float, *, min_distance_s: float = 0.22) -> np.ndarray:
    if signal.size < 3:
        return np.array([], dtype=np.int64)

    x = _moving_average(signal, win=max(3, int(round(0.04 * fs)) | 1))
    thr = max(float(np.median(x) + 0.35 * np.std(x)), float(np.percentile(x, 60)))
    min_dist = max(1, int(round(min_distance_s * fs)))

    cand = np.where((x[1:-1] > x[:-2]) & (x[1:-1] >= x[2:]) & (x[1:-1] >= thr))[0] + 1
    if cand.size == 0:
        return np.array([], dtype=np.int64)

    order = cand[np.argsort(x[cand])[::-1]]
    chosen: list[int] = []
    for idx in order:
        if all(abs(idx - j) >= min_dist for j in chosen):
            chosen.append(int(idx))
    chosen.sort()
    return np.asarray(chosen, dtype=np.int64)


def _accent_subset(peaks: np.ndarray, knee_signal: np.ndarray) -> np.ndarray:
    if peaks.size <= 1:
        return peaks

    a = peaks[::2]
    b = peaks[1::2]
    if b.size == 0:
        return a

    mean_a = float(np.mean(knee_signal[a]))
    mean_b = float(np.mean(knee_signal[b]))
    sel = a if mean_a >= mean_b else b

    if sel.size == 0:
        vals = knee_signal[peaks]
        thr = float(np.percentile(vals, 55))
        sel = peaks[vals >= thr]

    if sel.size == 0:
        sel = peaks[:1]
    return np.asarray(sel, dtype=np.int64)


def _mean_or_none(arr: np.ndarray) -> Optional[float]:
    if arr.size == 0:
        return None
    return float(np.mean(arr))


def _side_metrics(
    peaks: np.ndarray,
    ipsi_ank: np.ndarray,
    contra_ank: np.ndarray,
    knee_flex: np.ndarray,
    fs: float,
    *,
    with_length: bool,
) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {
        "duration_seconds": None,
        "step_length_normalized": None,
        "max_knee_angle": None,
        "peak_count": float(peaks.size),
    }

    if peaks.size >= 2:
        out["duration_seconds"] = float(np.median(np.diff(peaks)) / fs)

    if peaks.size >= 1:
        half = max(1, int(round(0.18 * fs)))

        knee_vals: list[float] = []
        len_vals: list[float] = []
        n = ipsi_ank.shape[0]

        for p in peaks:
            i = int(p)
            lo = max(0, i - half)
            hi = min(n, i + half + 1)

            knee_vals.append(float(np.nanmax(knee_flex[lo:hi])))

            if with_length:
                # W pobliżu końca kroku, nie dokładnie w samym piku kolana.
                ydiff = np.abs(ipsi_ank[lo:hi, 1] - contra_ank[lo:hi, 1])
                len_vals.append(float(np.nanmax(ydiff)))

        out["max_knee_angle"] = _mean_or_none(np.asarray(knee_vals, dtype=np.float64))
        if with_length:
            out["step_length_normalized"] = _mean_or_none(np.asarray(len_vals, dtype=np.float64))

    return out


def _z(value: Optional[float], mean: Optional[float], std: Optional[float]) -> Optional[float]:
    if value is None or mean is None or std is None:
        return None
    if std <= 1e-9:
        return 0.0
    return (float(value) - float(mean)) / float(std)


def _dur_phrase(side: str, z: Optional[float], threshold: float, *, prefix: str) -> Optional[str]:
    if z is None or abs(z) < threshold:
        return None
    if z < 0:
        return f"{prefix} with the {side} leg were performed slightly too fast"
    return f"{prefix} with the {side} leg were performed slightly too slow"


def _len_phrase(side: str, z: Optional[float], threshold: float, *, prefix: str) -> Optional[str]:
    if z is None or abs(z) < threshold:
        return None
    if z < 0:
        return f"{prefix} with the {side} leg were slightly too short"
    return f"{prefix} with the {side} leg were a bit too long"


def _knee_phrase(z: Optional[float], threshold: float) -> Optional[str]:
    if z is None or abs(z) < threshold:
        return None
    if z < 0:
        return "the knee was too stiff"
    return "the knee was bent too much"


def _compose_text(
    prefix: str,
    side: str,
    z_dur: Optional[float],
    z_len: Optional[float],
    z_knee: Optional[float],
    threshold: float,
) -> tuple[Optional[str], bool, bool, bool]:
    d = _dur_phrase(side, z_dur, threshold, prefix=prefix)
    l = _len_phrase(side, z_len, threshold, prefix=prefix)
    k = _knee_phrase(z_knee, threshold)

    has_d = d is not None
    has_l = l is not None
    has_k = k is not None

    if d and l and k:
        return f"{d} and {l.split(' were ', 1)[1]}, while {k}.", has_d, has_l, has_k
    if d and l:
        return f"{d} and {l.split(' were ', 1)[1]}.", has_d, has_l, has_k
    if d and k:
        return f"{d}, while {k}.", has_d, has_l, has_k
    if l and k:
        return f"{l}, while {k}.", has_d, has_l, has_k
    if d:
        return f"{d}.", has_d, has_l, has_k
    if l:
        return f"{l}.", has_d, has_l, has_k
    if k:
        return f"In {prefix.lower()} with the {side} leg, {k}.", has_d, has_l, has_k
    return None, has_d, has_l, has_k


def _group_weights(group: str) -> tuple[float, float, float]:
    # (duration, length, knee)
    if group == "step":
        return 1.0, 1.1, 0.45
    if group == "accented_step":
        return 1.0, 1.0, 0.40
    # accent: brak długości; unikamy dominacji samego kolana
    return 1.0, 0.0, 0.30


def _candidate(
    *,
    side: str,
    prefix: str,
    group: str,
    metrics: Dict[str, Optional[float]],
    ref: Optional[MetricRef],
    use_length: bool,
    threshold: float,
) -> Optional[Dict[str, Any]]:
    if ref is None:
        return None

    z_dur = _z(metrics.get("duration_seconds"), ref.duration_mean, ref.duration_std)
    z_len = _z(metrics.get("step_length_normalized"), ref.length_mean, ref.length_std) if use_length else None
    z_knee = _z(metrics.get("max_knee_angle"), ref.knee_mean, ref.knee_std)

    txt, has_d, has_l, has_k = _compose_text(prefix, side, z_dur, z_len, z_knee, threshold)
    if not txt:
        return None

    wd, wl, wk = _group_weights(group)

    def _wz(zv: Optional[float], w: float) -> float:
        if zv is None or w <= 0:
            return 0.0
        return float(min(abs(zv), 4.0) * w)

    score = max(_wz(z_dur, wd), _wz(z_len, wl), _wz(z_knee, wk))
    knee_only = has_k and not has_d and not has_l

    return {
        "text": txt,
        "score": float(score),
        "group": group,
        "knee_only": bool(knee_only),
        "z": {
            "duration": z_dur,
            "length": z_len,
            "knee": z_knee,
        },
    }


def _select_sentences(candidates: list[Dict[str, Any]], max_sentences: int) -> list[str]:
    if not candidates:
        return []

    primary = [c for c in candidates if not bool(c.get("knee_only", False))]
    secondary = [c for c in candidates if bool(c.get("knee_only", False))]

    def _rank(c: Dict[str, Any]) -> float:
        base = float(c.get("score", 0.0))
        g = str(c.get("group", ""))
        mult = 1.15 if g in {"step", "accented_step"} else 0.9
        return base * mult

    primary = sorted(primary, key=_rank, reverse=True)
    secondary = sorted(secondary, key=_rank, reverse=True)
    ordered = primary + secondary

    chosen: list[Dict[str, Any]] = []
    if ordered:
        chosen.append(ordered[0])

    if max_sentences >= 2 and len(ordered) > 1:
        g0 = str(chosen[0].get("group", ""))
        alt = next((c for c in ordered[1:] if str(c.get("group", "")) != g0), None)
        if alt is None:
            alt = ordered[1]
        chosen.append(alt)

    used_text = {str(c.get("text", "")) for c in chosen}
    if max_sentences > len(chosen):
        for c in ordered:
            t = str(c.get("text", ""))
            if t in used_text:
                continue
            chosen.append(c)
            used_text.add(t)
            if len(chosen) >= max_sentences:
                break

    return [str(c.get("text", "")) for c in chosen if str(c.get("text", ""))]


def build_model_input_fast(
    *,
    window: FrameWindow,
    refs: PatternStepRefs,
    input_hz: float,
    z_threshold: float = 1.0,
    max_sentences: int = 2,
) -> tuple[Dict[str, str], Dict[str, Any]]:
    frames = window.frames
    if len(frames) < 10:
        rec = {"instruction": MODEL_INSTRUCTION, "input": "The performance was very good."}
        return rec, {"reason": "too_few_frames"}

    needed = ["LTHI", "LKNE", "LANK", "RTHI", "RKNE", "RANK", "LASI", "RASI", "LPSI", "RPSI"]
    mk: Dict[str, np.ndarray] = {name: _interp_nan_xyz(_extract_marker(frames, name)) for name in needed}

    pelvis = 0.5 * (mk["LASI"] + mk["RASI"])

    pelvis_width = np.linalg.norm(mk["RASI"] - mk["LASI"], axis=1)
    scale_ref = float(np.nanmedian(pelvis_width))
    if not np.isfinite(scale_ref) or scale_ref <= 1e-6:
        scale_ref = 1.0
    scale = 1.0 / scale_ref

    for k in mk:
        mk[k] = (mk[k] - pelvis) * scale

    asis_mid = 0.5 * (mk["LASI"] + mk["RASI"])
    psis_mid = 0.5 * (mk["LPSI"] + mk["RPSI"])
    fwd = asis_mid[:, :2] - psis_mid[:, :2]
    phi = np.arctan2(fwd[:, 1], fwd[:, 0])
    theta = (np.pi / 2.0) - phi
    c = np.cos(theta)
    s = np.sin(theta)

    for k in mk:
        x = mk[k][:, 0].copy()
        y = mk[k][:, 1].copy()
        mk[k][:, 0] = x * c - y * s
        mk[k][:, 1] = x * s + y * c

    l_knee = _knee_flexion_deg(mk["LTHI"], mk["LKNE"], mk["LANK"])
    r_knee = _knee_flexion_deg(mk["RTHI"], mk["RKNE"], mk["RANK"])

    l_peaks = _detect_peaks(l_knee, input_hz)
    r_peaks = _detect_peaks(r_knee, input_hz)
    l_acc_peaks = _accent_subset(l_peaks, l_knee)
    r_acc_peaks = _accent_subset(r_peaks, r_knee)

    m_step_l = _side_metrics(l_peaks, mk["LANK"], mk["RANK"], l_knee, input_hz, with_length=True)
    m_step_r = _side_metrics(r_peaks, mk["RANK"], mk["LANK"], r_knee, input_hz, with_length=True)
    m_step_acc_l = _side_metrics(l_acc_peaks, mk["LANK"], mk["RANK"], l_knee, input_hz, with_length=True)
    m_step_acc_r = _side_metrics(r_acc_peaks, mk["RANK"], mk["LANK"], r_knee, input_hz, with_length=True)
    m_acc_l = _side_metrics(l_acc_peaks, mk["LANK"], mk["RANK"], l_knee, input_hz, with_length=False)
    m_acc_r = _side_metrics(r_acc_peaks, mk["RANK"], mk["LANK"], r_knee, input_hz, with_length=False)

    candidates: list[Dict[str, Any]] = []
    for cand in [
        _candidate(side="left", prefix="Steps", group="step", metrics=m_step_l, ref=refs.step_left, use_length=True, threshold=z_threshold),
        _candidate(side="right", prefix="Steps", group="step", metrics=m_step_r, ref=refs.step_right, use_length=True, threshold=z_threshold),
        _candidate(side="left", prefix="Accented steps", group="accented_step", metrics=m_step_acc_l, ref=refs.step_accent_left, use_length=True, threshold=z_threshold),
        _candidate(side="right", prefix="Accented steps", group="accented_step", metrics=m_step_acc_r, ref=refs.step_accent_right, use_length=True, threshold=z_threshold),
        _candidate(side="left", prefix="Accents", group="accent", metrics=m_acc_l, ref=refs.accent_left, use_length=False, threshold=z_threshold),
        _candidate(side="right", prefix="Accents", group="accent", metrics=m_acc_r, ref=refs.accent_right, use_length=False, threshold=z_threshold),
    ]:
        if cand is not None:
            candidates.append(cand)

    chosen = _select_sentences(candidates, max_sentences=max(1, int(max_sentences)))

    if not chosen:
        input_text = "The performance was very good."
    else:
        input_text = " ".join(chosen)

    rec = {
        "instruction": MODEL_INSTRUCTION,
        "input": input_text,
    }

    debug = {
        "window_index": int(window.window_index),
        "frame_count": int(window.frame_count),
        "scale_ref": scale_ref,
        "left_peak_count": int(l_peaks.size),
        "right_peak_count": int(r_peaks.size),
        "left_accent_peak_count": int(l_acc_peaks.size),
        "right_accent_peak_count": int(r_acc_peaks.size),
        "left_metrics": m_step_l,
        "right_metrics": m_step_r,
        "left_accent_metrics": m_acc_l,
        "right_accent_metrics": m_acc_r,
        "candidates": candidates,
        "input": input_text,
    }
    return rec, debug
