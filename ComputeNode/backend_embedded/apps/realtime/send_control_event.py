#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any


def _load_json_path(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("JSON payload file must contain object.")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Send one JSON control event to realtime control UDP channel.")
    ap.add_argument("--host", required=True, help="Destination host")
    ap.add_argument("--port", type=int, default=5006, help="Destination control port")

    ap.add_argument("--type", default="session_start", help="Event type")
    ap.add_argument("--session-id", default="S1")
    ap.add_argument("--dance-id", default="k_krok_podstawowy_polonez")
    ap.add_argument("--gender", choices=["female", "male"], default="female")
    ap.add_argument("--step-type", choices=["step", "static"], default="step")
    ap.add_argument("--sequence-name", default="udp_sequence")
    ap.add_argument("--pattern-file", default="")
    ap.add_argument("--run-id", default="")

    ap.add_argument("--from-json", type=Path, default=None, help="Optional JSON file with full payload")
    args = ap.parse_args()

    if args.from_json is not None:
        payload = _load_json_path(args.from_json)
    else:
        payload = {
            "type": args.type,
            "session_id": args.session_id,
            "dance_id": args.dance_id,
            "gender": args.gender,
            "step_type": args.step_type,
            "sequence_name": args.sequence_name,
        }
        if args.pattern_file:
            payload["pattern_file"] = args.pattern_file
        if args.run_id:
            payload["run_id"] = args.run_id

    raw = json.dumps(payload, ensure_ascii=False)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(raw.encode("utf-8"), (args.host, args.port))
    finally:
        sock.close()

    print(f"[DONE] sent to {args.host}:{args.port} -> {raw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
