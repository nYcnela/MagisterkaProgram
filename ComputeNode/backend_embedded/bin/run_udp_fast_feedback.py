#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pipeline_core.realtime.engine import RealtimeWindowEngine
from pipeline_core.realtime.fast_feedback import build_model_input_fast, load_pattern_step_refs
from pipeline_core.realtime.udp_receiver import run_udp_window_loop
from pipeline_core.realtime.window_csv import write_window_as_vicon_csv


def main() -> int:
    ap = argparse.ArgumentParser(description="Fast realtime UDP -> model-inputs (in-memory, no offline subprocesses).")
    ap.add_argument("--udp-host", default="0.0.0.0", help="Bind host for UDP receive")
    ap.add_argument("--udp-port", type=int, default=5005, help="Bind UDP port")
    ap.add_argument("--input-hz", type=float, default=100.0, help="Expected stream Hz")
    ap.add_argument("--window-seconds", type=float, default=4.0, help="Window length in seconds")
    ap.add_argument("--stride-seconds", type=float, default=3.0, help="Window stride in seconds")
    ap.add_argument("--duration-seconds", type=float, default=0.0, help="Capture duration; <=0 means infinite")
    ap.add_argument("--max-packets", type=int, default=0, help="Optional packet cap (0=disabled)")
    ap.add_argument("--max-windows", type=int, default=0, help="Optional window cap (0=disabled)")
    ap.add_argument("--socket-timeout-ms", type=int, default=200, help="UDP socket timeout ms")
    ap.add_argument("--sequence-name", default="udp_sequence", help="Subfolder name for captured raw windows")
    ap.add_argument(
        "--pattern-file",
        type=Path,
        required=True,
        help="Path to enriched *_pattern.json used as reference",
    )
    ap.add_argument("--z-threshold", type=float, default=1.0, help="Absolute z-score threshold for feedback sentence")
    ap.add_argument("--max-sentences", type=int, default=2, help="Max number of observation sentences in input")
    ap.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "data/tmp/realtime_fast",
        help="Root folder for test artifacts",
    )
    ap.add_argument(
        "--save-raw-csv",
        action="store_true",
        help="Store raw per-window CSV in run folder (debug).",
    )
    ap.add_argument(
        "--save-debug-jsonl",
        action="store_true",
        help="Store per-window debug metrics JSONL.",
    )
    ap.add_argument("--run-id", default=None, help="Custom run id; default timestamp")
    args = ap.parse_args()

    run_id = args.run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_root = args.output_root / run_id
    capture_root = run_root / "capture"
    raw_root = capture_root / "raw" / args.sequence_name
    manifest_path = capture_root / "windows_manifest.jsonl"
    model_inputs_path = run_root / "model_inputs.jsonl"
    debug_jsonl_path = run_root / "debug_windows.jsonl"

    run_root.mkdir(parents=True, exist_ok=True)
    capture_root.mkdir(parents=True, exist_ok=True)
    if args.save_raw_csv:
        raw_root.mkdir(parents=True, exist_ok=True)

    model_inputs_path.write_text("", encoding="utf-8")
    if args.save_debug_jsonl:
        debug_jsonl_path.write_text("", encoding="utf-8")

    pattern_file = args.pattern_file if args.pattern_file.is_absolute() else (PROJECT_ROOT / args.pattern_file)
    pattern_file = pattern_file.resolve()
    refs = load_pattern_step_refs(pattern_file)

    print(f"[INFO] Fast realtime run root: {run_root}")
    print(f"[INFO] Capture UDP on {args.udp_host}:{args.udp_port}")

    engine = RealtimeWindowEngine(
        input_hz=args.input_hz,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
    )

    processing_s: list[float] = []
    windows_written = 0
    stop_after_windows = args.max_windows if args.max_windows > 0 else None

    def on_window(window, stats):
        nonlocal windows_written
        stem = f"{args.sequence_name}_{window.window_index:05d}"

        if args.save_raw_csv:
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

        t0 = time.monotonic()
        rec, dbg = build_model_input_fast(
            window=window,
            refs=refs,
            input_hz=args.input_hz,
            z_threshold=args.z_threshold,
            max_sentences=max(1, args.max_sentences),
        )
        dt = time.monotonic() - t0
        processing_s.append(dt)

        with model_inputs_path.open("a", encoding="utf-8") as out_f:
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        if args.save_debug_jsonl:
            dbg_rec = {
                "window_index": int(window.window_index),
                "start_s": float(window.start_s),
                "end_s": float(window.end_s),
                "processing_s": float(dt),
                **dbg,
            }
            with debug_jsonl_path.open("a", encoding="utf-8") as dbg_f:
                dbg_f.write(json.dumps(dbg_rec, ensure_ascii=False) + "\n")

        windows_written += 1
        print(
            f"[FAST] idx={window.window_index} frames={window.frame_count} "
            f"proc={dt:.4f}s missing_total={stats.missing_frames}"
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

    summary = {
        "run_root": str(run_root.resolve()),
        "mode": "fast_in_memory",
        "windows_written": windows_written,
        "model_inputs_path": str(model_inputs_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "debug_jsonl_path": str(debug_jsonl_path.resolve()) if args.save_debug_jsonl else None,
        "processing_seconds_avg": (sum(processing_s) / len(processing_s)) if processing_s else None,
        "processing_seconds_max": max(processing_s) if processing_s else None,
        "stream_stats": stats.as_dict(),
    }
    summary_path = run_root / "run_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] Summary: {summary_path}")
    print(f"[DONE] Model inputs: {model_inputs_path}")
    if processing_s:
        print(
            f"[DONE] Processing time per window: avg={sum(processing_s)/len(processing_s):.4f}s "
            f"max={max(processing_s):.4f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
