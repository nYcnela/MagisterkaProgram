#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import importlib.util
import json
import queue
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pipeline_core.offline_runner import candidate_root_overrides, resolve_placeholders
from pipeline_core.realtime.engine import RealtimeWindowEngine
from pipeline_core.realtime.prompt_windows import (
    build_window_record,
    build_window_records_from_stage7,
    load_enriched_pattern,
)
from pipeline_core.realtime.udp_receiver import run_udp_window_loop
from pipeline_core.realtime.window_csv import write_window_as_vicon_csv

MODEL_INSTRUCTION = (
    "You are the teacher of the Polish Polonaise dance. "
    "Based on the student's movement description, give one short sentence of supportive corrective feedback, "
    "then give a score from 1 to 5, where 5 is best."
)

# Live feedback calibrated more conservatively than offline artifacts
LIVE_DESC_Z_THRESHOLD = 1.5
LIVE_MAJOR_ORDER_THRESHOLD = 60
LIVE_EMIT_MINOR_ORDER_TEXT = False


def _tail(text: str, max_chars: int = 1800) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _run_subprocess(cmd: list[str], cwd: Path, *, print_output: bool = True) -> None:
    if print_output:
        print("[CMD]", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)

    if print_output:
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip())

    if proc.returncode != 0:
        stderr_tail = _tail((proc.stderr or "").strip())
        stdout_tail = _tail((proc.stdout or "").strip())
        msg = (
            f"Command failed with exit code {proc.returncode}: {' '.join(str(c) for c in cmd)}\n"
            f"--- stdout (tail) ---\n{stdout_tail}\n"
            f"--- stderr (tail) ---\n{stderr_tail}"
        )
        raise RuntimeError(msg)


def _load_manifest_by_stem(path: Path) -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        obj = json.loads(ln)
        stem = str(obj.get("file_stem") or "")
        if stem:
            out[stem] = obj
    return out


def _write_prompt_index(desc_root: Path, out_jsonl: Path) -> int:
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_jsonl.open("w", encoding="utf-8") as f:
        for p in sorted(desc_root.rglob("*_desc.json")):
            obj = json.loads(p.read_text(encoding="utf-8"))
            rec = {
                "file": str(p),
                "prompt": obj.get("prompt", ""),
                "composite_score": obj.get("composite_score"),
                "order_score": obj.get("order_score"),
                "labels": obj.get("labels", []),
                "top_info": obj.get("top_info", []),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    return count


def _write_instruction_index(training_prompts_root: Path, out_jsonl: Path) -> int:
    """
    Build a flat index of final 10_2 records (instruction/input/output) from split/bucket JSONL files.
    """
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_jsonl.open("w", encoding="utf-8") as out_f:
        for split in ("train", "val", "test"):
            for bucket in ("good", "medium", "bad"):
                src = training_prompts_root / split / bucket / "data.jsonl"
                if not src.exists():
                    continue
                for ln in src.read_text(encoding="utf-8").splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        continue
                    rec = {
                        "split": split,
                        "bucket": bucket,
                        "instruction": obj.get("instruction", ""),
                        "input": obj.get("input", ""),
                        "output": obj.get("output", ""),
                    }
                    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    count += 1
    return count


def _load_desc_generator_module() -> ModuleType:
    script_path = PROJECT_ROOT / "scripts/generate_feedback_descriptions.py"
    spec = importlib.util.spec_from_file_location("desc9_2", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load descriptive generator from: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _window_record_to_model_input(
    window_record: Dict[str, Any],
    desc_module: ModuleType,
    *,
    z_threshold: float = LIVE_DESC_Z_THRESHOLD,
    major_order_threshold: int = LIVE_MAJOR_ORDER_THRESHOLD,
    emit_minor_order_text: bool = LIVE_EMIT_MINOR_ORDER_TEXT,
) -> Dict[str, str]:
    metrics_summary = dict(window_record.get("metrics_summary") or {})
    order_score = window_record.get("order_score")
    errors_detected = list(window_record.get("errors_detected") or [])
    description, order_text, _top_info = desc_module.generate_description(
        metrics_summary,
        order_score,
        errors_detected=errors_detected,
        z_threshold=z_threshold,
        major_order_threshold=major_order_threshold,
        emit_minor_order_text=emit_minor_order_text,
    )

    description = (description or "").strip()
    if not description:
        description = "The performance was very good."

    input_text = f"{description} {order_text or ''}".strip()
    if not input_text:
        input_text = "The performance was very good."

    return {
        "instruction": MODEL_INSTRUCTION,
        "input": input_text,
    }


def _model_input_from_stage7_file(
    *,
    stage7_path: Path,
    pattern_data: Any,
    manifest: Dict[str, Any],
    default_window_seconds: float,
    desc_module: ModuleType,
    z_threshold: float = LIVE_DESC_Z_THRESHOLD,
    major_order_threshold: int = LIVE_MAJOR_ORDER_THRESHOLD,
    emit_minor_order_text: bool = LIVE_EMIT_MINOR_ORDER_TEXT,
) -> Dict[str, str]:
    stage7_data = json.loads(stage7_path.read_text(encoding="utf-8"))
    window_id = int(manifest.get("window_index", 0))
    window_start = float(manifest.get("start_s", 0.0))
    window_end = float(manifest.get("end_s", window_start + default_window_seconds))

    window_record = build_window_record(
        stage7_data,
        pattern_data,
        window_id=window_id,
        window_start=window_start,
        window_end=window_end,
    )
    return _window_record_to_model_input(
        window_record,
        desc_module,
        z_threshold=z_threshold,
        major_order_threshold=major_order_threshold,
        emit_minor_order_text=emit_minor_order_text,
    )


def _window_bundle_from_stage7_file(
    *,
    stage7_path: Path,
    pattern_data: Any,
    manifest: Dict[str, Any],
    default_window_seconds: float,
    desc_module: ModuleType,
    z_threshold: float = LIVE_DESC_Z_THRESHOLD,
    major_order_threshold: int = LIVE_MAJOR_ORDER_THRESHOLD,
    emit_minor_order_text: bool = LIVE_EMIT_MINOR_ORDER_TEXT,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    stage7_data = json.loads(stage7_path.read_text(encoding="utf-8"))
    window_id = int(manifest.get("window_index", 0))
    window_start = float(manifest.get("start_s", 0.0))
    window_end = float(manifest.get("end_s", window_start + default_window_seconds))

    window_record = build_window_record(
        stage7_data,
        pattern_data,
        window_id=window_id,
        window_start=window_start,
        window_end=window_end,
    )
    model_input = _window_record_to_model_input(
        window_record,
        desc_module,
        z_threshold=z_threshold,
        major_order_threshold=major_order_threshold,
        emit_minor_order_text=emit_minor_order_text,
    )
    return stage7_data, window_record, model_input



def _call_llm_server(llm_url: str, rec: Dict[str, Any], timeout_s: float = 30.0) -> Optional[Dict]:
    """
    POST {instruction, input} to llm_server /generate endpoint.
    Returns dict with keys: feedback, score, latency_s — or None on error.
    """
    try:
        payload = json.dumps({
            "instruction": rec.get("instruction", ""),
            "input": rec.get("input", ""),
        }).encode("utf-8")
        url = llm_url.rstrip("/") + "/generate"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body
    except urllib.error.URLError as e:
        print(f"[LLM][warn] Could not reach LLM server at {llm_url}: {e}")
        return None
    except Exception as e:
        print(f"[LLM][warn] Unexpected error calling LLM server: {e}")
        return None


def _write_model_inputs_index(
    *,
    stage7_root: Path,
    pattern_file: Path,
    manifest_by_stem: Dict[str, Dict],
    out_jsonl: Path,
    default_window_seconds: float,
) -> int:
    desc_module = _load_desc_generator_module()
    pattern_data = load_enriched_pattern(pattern_file)

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_jsonl.open("w", encoding="utf-8") as f:
        for stage7_path in sorted(stage7_root.rglob("*.json")):
            stem = stage7_path.stem
            manifest = manifest_by_stem.get(stem, {})
            rec = _model_input_from_stage7_file(
                stage7_path=stage7_path,
                pattern_data=pattern_data,
                manifest=manifest,
                default_window_seconds=default_window_seconds,
                desc_module=desc_module,
            )
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    return count


def _load_script_module(name_hint: str, script_rel_path: str) -> ModuleType:
    script_path = (PROJECT_ROOT / script_rel_path).resolve()
    if not script_path.exists():
        raise RuntimeError(f"Missing stage script: {script_path}")

    module_name = f"realtime_{name_hint}_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load script module: {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_live_stage_configs(
    *,
    offline_config: Path,
    candidate_root: Path,
    csv_raw_root: Path,
) -> Dict[str, Dict[str, Any]]:
    cfg = json.loads(offline_config.read_text(encoding="utf-8"))
    cfg_vars = {str(k): str(v) for k, v in (cfg.get("variables") or {}).items()}
    merged_vars: Dict[str, str] = {
        **cfg_vars,
        **candidate_root_overrides(candidate_root),
        "csv_raw_root": str(csv_raw_root),
        "PROJECT_ROOT": str(PROJECT_ROOT),
    }
    resolved_cfg = resolve_placeholders(cfg, merged_vars)
    stages = resolved_cfg.get("stages")
    if not isinstance(stages, dict):
        raise RuntimeError(f"Invalid offline config (missing stages): {offline_config}")
    return stages


def _build_inprocess_stage7_pipeline(
    *,
    offline_config: Path,
    candidate_root: Path,
    csv_raw_root: Path,
    gender: str = "female",
    step_type: str = "krok_podstawowy",
) -> Callable[[Path], tuple[Path, Dict[str, float]]]:
    scripts_dir = (PROJECT_ROOT / "scripts").resolve()
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    stages = _resolve_live_stage_configs(
        offline_config=offline_config,
        candidate_root=candidate_root,
        csv_raw_root=csv_raw_root,
    )
    required = ("calculate_angles", "normalize", "downsample", "segment_bounds", "arms_metrics")
    missing = [name for name in required if name not in stages]
    if missing:
        raise RuntimeError(f"Offline config is missing required stages: {', '.join(missing)}")

    for name in required:
        if not bool(stages[name].get("enabled", True)):
            raise RuntimeError(f"Required stage is disabled in config: {name}")

    stage0_cfg = stages["calculate_angles"]
    stage1_cfg = stages["normalize"]
    stage2_cfg = stages["downsample"]
    stage4_cfg = stages["segment_bounds"]
    stage7_cfg = stages["arms_metrics"]

    stage0_mod = _load_script_module("stage0", str(stage0_cfg["script"]))
    stage1_mod = _load_script_module("stage1", str(stage1_cfg["script"]))
    stage2_mod = _load_script_module("stage2", str(stage2_cfg["script"]))
    stage4_mod = _load_script_module("stage4", str(stage4_cfg["script"]))
    stage7_mod = _load_script_module("stage7", str(stage7_cfg["script"]))

    stage1_args = dict(stage1_cfg.get("args") or {})
    window_raw = stage1_args.get("window", [0, 50])
    if not isinstance(window_raw, list) or len(window_raw) != 2:
        raise RuntimeError(f"Invalid normalize.window in config: {window_raw!r}")
    norm_cfg = stage1_mod.NormConfig(
        window=(int(window_raw[0]), int(window_raw[1])),
        target_pelvis=float(stage1_args.get("target-pelvis", 1.0)),
        unit_label=str(stage1_args.get("unit-label", "norm")),
        skip_markers=("CentreOfMass", "CentreOfMassFloor"),
        force_keep=(),
    )

    stage2_args = dict(stage2_cfg.get("args") or {})
    target_fps = float(stage2_args.get("target-fps", 50.0))
    src_fps_opt = stage2_args.get("src-fps")
    src_fps = float(src_fps_opt) if src_fps_opt is not None else None
    cutoff = float(stage2_args.get("cutoff", 8.0))
    order = int(stage2_args.get("order", 4))

    stage4_args = dict(stage4_cfg.get("args") or {})
    stage4_fs = float(stage4_args.get("fs", 50.0))
    stage4_write_plot = not bool(stage4_args.get("skip-plots", False))
    stage4_plot_root_raw = stage4_args.get("out-root", str(candidate_root / "plots" / "4segmentation_step_bounds"))
    stage4_plot_root = Path(str(stage4_plot_root_raw))
    if not stage4_plot_root.is_absolute():
        stage4_plot_root = (PROJECT_ROOT / stage4_plot_root).resolve()

    stage7_args = dict(stage7_cfg.get("args") or {})
    stage7_fs = float(stage7_args.get("fs", 50.0))

    calc_root = candidate_root / "csv" / "calculated"
    norm_root = candidate_root / "csv" / "normalized"
    down_root = candidate_root / "csv" / "downsampled"
    seg4_root = candidate_root / "json" / "4_segmentation_bounds"
    seg7_root = candidate_root / "json" / "7_arms_position"
    roots = [calc_root, norm_root, down_root, seg4_root, seg7_root]
    if stage4_write_plot:
        roots.append(stage4_plot_root)
    for p in roots:
        p.mkdir(parents=True, exist_ok=True)

    raw_base = csv_raw_root.resolve()

    def _run_stage_quiet(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[float, str]:
        captured = io.StringIO()
        t0 = time.monotonic()
        with redirect_stdout(captured), redirect_stderr(captured):
            fn(*args, **kwargs)
        return time.monotonic() - t0, captured.getvalue()

    def process_window(csv_path: Path) -> tuple[Path, Dict[str, float]]:
        csv_abs = csv_path.resolve()
        rel = csv_abs.relative_to(raw_base)
        calc_csv = calc_root / rel
        norm_csv = norm_root / rel
        down_csv = down_root / rel
        seg4_json = seg4_root / rel.with_suffix(".json")
        seg7_json = seg7_root / rel.with_suffix(".json")
        seg4_png = stage4_plot_root / rel.with_suffix(".png")

        stage_times: Dict[str, float] = {}

        dt, logs = _run_stage_quiet("calculate_angles", stage0_mod.process_file, csv_abs, calc_root, raw_base)
        stage_times["calculate_angles"] = dt
        if not calc_csv.exists():
            raise RuntimeError(f"Stage calculate_angles did not create output: {calc_csv}\n{_tail(logs)}")

        dt, logs = _run_stage_quiet("normalize", stage1_mod.process_file, calc_csv, norm_csv, norm_cfg)
        stage_times["normalize"] = dt
        if not norm_csv.exists():
            raise RuntimeError(f"Stage normalize did not create output: {norm_csv}\n{_tail(logs)}")

        dt, logs = _run_stage_quiet(
            "downsample",
            stage2_mod.process_one,
            norm_csv,
            norm_root,
            down_root,
            target_fps,
            src_fps,
            cutoff,
            order,
        )
        stage_times["downsample"] = dt
        if not down_csv.exists():
            raise RuntimeError(f"Stage downsample did not create output: {down_csv}\n{_tail(logs)}")

        dt, logs = _run_stage_quiet(
            "segment_bounds",
            stage4_mod.process_file,
            down_csv,
            seg4_png if stage4_write_plot else None,
            stage4_fs,
            write_plot=stage4_write_plot,
            in_root=down_root,
            json_root=seg4_root,
            gender=gender,
            step_type=step_type,
        )
        stage_times["segment_bounds"] = dt
        if not seg4_json.exists():
            raise RuntimeError(f"Stage segment_bounds did not create output: {seg4_json}\n{_tail(logs)}")

        dt, logs = _run_stage_quiet(
            "arms_metrics",
            stage7_mod.process_file,
            down_csv,
            down_root,
            seg4_root,
            seg7_root,
            stage7_fs,
        )
        stage_times["arms_metrics"] = dt
        if not seg7_json.exists():
            raise RuntimeError(f"Stage arms_metrics did not create output: {seg7_json}\n{_tail(logs)}")

        return seg7_json, stage_times

    return process_window


def main() -> int:
    ap = argparse.ArgumentParser(description="End-to-end UDP -> offline stages -> prompt generation test.")
    ap.add_argument("--udp-host", default="0.0.0.0", help="Bind host for UDP receive")
    ap.add_argument("--udp-port", type=int, default=5005, help="Bind UDP port")
    ap.add_argument("--input-hz", type=float, default=100.0, help="Expected stream Hz")
    ap.add_argument("--window-seconds", type=float, default=4.0, help="Window length in seconds")
    ap.add_argument("--stride-seconds", type=float, default=3.0, help="Window stride in seconds")
    ap.add_argument("--duration-seconds", type=float, default=20.0, help="Capture duration; <=0 means infinite")
    ap.add_argument("--max-packets", type=int, default=0, help="Optional packet cap (0=disabled)")
    ap.add_argument(
        "--gender",
        default="female",
        choices=["female", "male"],
        help="Płeć tancerza — wpływa na detekcję ukłonów i kroków w etapie 4 (domyślnie: female)",
    )
    ap.add_argument(
        "--step-type",
        default="step",
        choices=["step", "static"],
        help="Typ ruchu: 'step' (kroki/polonez) lub 'static' (obroty w miejscu). Domyślnie: step",
    )
    ap.add_argument("--max-windows", type=int, default=0, help="Optional window cap (0=disabled)")
    ap.add_argument("--socket-timeout-ms", type=int, default=200, help="UDP socket timeout ms")
    ap.add_argument("--sequence-name", default="udp_sequence", help="Subfolder name for captured raw windows")
    ap.add_argument(
        "--llm-url",
        default=None,
        help="Base URL of the LLM server (e.g. http://localhost:8000). "
             "If set, each model input is sent to POST /generate and feedback saved to feedback.jsonl.",
    )
    ap.add_argument(
        "--pattern-file",
        type=Path,
        required=True,
        help="Path to enriched *_pattern.json used for window prompt records",
    )
    ap.add_argument(
        "--offline-config",
        type=Path,
        default=PROJECT_ROOT / "bin/offline_pipeline.realtime.config.json",
        help="Offline pipeline config JSON used by bin/run_offline_pipeline.py",
    )
    ap.add_argument(
        "--model-inputs-only",
        action="store_true",
        help="Generate only final model payloads (instruction+input). In this mode windows are processed live.",
    )
    ap.add_argument(
        "--live-z-threshold",
        type=float,
        default=LIVE_DESC_Z_THRESHOLD,
        help="Z-score threshold for live description generation (higher = fewer issues).",
    )
    ap.add_argument(
        "--live-major-order-threshold",
        type=int,
        default=LIVE_MAJOR_ORDER_THRESHOLD,
        help="Order score threshold below which 'out of order' text is emitted in live mode.",
    )
    ap.add_argument(
        "--live-emit-minor-order-text",
        action="store_true",
        default=LIVE_EMIT_MINOR_ORDER_TEXT,
        help="Emit 'minor deviations' order text in live mode.",
    )
    ap.add_argument(
        "--model-inputs-path",
        type=Path,
        default=None,
        help="Output JSONL path for model payloads in --model-inputs-only mode.",
    )
    ap.add_argument(
        "--live-queue-maxsize",
        type=int,
        default=0,
        help="Queue size for live window processing (0 = unbounded).",
    )
    ap.add_argument(
        "--live-workers",
        type=int,
        default=1,
        help="Number of parallel workers for live per-window processing.",
    )
    ap.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/tmp/realtime_e2e",
        help="Root folder for test artifacts",
    )
    ap.add_argument("--run-id", default=None, help="Custom run id; default timestamp")
    args = ap.parse_args()

    run_id = args.run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_root = args.output_root / run_id
    capture_root = run_root / "capture"
    raw_root = capture_root / "raw" / args.sequence_name
    manifest_path = capture_root / "windows_manifest.jsonl"

    candidate_root = run_root / "pipeline"

    prompt_windows_root = run_root / "prompts" / "window_records"
    prompt_desc_root = run_root / "prompts" / "descriptive"
    prompt_9_2_index_path = run_root / "prompts" / "prompts_9_2_index.jsonl"
    training_prompts_10_2_root = run_root / "prompts" / "training_prompts_10_2"
    prompt_10_2_index_path = run_root / "prompts" / "prompts_10_2_index.jsonl"

    pattern_file = args.pattern_file if args.pattern_file.is_absolute() else (PROJECT_ROOT / args.pattern_file)
    pattern_file = pattern_file.resolve()
    pattern_name = pattern_file.stem.replace("_pattern", "")

    offline_config = args.offline_config if args.offline_config.is_absolute() else (PROJECT_ROOT / args.offline_config)
    offline_config = offline_config.resolve()

    model_inputs_path = args.model_inputs_path
    if args.model_inputs_only:
        if model_inputs_path is None:
            model_inputs_path = run_root / "model_inputs.jsonl"
        elif not model_inputs_path.is_absolute():
            model_inputs_path = (PROJECT_ROOT / model_inputs_path).resolve()

    dirs_to_make = [raw_root]
    analysis_stage7_root = run_root / "analysis" / "stage7"
    analysis_window_records_root = run_root / "analysis" / "window_records" / pattern_name / "windows"
    if args.model_inputs_only:
        assert model_inputs_path is not None
        dirs_to_make.append(model_inputs_path.parent)
        dirs_to_make.extend([analysis_stage7_root, analysis_window_records_root])
    else:
        dirs_to_make.extend([prompt_windows_root, prompt_desc_root])

    for p in dirs_to_make:
        p.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] E2E run root: {run_root}")
    print(f"[INFO] Capture UDP on {args.udp_host}:{args.udp_port}")

    engine = RealtimeWindowEngine(
        input_hz=args.input_hz,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
    )

    # Live model-input worker state
    jobs_queue: queue.Queue[Optional[Dict[str, Any]]] | None = None
    worker_threads: list[threading.Thread] = []
    live_state_lock = threading.Lock()
    output_lock = threading.Lock()
    live_queue_peak = 0
    live_workers = 0
    live_state: Dict[str, Any] = {
        "processed": 0,
        "failed": 0,
        "processing_s": [],
        "latency_s": [],
        "stage_sums": {},
        "stage_max": {},
        "errors": [],
    }

    if args.model_inputs_only:
        assert model_inputs_path is not None
        model_inputs_path.write_text("", encoding="utf-8")

        # feedback JSONL — alongside model_inputs, only when --llm-url is provided
        feedback_path: Optional[Path] = None
        if args.llm_url:
            feedback_path = model_inputs_path.parent / "feedback.jsonl"
            feedback_path.write_text("", encoding="utf-8")
            print(f"[INFO] LLM server: {args.llm_url}  |  feedback -> {feedback_path}")

        queue_size = args.live_queue_maxsize if args.live_queue_maxsize > 0 else 0
        jobs_queue = queue.Queue(maxsize=queue_size)
        pattern_data = load_enriched_pattern(pattern_file)
        desc_module = _load_desc_generator_module()

        live_workers = max(1, int(args.live_workers))

        def _worker(worker_id: int) -> None:
            nonlocal live_queue_peak
            assert jobs_queue is not None
            stage7_pipeline = _build_inprocess_stage7_pipeline(
                offline_config=offline_config,
                candidate_root=candidate_root,
                csv_raw_root=raw_root.parent,
                gender=args.gender,
                step_type=args.step_type,
            )
            while True:
                job = jobs_queue.get()
                if job is None:
                    jobs_queue.task_done()
                    break

                t0 = time.monotonic()
                stem = str(job["stem"])
                manifest = dict(job["manifest"])
                src_csv = Path(str(job["csv_path"]))
                enq_t = float(job["enqueued_at"])

                try:
                    stage7_path, stage_timings = stage7_pipeline(src_csv)

                    stage7_data, window_record, rec = _window_bundle_from_stage7_file(
                        stage7_path=stage7_path,
                        pattern_data=pattern_data,
                        manifest=manifest,
                        default_window_seconds=args.window_seconds,
                        desc_module=desc_module,
                        z_threshold=float(args.live_z_threshold),
                        major_order_threshold=int(args.live_major_order_threshold),
                        emit_minor_order_text=bool(args.live_emit_minor_order_text),
                    )
                    analysis_stage7_path = analysis_stage7_root / f"{stem}.json"
                    analysis_window_path = analysis_window_records_root / f"{stem}.json"
                    analysis_stage7_path.write_text(
                        json.dumps(stage7_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    analysis_window_path.write_text(
                        json.dumps(window_record, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    with output_lock:
                        with model_inputs_path.open("a", encoding="utf-8") as out_f:
                            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

                    # optional: call LLM server and save feedback
                    if args.llm_url and feedback_path is not None:
                        fb = _call_llm_server(args.llm_url, rec)
                        if fb is not None:
                            fb_rec = {
                                "window_index": manifest.get("window_index"),
                                "start_s": manifest.get("start_s"),
                                "end_s": manifest.get("end_s"),
                                "instruction": rec.get("instruction", ""),
                                "input": rec.get("input", ""),
                                **fb,
                            }
                            with output_lock:
                                with feedback_path.open("a", encoding="utf-8") as fb_f:
                                    fb_f.write(json.dumps(fb_rec, ensure_ascii=False) + "\n")
                            print(
                                f"[FEEDBACK] {fb.get('feedback', '')} "
                                f"(score={fb.get('score')}, {fb.get('latency_s')}s)"
                            )

                    t1 = time.monotonic()
                    proc_s = t1 - t0
                    latency_s = t1 - enq_t
                    with live_state_lock:
                        live_state["processed"] += 1
                        live_state["processing_s"].append(proc_s)
                        live_state["latency_s"].append(latency_s)
                        stage_sums = live_state["stage_sums"]
                        stage_max = live_state["stage_max"]
                        for name, value in stage_timings.items():
                            stage_sums[name] = float(stage_sums.get(name, 0.0)) + float(value)
                            stage_max[name] = max(float(stage_max.get(name, 0.0)), float(value))

                    q_now = jobs_queue.qsize()
                    with live_state_lock:
                        live_queue_peak = max(live_queue_peak, q_now)

                    stage_msg = (
                        f"ca={stage_timings.get('calculate_angles', 0.0):.3f}s "
                        f"n={stage_timings.get('normalize', 0.0):.3f}s "
                        f"d={stage_timings.get('downsample', 0.0):.3f}s "
                        f"s={stage_timings.get('segment_bounds', 0.0):.3f}s "
                        f"a={stage_timings.get('arms_metrics', 0.0):.3f}s"
                    )
                    print(
                        f"[LIVE] worker={worker_id} stem={stem} proc={proc_s:.3f}s latency={latency_s:.3f}s "
                        f"queue={q_now} {stage_msg}"
                    )
                except Exception as exc:
                    with live_state_lock:
                        live_state["failed"] += 1
                        live_state["errors"].append({"stem": stem, "error": str(exc)})
                    print(f"[ERR ] worker={worker_id} stem={stem} {exc}")
                finally:
                    jobs_queue.task_done()

        for wid in range(live_workers):
            th = threading.Thread(target=_worker, args=(wid,), name=f"model-inputs-worker-{wid}", daemon=True)
            worker_threads.append(th)
            th.start()
    windows_written = 0
    stop_after_windows = args.max_windows if args.max_windows > 0 else None

    def on_window(window, stats):
        nonlocal windows_written, live_queue_peak
        stem = f"{args.sequence_name}_{window.window_index:05d}"
        out_csv = raw_root / f"{stem}.csv"
        write_window_as_vicon_csv(window, out_csv, sample_rate_hz=args.input_hz)

        manifest = {
            "file_stem": stem,
            "window_index": window.window_index,
            "start_s": window.start_s,
            "end_s": window.end_s,
            "first_frame": window.first_frame_number,
            "last_frame": window.last_frame_number,
            "frame_count": window.frame_count,
            "marker_count_first_frame": window.frames[0].marker_count if window.frames else 0,
        }
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(manifest, ensure_ascii=False) + "\n")

        windows_written += 1

        if args.model_inputs_only and jobs_queue is not None:
            jobs_queue.put(
                {
                    "stem": stem,
                    "csv_path": str(out_csv),
                    "manifest": manifest,
                    "enqueued_at": time.monotonic(),
                }
            )
            q_now = jobs_queue.qsize()
            with live_state_lock:
                live_queue_peak = max(live_queue_peak, q_now)

            print(
                f"[WIN ] idx={window.window_index} frames={window.frame_count} file={out_csv.name} "
                f"queued={q_now} missing_total={stats.missing_frames}"
            )
        else:
            print(
                f"[WIN ] idx={window.window_index} frames={window.frame_count} "
                f"file={out_csv.name} missing_total={stats.missing_frames}"
            )

        if stop_after_windows is not None and windows_written >= stop_after_windows:
            raise KeyboardInterrupt

    duration_seconds: Optional[float] = args.duration_seconds if args.duration_seconds > 0 else None
    max_packets: Optional[int] = args.max_packets if args.max_packets > 0 else None

    try:
        stats = run_udp_window_loop(
            host=args.udp_host,
            port=args.udp_port,
            engine=engine,
            duration_seconds=duration_seconds,
            max_packets=max_packets,
            socket_timeout_ms=args.socket_timeout_ms,
            on_window=on_window,
            on_packet_error=lambda exc, no: print(f"[WARN] Malformed packet #{no}: {exc}"),
        )
    except KeyboardInterrupt:
        stats = engine.stats
        print("[STOP] Capture interrupted (window cap or user stop).")

    print(f"[INFO] Capture done. windows_written={windows_written} packets={stats.packets_received}")

    if args.model_inputs_only:
        assert jobs_queue is not None
        assert worker_threads

        for _ in worker_threads:
            jobs_queue.put(None)
        jobs_queue.join()
        for th in worker_threads:
            th.join(timeout=5.0)

        with live_state_lock:
            proc_vals = list(live_state["processing_s"])
            lat_vals = list(live_state["latency_s"])
            processed = int(live_state["processed"])
            failed = int(live_state["failed"])
            errors = list(live_state["errors"])
            stage_sums = dict(live_state["stage_sums"])
            stage_max = dict(live_state["stage_max"])
            queue_peak = int(live_queue_peak)

        stage_avg = {
            name: (float(total) / processed if processed > 0 else None)
            for name, total in stage_sums.items()
        }

        summary = {
            "run_root": str(run_root.resolve()),
            "mode": "live_model_inputs_inprocess_strict",
            "windows_written": windows_written,
            "windows_processed": processed,
            "windows_failed": failed,
            "live_workers": int(live_workers),
            "live_queue_peak": queue_peak,
            "live_z_threshold": float(args.live_z_threshold),
            "live_major_order_threshold": int(args.live_major_order_threshold),
            "live_emit_minor_order_text": bool(args.live_emit_minor_order_text),
            "model_inputs_path": str(model_inputs_path.resolve()) if model_inputs_path else None,
            "llm_url": args.llm_url,
            "feedback_path": str(feedback_path.resolve()) if (args.llm_url and feedback_path is not None) else None,
            "pipeline_root": str(candidate_root.resolve()),
            "processing_seconds_avg": (sum(proc_vals) / len(proc_vals)) if proc_vals else None,
            "processing_seconds_max": max(proc_vals) if proc_vals else None,
            "latency_seconds_avg": (sum(lat_vals) / len(lat_vals)) if lat_vals else None,
            "latency_seconds_max": max(lat_vals) if lat_vals else None,
            "stage_seconds_avg": stage_avg,
            "stage_seconds_max": stage_max,
            "errors": errors,
            "stream_stats": stats.as_dict(),
        }
        summary_path = run_root / "run_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[DONE] E2E summary: {summary_path}")
        print(f"[DONE] Model inputs: {model_inputs_path}")
        return 0

    if windows_written == 0:
        print("[WARN] No windows captured; skipping offline + prompts pipeline.")
        return 0

    offline_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "bin/run_offline_pipeline.py"),
        "--config",
        str(offline_config),
        "--candidate-root",
        str(candidate_root),
        "--var",
        f"csv_raw_root={raw_root.parent}",
        "--only",
        "calculate_angles",
        "normalize",
        "downsample",
        "segment_bounds",
        "arms_metrics",
        "--log-dir",
        str(run_root / "offline_runs"),
    ]
    _run_subprocess(offline_cmd, PROJECT_ROOT)

    stage7_root = candidate_root / "json" / "7_arms_position"
    if not stage7_root.exists():
        raise RuntimeError(f"Missing stage7 output: {stage7_root}")

    manifest_by_stem = _load_manifest_by_stem(manifest_path)

    out_windows_dir = prompt_windows_root / pattern_name / "windows"
    built = build_window_records_from_stage7(
        stage7_root=stage7_root,
        pattern_file=pattern_file,
        manifest_by_stem=manifest_by_stem,
        out_windows_dir=out_windows_dir,
    )
    print(f"[INFO] Built window prompt-record JSONs: {built}")

    desc_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/generate_feedback_descriptions.py"),
        "--in_dir",
        str(prompt_windows_root),
        "--out_dir",
        str(prompt_desc_root),
    ]
    _run_subprocess(desc_cmd, PROJECT_ROOT)

    prompts_9_2_count = _write_prompt_index(prompt_desc_root, prompt_9_2_index_path)

    prompts_10_2_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts/10_2descriptive_training_prompts.py"),
        "--desc_root",
        str(prompt_desc_root),
        "--out_root",
        str(training_prompts_10_2_root),
        "--train_ratio",
        "1.0",
        "--val_ratio",
        "0.0",
    ]
    _run_subprocess(prompts_10_2_cmd, PROJECT_ROOT)
    prompts_10_2_count = _write_instruction_index(training_prompts_10_2_root, prompt_10_2_index_path)

    summary = {
        "run_root": str(run_root.resolve()),
        "mode": "batch_prompts",
        "windows_written": windows_written,
        "pipeline_root": str(candidate_root.resolve()),
        "window_records_root": str(prompt_windows_root.resolve()),
        "prompt_descriptive_root": str(prompt_desc_root.resolve()),
        "prompts_9_2_index": str(prompt_9_2_index_path.resolve()),
        "prompts_9_2_count": prompts_9_2_count,
        "prompts_10_2_root": str(training_prompts_10_2_root.resolve()),
        "prompts_10_2_index": str(prompt_10_2_index_path.resolve()),
        "prompts_10_2_count": prompts_10_2_count,
        "stream_stats": stats.as_dict(),
    }
    summary_path = run_root / "run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] E2E summary: {summary_path}")
    print(f"[DONE] Prompts 9_2 index: {prompt_9_2_index_path}")
    print(f"[DONE] Prompts 10_2 index: {prompt_10_2_index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
