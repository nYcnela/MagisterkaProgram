"""Realtime pipeline foundations (UDP + window scheduler)."""

from .contracts import FrameWindow, MarkerSample, MotionFrame, StreamStats
from .engine import RealtimeWindowEngine
from .udp_protocol import DEFAULT_MARKER_NAMES, parse_udp_packet

__all__ = [
    "DEFAULT_MARKER_NAMES",
    "FrameWindow",
    "MarkerSample",
    "MotionFrame",
    "StreamStats",
    "RealtimeWindowEngine",
    "parse_udp_packet",
]
