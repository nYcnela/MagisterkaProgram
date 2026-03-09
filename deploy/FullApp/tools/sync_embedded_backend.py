#!/usr/bin/env python3
"""Sync embedded backend from source project into realtime_studio/backend_embedded."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend_embedded"

FILES_TO_COPY = [
    "apps/realtime/run_udp_e2e_test.py",
    "apps/realtime/llm_server.py",
    "apps/realtime/offline_pipeline.realtime.config.json",
    "apps/realtime/run_udp_controlled_session.py",
    "apps/realtime/send_control_event.py",
    "apps/realtime/replay_csv_over_udp.py",
    "apps/realtime/run_udp_fast_feedback.py",
    "apps/realtime/send_model_inputs_to_llm.py",
    "Scripts/0calculate_angles_v3.py",
    "Scripts/1fast_normalize.py",
    "Scripts/2filter_and_downsample_w_angles.py",
    "Scripts/4segmentation_bounds_w_head.py",
    "Scripts/7arms_position_recognition_w_json.py",
    "models/model_v12.0/9_2generate_descriptive_training_data.py",
]

DIRS_TO_COPY = [
    "src/pipeline_core",
    "Scripts/utils",
    "data/json/manual/pipeline/8_patterns/enriched",
]

ADAPTER_REL = "outputs/manual/danube_4b/model_danube_supervised/lora_adapter"


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync backend into backend_embedded.")
    ap.add_argument("--source-root", type=Path, required=True, help="Source project root (e.g. e:\\Python_projects)")
    ap.add_argument("--clean", action="store_true", help="Remove backend_embedded before sync")
    args = ap.parse_args()

    source: Path = args.source_root.resolve()
    target: Path = BACKEND_DIR

    if not source.is_dir():
        raise FileNotFoundError(f"Source root not found: {source}")

    if args.clean and target.exists():
        shutil.rmtree(target)

    target.mkdir(parents=True, exist_ok=True)

    files_copied = 0
    for rel in FILES_TO_COPY:
        src = source / rel
        dst = target / rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            files_copied += 1
        else:
            print(f"[warn] missing: {src}")

    dirs_copied = 0
    for rel in DIRS_TO_COPY:
        src = source / rel
        dst = target / rel
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            dirs_copied += 1
            files_copied += sum(1 for _ in dst.rglob("*") if _.is_file())
        else:
            print(f"[warn] missing dir: {src}")

    adapter_src = source / ADAPTER_REL
    adapter_dst = target / ADAPTER_REL
    adapter_ok = False
    if adapter_src.is_dir():
        if adapter_dst.exists():
            shutil.rmtree(adapter_dst)
        shutil.copytree(adapter_src, adapter_dst)
        adapter_ok = True
        files_copied += sum(1 for _ in adapter_dst.rglob("*") if _.is_file())
    else:
        print(f"[warn] adapter not found: {adapter_src}")

    manifest = {
        "source_root": str(source),
        "target_root": str(target),
        "files_to_copy": FILES_TO_COPY,
        "dirs_to_copy": DIRS_TO_COPY,
        "adapter_rel": ADAPTER_REL,
        "adapter_copied": adapter_ok,
        "copied_files_count": files_copied,
        "copied_dirs_count": dirs_copied,
    }
    manifest_path = target / ".embedded_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[OK] Embedded backend refreshed: {target}")
    print(f"[OK] Copied files: {files_copied}, directories: {dirs_copied}")
    print(f"[OK] Adapter copied: {adapter_ok} ({ADAPTER_REL})")


if __name__ == "__main__":
    main()
