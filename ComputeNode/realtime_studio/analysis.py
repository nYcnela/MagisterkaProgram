from __future__ import annotations

import importlib
import json
import math
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .compute_settings import ComputeNodeConfig
from .launch import discover_backend_root, resolve_under_root


EVENT_METRIC_LABELS = {
    "duration_seconds": "Movement duration",
    "step_length_normalized": "Step length",
    "max_knee_angle": "Knee angle",
    "max_arm_angle": "Arm angle",
    "max_head_angle": "Head angle",
}

EVENT_METRIC_UNITS = {
    "duration_seconds": "s",
    "step_length_normalized": "norm",
    "max_knee_angle": "deg",
    "max_arm_angle": "deg",
    "max_head_angle": "deg",
}

CHANNEL_LABELS = {
    "Lshoulder_x": "L shoulder X",
    "Rshoulder_x": "R shoulder X",
    "Lshoulder_y": "L shoulder Y",
    "Rshoulder_y": "R shoulder Y",
    "LElbow_x": "L elbow",
    "RElbow_x": "R elbow",
}

STABILITY_GROUPS = {
    "shoulders": ["Lshoulder_x", "Rshoulder_x", "Lshoulder_y", "Rshoulder_y"],
    "elbows": ["LElbow_x", "RElbow_x"],
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _safe_score(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (value != value or value == float("inf") or value == float("-inf")):
        return None
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sample_stdev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return variance ** 0.5


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _load_manifest_by_stem(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in _read_jsonl(path):
        stem = str(item.get("file_stem") or "")
        if stem:
            out[stem] = item
    return out


def _analysis_window_meta(
    manifest_by_stem: dict[str, dict[str, Any]],
    stage7_files: list[Path],
) -> dict[str, Any]:
    manifest_items = sorted(
        (
            item
            for item in manifest_by_stem.values()
            if isinstance(item, dict)
        ),
        key=lambda item: int(item.get("window_index", 0)),
    )
    processed_stems = {path.stem for path in stage7_files}
    processed_items = [item for item in manifest_items if str(item.get("file_stem") or "") in processed_stems]
    missing_items = [item for item in manifest_items if str(item.get("file_stem") or "") not in processed_stems]

    processed_indices = [int(item.get("window_index", 0)) for item in processed_items]
    missing_indices = [int(item.get("window_index", 0)) for item in missing_items]
    processed_until_s = max((float(item.get("end_s", 0.0)) for item in processed_items), default=0.0)
    capture_until_s = max((float(item.get("end_s", 0.0)) for item in manifest_items), default=processed_until_s)

    trailing_missing_start = None
    if missing_indices:
        sorted_missing = sorted(missing_indices)
        candidate = sorted_missing[0]
        expected_suffix = list(range(candidate, candidate + len(sorted_missing)))
        if sorted_missing == expected_suffix:
            trailing_missing_start = candidate

    return {
        "capture_window_count": len(manifest_items),
        "processed_window_count": len(processed_items),
        "missing_window_count": len(missing_items),
        "processed_window_indices": processed_indices,
        "missing_window_indices": missing_indices,
        "processed_until_s": round(processed_until_s, 3),
        "capture_until_s": round(capture_until_s, 3),
        "is_partial": bool(missing_items),
        "trailing_missing_start_index": trailing_missing_start,
    }


@lru_cache(maxsize=8)
def _load_prompt_module(src_root_str: str):
    src_root = Path(src_root_str)
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    return importlib.import_module("pipeline_core.realtime.prompt_windows")


def _analysis_roots(cfg: ComputeNodeConfig) -> tuple[Path, Path, Path]:
    backend_root = discover_backend_root(cfg.backend_root)
    output_root = resolve_under_root(cfg.output_root, backend_root)
    pattern_root = backend_root / "dance_patterns"
    return backend_root, output_root, pattern_root


def _is_run_dir(path: Path) -> bool:
    return (
        (path / "session_meta.json").exists()
        or (path / "capture").is_dir()
        or (path / "run_summary.json").exists()
    )


def _iter_run_dirs(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    runs: list[Path] = []
    for date_dir in output_root.iterdir():
        if not date_dir.is_dir():
            continue
        for child in date_dir.iterdir():
            if not child.is_dir():
                continue
            if _is_run_dir(child):
                runs.append(child)
            else:
                # dancer subfolder — one level deeper
                for run_dir in child.iterdir():
                    if run_dir.is_dir() and _is_run_dir(run_dir):
                        runs.append(run_dir)
    return runs


def _find_run_dir(output_root: Path, run_id: str) -> Path | None:
    if not output_root.exists():
        return None
    for date_dir in output_root.iterdir():
        if not date_dir.is_dir():
            continue
        candidate = date_dir / run_id
        if candidate.is_dir():
            return candidate
        for child in date_dir.iterdir():
            if not child.is_dir():
                continue
            candidate = child / run_id
            if candidate.is_dir():
                return candidate
    return None


@lru_cache(maxsize=8)
def _known_dance_ids(pattern_root_str: str) -> list[str]:
    pattern_root = Path(pattern_root_str)
    dance_ids: list[str] = []
    for path in pattern_root.glob("*_pattern.json"):
        dance_ids.append(path.stem.replace("_pattern", ""))
    return sorted(dance_ids, key=len, reverse=True)


def _load_session_meta(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "session_meta.json"
    if not path.exists():
        return {}
    try:
        data = _load_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _infer_dance_id(run_id: str, session_meta: dict[str, Any], pattern_root: Path) -> str:
    dance_id = str(session_meta.get("dance_id") or "").strip()
    if dance_id:
        return dance_id
    for candidate in _known_dance_ids(str(pattern_root)):
        if run_id.startswith(f"session_{candidate}_"):
            return candidate
    return ""


def _infer_sequence_name(run_dir: Path, session_meta: dict[str, Any]) -> str:
    sequence_name = str(session_meta.get("sequence_name") or "").strip()
    if sequence_name:
        return sequence_name
    raw_root = run_dir / "capture" / "raw"
    if raw_root.exists():
        for child in sorted(raw_root.iterdir()):
            if child.is_dir():
                return child.name
    return ""


def _run_timestamp(run_dir: Path, session_meta: dict[str, Any]) -> str:
    created = str(session_meta.get("created_at") or "").strip()
    if created:
        return created
    return datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds")


def _live_feedback_settings(session_meta: dict[str, Any], cfg: ComputeNodeConfig) -> dict[str, Any]:
    control_payload = session_meta.get("control_payload")
    control_payload = control_payload if isinstance(control_payload, dict) else {}
    try:
        session_live_z_threshold = float(control_payload.get("live_z_threshold", cfg.live_z_threshold))
    except Exception:
        session_live_z_threshold = float(cfg.live_z_threshold)
    try:
        session_live_major_order_threshold = int(
            control_payload.get("live_major_order_threshold", cfg.live_major_order_threshold)
        )
    except Exception:
        session_live_major_order_threshold = int(cfg.live_major_order_threshold)
    return {
        "live_z_threshold": round(float(cfg.live_z_threshold), 4),
        "live_major_order_threshold": int(cfg.live_major_order_threshold),
        "session_live_z_threshold": round(session_live_z_threshold, 4),
        "session_live_major_order_threshold": session_live_major_order_threshold,
    }


def list_analysis_runs(cfg: ComputeNodeConfig) -> list[dict[str, Any]]:
    _backend_root, output_root, pattern_root = _analysis_roots(cfg)

    items: list[dict[str, Any]] = []
    for run_dir in _iter_run_dirs(output_root):
        run_id = run_dir.name
        session_meta = _load_session_meta(run_dir)
        dance_id = _infer_dance_id(run_id, session_meta, pattern_root)
        sequence_name = _infer_sequence_name(run_dir, session_meta)
        feedback_path = run_dir / "feedback.jsonl"
        manifest_path = run_dir / "capture" / "windows_manifest.jsonl"
        first_name = str(session_meta.get("dancer_first_name") or "").strip()
        last_name = str(session_meta.get("dancer_last_name") or "").strip()
        dancer_name = " ".join(part for part in [first_name, last_name] if part).strip()
        items.append(
            {
                "run_id": run_id,
                "session_id": str(session_meta.get("session_id") or "").strip(),
                "dance_id": dance_id,
                "sequence_name": sequence_name,
                "gender": str(session_meta.get("gender") or "").strip(),
                "step_type": str(session_meta.get("step_type") or "").strip(),
                "dancer_first_name": first_name,
                "dancer_last_name": last_name,
                "dancer_name": dancer_name,
                "created_at": _run_timestamp(run_dir, session_meta),
                "window_count": _count_lines(manifest_path),
                "feedback_count": _count_lines(feedback_path),
            }
        )

    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def _feedback_by_window(run_dir: Path) -> dict[int, dict[str, Any]]:
    feedback_map: dict[int, dict[str, Any]] = {}
    for item in _read_jsonl(run_dir / "feedback.jsonl"):
        try:
            window_index = int(item.get("window_index", -1))
        except Exception:
            continue
        if window_index < 0:
            continue
        feedback_map[window_index] = item
    return feedback_map


def _resolve_stage7_files(run_dir: Path, sequence_name: str) -> list[Path]:
    analysis_root = run_dir / "analysis" / "stage7"
    if analysis_root.exists():
        files = sorted(analysis_root.glob("*.json"))
        if files:
            return files

    pipeline_root = run_dir / "pipeline" / "json" / "7_arms_position" / sequence_name
    if pipeline_root.exists():
        return sorted(pipeline_root.glob("*.json"))
    return []


def _event_measurements(event_end: dict[str, Any], duration_s: float) -> dict[str, float]:
    out: dict[str, float] = {"duration_seconds": duration_s}

    value = event_end.get("value")
    if value is not None:
        try:
            out["step_length_normalized"] = float(value)
        except Exception:
            pass

    for key in ["max_knee_angle", "max_arm_angle", "max_head_angle"]:
        value = event_end.get(key)
        if value is None and key == "max_arm_angle":
            value = event_end.get("max_arms_angle")
        if value is None:
            continue
        try:
            out[key] = float(value)
        except Exception:
            continue
    return out


def _build_event_metric_series(stage7_json: dict[str, Any], pattern: Any, manifest: dict[str, Any], prompt_module) -> dict[str, list[dict[str, Any]]]:
    series: dict[str, list[dict[str, Any]]] = {key: [] for key in EVENT_METRIC_LABELS}
    split_base = getattr(prompt_module, "_split_base_phase")
    normalize_key = getattr(prompt_module, "_normalize_event_base_to_pattern_key")

    events = [item for item in stage7_json.get("events", []) if isinstance(item, dict)]
    events.sort(key=lambda item: float(item.get("time", 0.0)))

    open_stacks: dict[str, list[float]] = {}
    event_occurrence: dict[str, int] = {}
    window_index = int(manifest.get("window_index", 0))
    window_start = float(manifest.get("start_s", 0.0))
    window_end = float(manifest.get("end_s", window_start))

    for event in events:
        label = str(event.get("label") or "")
        if not label:
            continue
        base, phase = split_base(label)
        pattern_key = normalize_key(base)
        if not pattern_key:
            continue

        if phase == "start":
            open_stacks.setdefault(pattern_key, []).append(float(event.get("time", 0.0)))
            continue
        if phase != "end":
            continue

        stack = open_stacks.get(pattern_key) or []
        if not stack:
            continue

        start_t = stack.pop()
        end_t = float(event.get("time", start_t))
        duration_s = max(0.0, end_t - start_t)
        occurrence = event_occurrence.get(pattern_key, 0) + 1
        event_occurrence[pattern_key] = occurrence

        pattern_metrics = pattern.performance.get(pattern_key, {})
        if not isinstance(pattern_metrics, dict):
            continue

        for metric_name, measured in _event_measurements(event, duration_s).items():
            ref = pattern_metrics.get(metric_name)
            if not isinstance(ref, dict):
                continue
            try:
                expected_avg = float(ref.get("average"))
            except Exception:
                continue
            try:
                expected_stdev = float(ref.get("stdev", 0.0))
            except Exception:
                expected_stdev = 0.0
            series.setdefault(metric_name, []).append(
                {
                    "event_key": pattern_key,
                    "event_label": pattern_key,
                    "occurrence": occurrence,
                    "window_index": window_index,
                    "window_start": round(window_start, 3),
                    "window_end": round(window_end, 3),
                    "event_time": round(end_t, 3),
                    "measured": round(float(measured), 4),
                    "expected_avg": round(expected_avg, 4),
                    "expected_stdev": round(expected_stdev, 4),
                    "x_label": f"{pattern_key} #{occurrence}",
                }
            )

    return series


def _channel_points(
    stage7_items: list[dict[str, Any]],
    pattern: Any,
    *,
    channel_names: list[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for channel_name in channel_names:
        measured_durations, measured_angles, _period_count = _measured_stability_values(stage7_items, channel_name)
        expected_periods = pattern.arm_stability.get(channel_name)
        if not isinstance(expected_periods, dict) or not expected_periods:
            continue
        expected_durations: list[float] = []
        expected_angles: list[float] = []
        expected_angle_stdevs: list[float] = []
        for period in expected_periods.values():
            if not isinstance(period, dict):
                continue
            try:
                expected_durations.append(float(period.get("duration_seconds")))
            except Exception:
                pass
            angle_stats = period.get("angle_stats_degrees") if isinstance(period.get("angle_stats_degrees"), dict) else {}
            try:
                expected_angles.append(float(angle_stats.get("average")))
            except Exception:
                pass
            try:
                expected_angle_stdevs.append(float(angle_stats.get("stdev")))
            except Exception:
                pass

        if not measured_durations and not measured_angles:
            continue

        output.append(
            {
                "channel": channel_name,
                "label": CHANNEL_LABELS.get(channel_name, channel_name),
                "measured_angle_avg": round(float(_mean(measured_angles) or 0.0), 4),
                "expected_angle_avg": round(float(_mean(expected_angles) or 0.0), 4),
                "expected_angle_stdev": round(float(_mean(expected_angle_stdevs) or _sample_stdev(expected_angles)), 4),
                "measured_duration_avg": round(float(_mean(measured_durations) or 0.0), 4),
                "expected_duration_avg": round(float(_mean(expected_durations) or 0.0), 4),
                "expected_duration_stdev": round(float(_sample_stdev(expected_durations)), 4),
            }
        )
    return output


def _measured_stability_values(stage7_items: list[dict[str, Any]], channel_name: str) -> tuple[list[float], list[float], int]:
    measured_durations: list[float] = []
    measured_angles: list[float] = []
    period_count = 0
    for stage7_json in stage7_items:
        measured_periods = stage7_json.get("arm_stability_metrics", {}).get(channel_name)
        if not isinstance(measured_periods, dict):
            continue
        for period in measured_periods.values():
            if not isinstance(period, dict):
                continue
            period_count += 1
            try:
                duration = float(period.get("duration_seconds"))
            except Exception:
                duration = None  # type: ignore[assignment]
            angle_range = period.get("angle_range_degrees") if isinstance(period.get("angle_range_degrees"), dict) else {}
            try:
                angle_min = float(angle_range.get("min"))
                angle_max = float(angle_range.get("max"))
            except Exception:
                angle_min = None  # type: ignore[assignment]
                angle_max = None  # type: ignore[assignment]
            if duration is not None:
                measured_durations.append(duration)
            if angle_min is not None and angle_max is not None:
                measured_angles.append((angle_min + angle_max) / 2.0)
    return measured_durations, measured_angles, period_count


def _unexpected_channel_points(
    stage7_items: list[dict[str, Any]],
    pattern: Any,
    *,
    channel_names: list[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for channel_name in channel_names:
        expected_periods = pattern.arm_stability.get(channel_name)
        if isinstance(expected_periods, dict) and expected_periods:
            continue

        measured_durations, measured_angles, period_count = _measured_stability_values(stage7_items, channel_name)
        if not measured_durations and not measured_angles:
            continue

        output.append(
            {
                "channel": channel_name,
                "label": CHANNEL_LABELS.get(channel_name, channel_name),
                "measured_angle_avg": round(float(_mean(measured_angles)), 4) if measured_angles else None,
                "measured_duration_avg": round(float(_mean(measured_durations)), 4) if measured_durations else None,
                "detected_period_count": int(period_count),
            }
        )
    return output


def _stability_meta(pattern: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    arm_stability = pattern.arm_stability if isinstance(pattern.arm_stability, dict) else {}
    for group_name, channel_names in STABILITY_GROUPS.items():
        missing_channels: list[str] = []
        expected_channels: list[str] = []
        for channel_name in channel_names:
            periods = arm_stability.get(channel_name)
            if isinstance(periods, dict) and periods:
                expected_channels.append(channel_name)
            else:
                missing_channels.append(channel_name)

        meta[group_name] = {
            "expected_channels": expected_channels,
            "missing_expected_channels": missing_channels,
            "no_expected_periods": not expected_channels,
        }
    return meta


def build_run_analysis(cfg: ComputeNodeConfig, run_id: str) -> dict[str, Any]:
    backend_root, output_root, pattern_root = _analysis_roots(cfg)
    run_dir = _find_run_dir(output_root, run_id)
    if run_dir is None:
        raise FileNotFoundError(f"Missing run directory: {run_id}")
    run_dir = run_dir.resolve()

    session_meta = _load_session_meta(run_dir)
    dance_id = _infer_dance_id(run_id, session_meta, pattern_root)
    if not dance_id:
        raise FileNotFoundError(f"Could not resolve dance_id for run: {run_id}")

    sequence_name = _infer_sequence_name(run_dir, session_meta)
    pattern_file = pattern_root / f"{dance_id}_pattern.json"
    if not pattern_file.exists():
        raise FileNotFoundError(f"Missing pattern file: {pattern_file}")

    prompt_module = _load_prompt_module(str(backend_root / "src"))
    pattern = prompt_module.load_enriched_pattern(pattern_file)
    live_feedback_settings = _live_feedback_settings(session_meta, cfg)

    stage7_files = _resolve_stage7_files(run_dir, sequence_name)
    if not stage7_files:
        raise FileNotFoundError(f"No stage7 analysis data for run: {run_id}")

    manifest_by_stem = _load_manifest_by_stem(run_dir / "capture" / "windows_manifest.jsonl")
    feedback_map = _feedback_by_window(run_dir)
    analysis_meta = _analysis_window_meta(manifest_by_stem, stage7_files)
    analysis_meta.update(live_feedback_settings)
    stability_meta = _stability_meta(pattern)

    event_series: dict[str, list[dict[str, Any]]] = {key: [] for key in EVENT_METRIC_LABELS}
    stage7_items: list[dict[str, Any]] = []
    window_scores: list[dict[str, Any]] = []

    for stage7_path in stage7_files:
        stage7_json = _load_json(stage7_path)
        stage7_items.append(stage7_json)
        manifest = manifest_by_stem.get(stage7_path.stem, {})

        series = _build_event_metric_series(stage7_json, pattern, manifest, prompt_module)
        for metric_name, points in series.items():
            event_series.setdefault(metric_name, []).extend(points)

        window_index = int(manifest.get("window_index", len(window_scores)))
        window_start = float(manifest.get("start_s", 0.0))
        window_end = float(manifest.get("end_s", window_start + float(cfg.window_seconds)))
        window_record = prompt_module.build_window_record(
            stage7_json,
            pattern,
            window_id=window_index,
            window_start=window_start,
            window_end=window_end,
        )
        feedback = feedback_map.get(window_index, {})
        window_scores.append(
            {
                "window_index": window_index,
                "window_start": round(window_start, 3),
                "window_end": round(window_end, 3),
                "order_score": int(window_record.get("order_score", 0)),
                "composite_score": int(window_record.get("composite_score", 0)),
                "feedback_score": _safe_score(feedback.get("score")),
                "feedback": feedback.get("feedback", ""),
                "observed_sequence": list(window_record.get("current_sequence") or []),
            }
        )

    for metric_name, points in event_series.items():
        points.sort(key=lambda item: (int(item.get("window_index", 0)), float(item.get("event_time", 0.0))))
        for index, point in enumerate(points, 1):
            point["index"] = index

    window_scores.sort(key=lambda item: int(item.get("window_index", 0)))
    for index, item in enumerate(window_scores, 1):
        item["index"] = index

    dance_runs = list_analysis_runs(cfg)
    run_item = next((item for item in dance_runs if item.get("run_id") == run_id), None)
    if run_item is None:
        run_item = {
            "run_id": run_id,
            "dance_id": dance_id,
            "sequence_name": sequence_name,
            "dancer_name": " ".join(
                part
                for part in [
                    str(session_meta.get("dancer_first_name") or "").strip(),
                    str(session_meta.get("dancer_last_name") or "").strip(),
                ]
                if part
            ).strip(),
            "created_at": _run_timestamp(run_dir, session_meta),
        }

    payload = {
        "run": {
            **run_item,
            "session_id": str(session_meta.get("session_id") or "").strip(),
            "pattern_file": str(pattern_file.resolve()),
            "stage7_files": len(stage7_files),
            "window_count": len(window_scores),
            "capture_window_count": int(analysis_meta.get("capture_window_count", len(window_scores))),
            "processed_window_count": int(analysis_meta.get("processed_window_count", len(window_scores))),
            "missing_window_count": int(analysis_meta.get("missing_window_count", 0)),
            "analysis_is_partial": bool(analysis_meta.get("is_partial", False)),
            "processed_until_s": float(analysis_meta.get("processed_until_s", 0.0)),
            "capture_until_s": float(analysis_meta.get("capture_until_s", 0.0)),
            "live_z_threshold": float(live_feedback_settings.get("live_z_threshold", cfg.live_z_threshold)),
            "live_major_order_threshold": int(
                live_feedback_settings.get("live_major_order_threshold", cfg.live_major_order_threshold)
            ),
        },
        "charts": {
            "meta": analysis_meta,
            "event_metrics": {
                metric_name: {
                    "title": EVENT_METRIC_LABELS[metric_name],
                    "unit": EVENT_METRIC_UNITS.get(metric_name, ""),
                    "points": points,
                }
                for metric_name, points in event_series.items()
                if points
            },
            "stability": {
                "meta": stability_meta,
                "shoulders": _channel_points(
                    stage7_items,
                    pattern,
                    channel_names=STABILITY_GROUPS["shoulders"],
                ),
                "elbows": _channel_points(
                    stage7_items,
                    pattern,
                    channel_names=STABILITY_GROUPS["elbows"],
                ),
                "unexpected_shoulders": _unexpected_channel_points(
                    stage7_items,
                    pattern,
                    channel_names=STABILITY_GROUPS["shoulders"],
                ),
                "unexpected_elbows": _unexpected_channel_points(
                    stage7_items,
                    pattern,
                    channel_names=STABILITY_GROUPS["elbows"],
                ),
            },
            "window_scores": window_scores,
        },
    }
    return _json_safe(payload)
