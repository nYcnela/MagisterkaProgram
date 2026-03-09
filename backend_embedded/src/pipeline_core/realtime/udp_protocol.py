from __future__ import annotations

import struct
import time
from typing import Dict, Sequence

from .contracts import MarkerSample, MotionFrame


# Must match marker schema used by sender.
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

HEADER_STRUCT = struct.Struct("<IH")  # uint32 frame + uint16 marker_count
MARKER_STRUCT = struct.Struct("<Hddd")  # uint16 marker_id + 3x float64


def build_id_to_name(marker_names: Sequence[str]) -> Dict[int, str]:
    return {idx: name for idx, name in enumerate(marker_names)}


def parse_udp_packet(
    packet: bytes,
    *,
    marker_names: Sequence[str] = DEFAULT_MARKER_NAMES,
    received_at_monotonic: float | None = None,
) -> MotionFrame:
    if len(packet) < HEADER_STRUCT.size:
        raise ValueError(
            f"Packet too short: got={len(packet)} bytes, expected at least {HEADER_STRUCT.size} bytes."
        )

    frame_number, marker_count = HEADER_STRUCT.unpack_from(packet, 0)
    expected_size = HEADER_STRUCT.size + marker_count * MARKER_STRUCT.size
    if len(packet) != expected_size:
        raise ValueError(
            f"Invalid packet size: got={len(packet)} bytes, expected={expected_size} bytes "
            f"for marker_count={marker_count}."
        )

    id_to_name = build_id_to_name(marker_names)
    markers: Dict[str, MarkerSample] = {}
    unknown_marker_ids: set[int] = set()

    offset = HEADER_STRUCT.size
    for _ in range(marker_count):
        marker_id, x, y, z = MARKER_STRUCT.unpack_from(packet, offset)
        marker_name = id_to_name.get(marker_id)
        if marker_name is None:
            marker_name = f"UNKNOWN_{marker_id}"
            unknown_marker_ids.add(marker_id)

        markers[marker_name] = MarkerSample(
            marker_id=int(marker_id),
            marker_name=marker_name,
            x=float(x),
            y=float(y),
            z=float(z),
        )
        offset += MARKER_STRUCT.size

    if received_at_monotonic is None:
        received_at_monotonic = time.monotonic()

    return MotionFrame(
        frame_number=int(frame_number),
        received_at_monotonic=float(received_at_monotonic),
        markers=markers,
        unknown_marker_ids=tuple(sorted(unknown_marker_ids)),
    )

