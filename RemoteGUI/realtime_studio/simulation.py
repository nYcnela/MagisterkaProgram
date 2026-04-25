from __future__ import annotations

import math
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Sequence


TEST_DATA_ROOT = Path(__file__).resolve().parents[1] / "TestData"

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


@dataclass(frozen=True)
class TestCsvSource:
    label: str
    dance_id: str
    csv_path: Path


def infer_dance_id(name: str, dance_choices: Sequence[str]) -> str:
    stem = Path(name).stem
    for dance_id in sorted(dance_choices, key=len, reverse=True):
        if stem.startswith(dance_id):
            return dance_id
    return ""


def list_test_csv_sources(dance_choices: Sequence[str]) -> list[TestCsvSource]:
    if not TEST_DATA_ROOT.exists():
        return []
    sources: list[TestCsvSource] = []
    for path in sorted(TEST_DATA_ROOT.glob("*.csv")):
        dance_id = infer_dance_id(path.name, dance_choices)
        label = f"{dance_id or path.stem} | {path.name}"
        sources.append(TestCsvSource(label=label, dance_id=dance_id, csv_path=path))
    return sources


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


def replay_csv(
    csv_path: Path,
    *,
    dst_host: str,
    dst_port: int,
    send_hz: float = 0.0,
    stop_event: Event | None = None,
) -> dict[str, float | int]:
    fps, marker_names, rows = load_trajectories_csv(csv_path)
    effective_hz = float(send_hz) if send_hz and send_hz > 0 else fps
    delay_s = 1.0 / max(effective_hz, 1e-6)
    marker_to_id = {name: index for index, name in enumerate(DEFAULT_MARKER_NAMES)}
    csv_marker_index = {name: index for index, name in enumerate(marker_names)}
    common_markers = [name for name in DEFAULT_MARKER_NAMES if name in csv_marker_index]
    if not common_markers:
        raise ValueError("No common markers between CSV and UDP schema.")

    started = time.perf_counter()
    sent = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        next_deadline = started
        for row_index, row in enumerate(rows):
            if stop_event is not None and stop_event.is_set():
                break
            frame_number = int(row[0]) if row and math.isfinite(row[0]) else row_index
            marker_triplets: list[tuple[int, float, float, float]] = []
            for marker_name in common_markers:
                marker_index = csv_marker_index[marker_name]
                x = row[2 + 3 * marker_index]
                y = row[2 + 3 * marker_index + 1]
                z = row[2 + 3 * marker_index + 2]
                if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                    continue
                marker_triplets.append((marker_to_id[marker_name], x, y, z))
            sock.sendto(_packet(frame_number, marker_triplets), (dst_host, int(dst_port)))
            sent += 1
            next_deadline += delay_s
            sleep_s = next_deadline - time.perf_counter()
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        sock.close()

    elapsed = max(time.perf_counter() - started, 1e-9)
    return {
        "frame_count": len(rows),
        "sent_frames": sent,
        "elapsed_s": round(elapsed, 3),
        "effective_hz": round(sent / elapsed, 3),
    }
