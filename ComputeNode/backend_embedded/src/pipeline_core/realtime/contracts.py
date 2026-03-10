from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MarkerSample:
    marker_id: int
    marker_name: str
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class MotionFrame:
    frame_number: int
    received_at_monotonic: float
    markers: Dict[str, MarkerSample]
    unknown_marker_ids: Tuple[int, ...] = field(default_factory=tuple)

    @property
    def marker_count(self) -> int:
        return len(self.markers)


@dataclass(frozen=True)
class FrameWindow:
    window_index: int
    start_s: float
    end_s: float
    first_frame_number: int
    last_frame_number: int
    frames: List[MotionFrame]

    @property
    def frame_count(self) -> int:
        return len(self.frames)


@dataclass
class StreamStats:
    packets_received: int = 0
    packets_parsed: int = 0
    packets_bad: int = 0
    duplicate_frames: int = 0
    out_of_order_frames: int = 0
    missing_frames: int = 0
    windows_emitted: int = 0
    windows_skipped_not_ready: int = 0
    last_frame_number: Optional[int] = None
    unknown_marker_ids_seen: Tuple[int, ...] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, int | Tuple[int, ...] | None]:
        return {
            "packets_received": self.packets_received,
            "packets_parsed": self.packets_parsed,
            "packets_bad": self.packets_bad,
            "duplicate_frames": self.duplicate_frames,
            "out_of_order_frames": self.out_of_order_frames,
            "missing_frames": self.missing_frames,
            "windows_emitted": self.windows_emitted,
            "windows_skipped_not_ready": self.windows_skipped_not_ready,
            "last_frame_number": self.last_frame_number,
            "unknown_marker_ids_seen": self.unknown_marker_ids_seen,
        }

