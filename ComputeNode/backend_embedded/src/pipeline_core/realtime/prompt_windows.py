from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PHASE_RE = re.compile(r"\b(start|end)\b", re.IGNORECASE)


def z_score(measured: float, avg: float, stdev: float) -> float:
    if stdev <= 0:
        return 0.0
    return (measured - avg) / stdev


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _split_base_phase(label: str) -> Tuple[str, Optional[str]]:
    m = PHASE_RE.search(label or "")
    phase = m.group(1).lower() if m else None
    base = PHASE_RE.sub("", label or "")
    base = re.sub(r"\s+", " ", base).strip(" ,")
    return base, phase


def _normalize_event_base_to_pattern_key(base: str) -> Optional[str]:
    low = base.lower().strip()

    if low == "arms up":
        return "arms up"
    if low == "head nod":
        return "head nod"
    if low == "turn (left)":
        return "turn (left)"
    if low == "turn (right)":
        return "turn (right)"
    if low == "bow":
        return "bow"
    if low == "bow, r lead":
        return "bow, R lead"
    if low == "bow, l lead":
        return "bow, L lead"

    side = None
    if low.startswith("r "):
        side = "R"
    elif low.startswith("l "):
        side = "L"

    if side is not None and "step" in low:
        accented = "accented" in low
        side_step = "side" in low
        if accented and side_step:
            return f"{side} step (accented, side)"
        if accented:
            return f"{side} step (accented)"
        return f"{side} step"

    if side is not None and "accent" in low and "step" not in low:
        return f"{side} accent"

    return None


def _summary_key_for_pattern_key(pattern_key: str) -> str:
    if pattern_key == "arms up":
        return "arms_up"
    if pattern_key == "head nod":
        return "head_nod"
    if pattern_key == "turn (left)":
        return "turn_left"
    if pattern_key == "turn (right)":
        return "turn_right"
    if pattern_key == "bow":
        return "bow"
    if pattern_key == "bow, R lead":
        return "bow_R_lead"
    if pattern_key == "bow, L lead":
        return "bow_L_lead"

    low = pattern_key.lower()
    side = "R" if low.startswith("r ") else "L" if low.startswith("l ") else "U"
    if "step (accented, side)" in low:
        return f"step_{side}_accented_side"
    if "step (accented)" in low:
        return f"step_{side}_accented"
    if "step" in low:
        return f"step_{side}"
    if "accent" in low:
        return f"accent_{side}"
    return low.replace(" ", "_")


def _metric_name_pairs_for_event(pattern_key: str, event_end: Dict[str, Any], duration_s: float) -> Dict[str, float]:
    out: Dict[str, float] = {"duration_seconds": duration_s}

    val = _safe_float(event_end.get("value"))
    if val is not None:
        out["step_length_normalized"] = val

    knee = _safe_float(event_end.get("max_knee_angle"))
    if knee is not None:
        out["max_knee_angle"] = knee

    arm = _safe_float(event_end.get("max_arm_angle"))
    if arm is None:
        arm = _safe_float(event_end.get("max_arms_angle"))
    if arm is not None:
        out["max_arm_angle"] = arm

    head = _safe_float(event_end.get("max_head_angle"))
    if head is not None:
        out["max_head_angle"] = head

    return out


def _edit_distance(a: List[str], b: List[str]) -> int:
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + cost,
            )
    return dp[n][m]


def _order_score_from_distance(d: int) -> int:
    if d == 0:
        return 100
    if d == 1:
        return 80
    if d == 2:
        return 60
    return 40


@dataclass
class PatternData:
    pattern_name: str
    sequence: List[str]
    performance: Dict[str, Dict[str, Dict[str, float]]]
    arm_stability: Dict[str, Dict[str, Any]]


def load_enriched_pattern(path: Path) -> PatternData:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return PatternData(
        pattern_name=str(obj.get("pattern_name") or path.stem.replace("_pattern", "")),
        sequence=list(obj.get("consensus_sequence_expanded") or []),
        performance=dict(obj.get("performance_metrics") or {}),
        arm_stability=dict(obj.get("arm_stability_metrics") or {}),
    )


def _best_expected_subsequence(ref_sequence: List[str], observed: List[str]) -> List[str]:
    if not observed:
        return []
    k = len(observed)
    if not ref_sequence:
        return []
    if len(ref_sequence) <= k:
        return ref_sequence

    best = ref_sequence[:k]
    best_d = _edit_distance(observed, best)
    for i in range(1, len(ref_sequence) - k + 1):
        cand = ref_sequence[i : i + k]
        d = _edit_distance(observed, cand)
        if d < best_d:
            best_d = d
            best = cand
    return best


def build_window_record(
    stage7_json: Dict[str, Any],
    pattern: PatternData,
    *,
    window_id: int,
    window_start: float,
    window_end: float,
) -> Dict[str, Any]:
    events = [e for e in (stage7_json.get("events") or []) if isinstance(e, dict)]
    events = sorted(events, key=lambda ev: float(ev.get("time", 0.0)))

    open_stacks: Dict[str, List[float]] = {}
    metrics_bucket: Dict[str, Dict[str, List[float]]] = {}
    observed_sequence: List[str] = []

    for ev in events:
        label = str(ev.get("label") or "")
        if not label:
            continue
        base, phase = _split_base_phase(label)
        pattern_key = _normalize_event_base_to_pattern_key(base)
        if not pattern_key:
            continue

        if phase == "start":
            open_stacks.setdefault(pattern_key, []).append(float(ev.get("time", 0.0)))
            continue
        if phase != "end":
            continue

        stack = open_stacks.get(pattern_key) or []
        if not stack:
            continue
        start_t = stack.pop()
        end_t = float(ev.get("time", start_t))
        duration = max(0.0, end_t - start_t)

        measured = _metric_name_pairs_for_event(pattern_key, ev, duration)
        pattern_metrics = pattern.performance.get(pattern_key, {})
        if not pattern_metrics:
            continue

        summary_key = _summary_key_for_pattern_key(pattern_key)
        observed_sequence.append(pattern_key)
        metric_acc = metrics_bucket.setdefault(summary_key, {})

        for metric_name, measured_value in measured.items():
            ref = pattern_metrics.get(metric_name)
            if not isinstance(ref, dict):
                continue
            avg = _safe_float(ref.get("average"))
            stdev = _safe_float(ref.get("stdev"))
            if avg is None or stdev is None:
                continue
            z = z_score(measured_value, avg, stdev)
            if metric_name == "duration_seconds":
                z_key = "z_mean_duration"
            elif metric_name == "step_length_normalized":
                z_key = "z_mean_step_length"
            elif metric_name == "max_knee_angle":
                z_key = "z_mean_knee_angle"
            elif metric_name == "max_arm_angle":
                z_key = "z_mean_arm_angle"
            elif metric_name == "max_head_angle":
                z_key = "z_mean_head_angle"
            else:
                continue
            metric_acc.setdefault(z_key, []).append(float(z))

    metrics_summary: Dict[str, Dict[str, float]] = {}
    z_values: List[float] = []

    for key, z_block in metrics_bucket.items():
        out_block: Dict[str, float] = {}
        for z_key, vals in z_block.items():
            if not vals:
                continue
            z_mean = sum(vals) / len(vals)
            out_block[z_key] = round(float(z_mean), 4)
            z_values.append(abs(z_mean))
        if out_block:
            metrics_summary[key] = out_block

    # Arm/elbow stability summary
    stage7_stab = dict(stage7_json.get("arm_stability_metrics") or {})
    stability_map = {
        "Lshoulder_x": "arm_stability_left_x",
        "Rshoulder_x": "arm_stability_right_x",
        "Lshoulder_y": "arm_stability_left_y",
        "Rshoulder_y": "arm_stability_right_y",
        "LElbow_x": "elbow_stability_left",
        "RElbow_x": "elbow_stability_right",
    }

    for ch_name, out_key in stability_map.items():
        measured_periods = stage7_stab.get(ch_name)
        expected_periods = pattern.arm_stability.get(ch_name)
        if not isinstance(measured_periods, dict):
            continue
        if not isinstance(expected_periods, dict):
            continue

        measured_vals: List[Tuple[float, float]] = []
        for _pname, pobj in measured_periods.items():
            if not isinstance(pobj, dict):
                continue
            dur = _safe_float(pobj.get("duration_seconds"))
            ar = pobj.get("angle_range_degrees") if isinstance(pobj.get("angle_range_degrees"), dict) else {}
            mn = _safe_float(ar.get("min"))
            mx = _safe_float(ar.get("max"))
            if dur is None or mn is None or mx is None:
                continue
            measured_vals.append((dur, (mn + mx) / 2.0))

        if not measured_vals:
            continue

        exp_durs: List[float] = []
        exp_angles: List[float] = []
        for _pname, pobj in expected_periods.items():
            if not isinstance(pobj, dict):
                continue
            d = _safe_float(pobj.get("duration_seconds"))
            a_stats = pobj.get("angle_stats_degrees") if isinstance(pobj.get("angle_stats_degrees"), dict) else {}
            a = _safe_float(a_stats.get("average"))
            if d is not None:
                exp_durs.append(d)
            if a is not None:
                exp_angles.append(a)

        if not exp_durs or not exp_angles:
            continue

        m_dur = sum(v[0] for v in measured_vals) / len(measured_vals)
        m_ang = sum(v[1] for v in measured_vals) / len(measured_vals)
        e_dur_avg = sum(exp_durs) / len(exp_durs)
        e_ang_avg = sum(exp_angles) / len(exp_angles)

        def _stdev(vals: Iterable[float]) -> float:
            vals = list(vals)
            if len(vals) <= 1:
                return 0.0
            avg = sum(vals) / len(vals)
            var = sum((v - avg) ** 2 for v in vals) / (len(vals) - 1)
            return var ** 0.5

        z_t = z_score(m_dur, e_dur_avg, _stdev(exp_durs))
        z_a = z_score(m_ang, e_ang_avg, _stdev(exp_angles))
        z_values.extend([abs(z_t), abs(z_a)])

        expected_frac = min(1.0, len(measured_vals) / max(1, len(expected_periods)))
        metrics_summary[out_key] = {
            "expected_frac": round(float(expected_frac), 4),
            "z_mean_timing": round(float(z_t), 4),
            "z_mean_angle": round(float(z_a), 4),
        }

    expected = _best_expected_subsequence(pattern.sequence, observed_sequence)
    d = _edit_distance(observed_sequence, expected)
    order_score = _order_score_from_distance(d)
    z_avg = (sum(z_values) / len(z_values)) if z_values else 0.0
    composite_score = int(round(max(60.0, 100.0 - min(40.0, z_avg * 12.0))))

    errors_detected: List[str] = []
    for key, block in metrics_summary.items():
        for b_key, b_val in block.items():
            if not b_key.startswith("z_"):
                continue
            if abs(float(b_val)) >= 1.0:
                direction = "high" if float(b_val) > 0 else "low"
                errors_detected.append(f"{key}:{b_key}:{direction}")

    return {
        "pattern_id": pattern.pattern_name,
        "window_id": int(window_id),
        "window_start": round(float(window_start), 3),
        "window_end": round(float(window_end), 3),
        "current_sequence": observed_sequence,
        "previous_tail": [],
        "metrics_summary": metrics_summary,
        "order_score": int(order_score),
        "composite_score": int(composite_score),
        "errors_detected": sorted(set(errors_detected)),
    }


def build_window_records_from_stage7(
    *,
    stage7_root: Path,
    pattern_file: Path,
    manifest_by_stem: Dict[str, Dict[str, Any]],
    out_windows_dir: Path,
) -> int:
    pattern = load_enriched_pattern(pattern_file)
    out_windows_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for stage7_path in sorted(stage7_root.rglob("*.json")):
        data = json.loads(stage7_path.read_text(encoding="utf-8"))
        stem = stage7_path.stem
        m = manifest_by_stem.get(stem, {})
        window_id = int(m.get("window_index", count + 1))
        window_start = float(m.get("start_s", 0.0))
        window_end = float(m.get("end_s", window_start + 4.0))
        rec = build_window_record(
            data,
            pattern,
            window_id=window_id,
            window_start=window_start,
            window_end=window_end,
        )
        out_path = out_windows_dir / f"{stem}.json"
        out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        count += 1
    return count

