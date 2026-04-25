from __future__ import annotations

import math
import socket
import struct
import time
from pathlib import Path
from threading import Event
from typing import Callable, Sequence


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


def _detect_delimiter(lines: list[str]) -> str:
    for line in lines[:200]:
        if "Frame;Sub Frame" in line:
            return ";"
        if "Frame,Sub Frame" in line:
            return ","
    return ";" if any(";" in line for line in lines[:50]) else ","


def _find_trajectories_section(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.strip().startswith("Trajectories"):
            return index
    raise ValueError("Could not find 'Trajectories' section in CSV.")


def _parse_marker_names(marker_line: str, delimiter: str) -> list[str]:
    parts = marker_line.rstrip("\n").split(delimiter)[2:]
    names: list[str] = []
    for index in range(len(parts) // 3):
        name = (parts[3 * index] or "").strip()
        if ":" in name:
            name = name.rsplit(":", 1)[1].strip()
        names.append(name)
    while names and names[-1] == "":
        names.pop()
    return names


def _parse_float(value: str) -> float:
    value = value.strip()
    if value == "":
        return math.nan
    return float(value)


def load_trajectories_csv(path: Path) -> tuple[float, list[str], list[list[float]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    delimiter = _detect_delimiter(lines)
    start = _find_trajectories_section(lines)
    fps = float(lines[start + 1].split(delimiter)[0].strip())
    marker_names = _parse_marker_names(lines[start + 2], delimiter)
    rows: list[list[float]] = []
    for line in lines[start + 5 :]:
        if not line.strip():
            break
        parts = line.split(delimiter)
        if len(parts) < 2 + 3 * len(marker_names):
            break
        rows.append([_parse_float(part) for part in parts[: 2 + 3 * len(marker_names)]])
    if not rows:
        raise ValueError(f"No trajectory rows parsed from {path}")
    return fps, marker_names, rows


def _packet(frame_number: int, marker_triplets: Sequence[tuple[int, float, float, float]]) -> bytes:
    packet = bytearray(HEADER_STRUCT.pack(int(frame_number), len(marker_triplets)))
    for marker_id, x, y, z in marker_triplets:
        packet.extend(MARKER_STRUCT.pack(int(marker_id), float(x), float(y), float(z)))
    return bytes(packet)


def replay_csv_files(
    csv_paths: Sequence[Path],
    *,
    dst_host: str,
    dst_port: int,
    send_hz: float = 0.0,
    dedupe_frames: bool = False,
    stop_event: Event | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, float | int]:
    if not csv_paths:
        raise ValueError("No CSV files to replay.")

    marker_to_id = {name: index for index, name in enumerate(DEFAULT_MARKER_NAMES)}
    prepared_rows: list[tuple[int, list[tuple[int, float, float, float]]]] = []
    fps_values: list[float] = []
    seen_frames: set[int] = set()

    for csv_path in csv_paths:
        fps, marker_names, rows = load_trajectories_csv(csv_path)
        fps_values.append(float(fps))
        csv_marker_index = {name: index for index, name in enumerate(marker_names)}
        common_markers = [name for name in DEFAULT_MARKER_NAMES if name in csv_marker_index]
        if not common_markers:
            raise ValueError(f"No common markers between CSV and UDP schema: {csv_path}")

        for row_index, row in enumerate(rows):
            frame_number = int(row[0]) if row and math.isfinite(row[0]) else row_index
            if dedupe_frames and frame_number in seen_frames:
                continue
            seen_frames.add(frame_number)

            marker_triplets: list[tuple[int, float, float, float]] = []
            for marker_name in common_markers:
                marker_index = csv_marker_index[marker_name]
                x = row[2 + 3 * marker_index]
                y = row[2 + 3 * marker_index + 1]
                z = row[2 + 3 * marker_index + 2]
                if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                    continue
                marker_triplets.append((marker_to_id[marker_name], x, y, z))
            prepared_rows.append((frame_number, marker_triplets))

    if dedupe_frames:
        prepared_rows.sort(key=lambda item: item[0])

    effective_hz = float(send_hz) if send_hz and send_hz > 0 else (fps_values[0] if fps_values else 100.0)
    delay_s = 1.0 / max(effective_hz, 1e-6)
    started = time.perf_counter()
    sent = 0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        next_deadline = started
        for frame_number, marker_triplets in prepared_rows:
            if stop_event is not None and stop_event.is_set():
                break
            sock.sendto(_packet(frame_number, marker_triplets), (dst_host, int(dst_port)))
            sent += 1
            next_deadline += delay_s
            sleep_s = next_deadline - time.perf_counter()
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        sock.close()

    elapsed = max(time.perf_counter() - started, 1e-9)
    if log is not None:
        log(f"Replay sent {sent} frame(s) from {len(csv_paths)} CSV file(s) in {elapsed:.2f}s.")
    return {
        "csv_count": len(csv_paths),
        "frame_count": len(prepared_rows),
        "sent_frames": sent,
        "elapsed_s": round(elapsed, 3),
        "effective_hz": round(sent / elapsed, 3),
    }
