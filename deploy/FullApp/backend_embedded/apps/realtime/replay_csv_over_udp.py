#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import struct
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


DEFAULT_MARKER_NAMES: tuple[str, ...] = (
    "LFHD",
    "RFHD",
    "LBHD",
    "RBHD",
    "C7",
    "T10",
    "CLAV",
    "STRN",
    "RBAK",
    "LSHO",
    "LUPA",
    "LELB",
    "LFRM",
    "LWRA",
    "LWRB",
    "LFIN",
    "RSHO",
    "RUPA",
    "RELB",
    "RFRM",
    "RWRA",
    "RWRB",
    "RFIN",
    "LASI",
    "RASI",
    "LPSI",
    "RPSI",
    "LTHI",
    "LKNE",
    "LTIB",
    "LANK",
    "LHEE",
    "LTOE",
    "RTHI",
    "RKNE",
    "RTIB",
    "RANK",
    "RHEE",
    "RTOE",
)

HEADER_STRUCT = struct.Struct("<IH")
MARKER_STRUCT = struct.Struct("<Hddd")


def detect_delimiter(lines: List[str]) -> str:
    for ln in lines[:200]:
        if "Frame;Sub Frame" in ln:
            return ";"
        if "Frame,Sub Frame" in ln:
            return ","
    return ";" if any(";" in ln for ln in lines[:50]) else ","


def find_trajectories_section(lines: List[str]) -> int:
    for i, line in enumerate(lines):
        if line.strip().startswith("Trajectories"):
            return i
    raise ValueError("Could not find 'Trajectories' section in CSV.")


def parse_marker_names(marker_line: str, delim: str) -> List[str]:
    parts = marker_line.rstrip("\n").split(delim)[2:]
    names: List[str] = []
    n_triplets = len(parts) // 3
    for i in range(n_triplets):
        name = (parts[3 * i] or "").strip()
        if ":" in name:
            name = name.rsplit(":", 1)[1].strip()
        names.append(name)

    # CSV often ends marker line with trailing ';;;', which becomes an empty pseudo-marker.
    while names and names[-1] == "":
        names.pop()
    return names


def parse_float_token(tok: str) -> float:
    tok = tok.strip()
    if tok == "":
        return float("nan")
    return float(tok)


def load_trajectories_csv(path: Path) -> Tuple[int, List[str], List[List[float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    delim = detect_delimiter(lines)
    start = find_trajectories_section(lines)

    fps_raw = lines[start + 1].split(delim)[0].strip()
    fps = int(float(fps_raw))
    marker_names = parse_marker_names(lines[start + 2], delim)
    data_start = start + 5

    rows: List[List[float]] = []
    for ln in lines[data_start:]:
        if not ln.strip():
            break
        parts = ln.split(delim)
        if len(parts) < 2 + 3 * len(marker_names):
            break
        rows.append([parse_float_token(p) for p in parts[: 2 + 3 * len(marker_names)]])

    if not rows:
        raise ValueError(f"No trajectory rows parsed from {path}")
    return fps, marker_names, rows


def build_packet(frame_number: int, marker_triplets: Sequence[Tuple[int, float, float, float]]) -> bytes:
    pkt = bytearray(HEADER_STRUCT.pack(int(frame_number), len(marker_triplets)))
    for marker_id, x, y, z in marker_triplets:
        pkt.extend(MARKER_STRUCT.pack(int(marker_id), float(x), float(y), float(z)))
    return bytes(pkt)


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay Vicon trajectories CSV as UDP packets.")
    ap.add_argument("--csv", type=Path, required=True, help="Input CSV with Trajectories section")
    ap.add_argument("--dst-host", required=True, help="Receiver host (LAN/Tailscale IP)")
    ap.add_argument("--dst-port", type=int, default=5005, help="Receiver UDP port")
    ap.add_argument(
        "--send-hz",
        type=float,
        default=0.0,
        help="Replay send rate. <=0 uses FPS from CSV.",
    )
    ap.add_argument(
        "--limit-frames",
        type=int,
        default=0,
        help="Optional frame cap (0 = all).",
    )
    ap.add_argument(
        "--no-realtime",
        action="store_true",
        help="Send as fast as possible (no sleep).",
    )
    args = ap.parse_args()

    fps_csv, marker_names_csv, rows = load_trajectories_csv(args.csv)
    send_hz = args.send_hz if args.send_hz > 0 else float(fps_csv)

    marker_to_id: Dict[str, int] = {name: i for i, name in enumerate(DEFAULT_MARKER_NAMES)}
    csv_marker_index: Dict[str, int] = {name: idx for idx, name in enumerate(marker_names_csv)}

    common_markers = [m for m in DEFAULT_MARKER_NAMES if m in csv_marker_index]
    if not common_markers:
        raise ValueError("No common markers between CSV and UDP schema.")

    print(f"[INFO] CSV fps={fps_csv}, rows={len(rows)}")
    print(f"[INFO] Sending to {args.dst_host}:{args.dst_port} at {send_hz:.3f} Hz")
    print(f"[INFO] Common markers={len(common_markers)}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    t0 = time.perf_counter()
    next_deadline = t0

    try:
        for idx, row in enumerate(rows):
            if args.limit_frames > 0 and sent >= args.limit_frames:
                break

            frame_no = int(row[0]) if row and row[0] == row[0] else idx
            marker_triplets: List[Tuple[int, float, float, float]] = []

            for marker_name in common_markers:
                mi = csv_marker_index[marker_name]
                x = row[2 + 3 * mi]
                y = row[2 + 3 * mi + 1]
                z = row[2 + 3 * mi + 2]
                if x != x or y != y or z != z:
                    continue
                marker_triplets.append((marker_to_id[marker_name], x, y, z))

            pkt = build_packet(frame_no, marker_triplets)
            sock.sendto(pkt, (args.dst_host, args.dst_port))
            sent += 1

            if not args.no_realtime:
                next_deadline += 1.0 / send_hz
                sleep_s = next_deadline - time.perf_counter()
                if sleep_s > 0:
                    time.sleep(sleep_s)
    finally:
        sock.close()

    dt = max(1e-9, time.perf_counter() - t0)
    print(f"[DONE] sent_frames={sent} elapsed_s={dt:.3f} effective_hz={sent / dt:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
