from __future__ import annotations

import socket
import time
from typing import Callable, Optional

from .contracts import FrameWindow, StreamStats
from .engine import RealtimeWindowEngine
from .udp_protocol import parse_udp_packet

WindowCallback = Callable[[FrameWindow, StreamStats], None]
PacketErrorCallback = Callable[[Exception, int], None]


def run_udp_window_loop(
    *,
    host: str,
    port: int,
    engine: RealtimeWindowEngine,
    duration_seconds: float | None,
    max_packets: int | None,
    socket_timeout_ms: int,
    max_packet_size: int = 65535,
    on_window: Optional[WindowCallback] = None,
    on_packet_error: Optional[PacketErrorCallback] = None,
) -> StreamStats:
    if socket_timeout_ms <= 0:
        raise ValueError("socket_timeout_ms must be > 0")
    if max_packet_size <= 0:
        raise ValueError("max_packet_size must be > 0")

    start = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.settimeout(socket_timeout_ms / 1000.0)

    try:
        while True:
            if duration_seconds is not None and duration_seconds > 0:
                if time.monotonic() - start >= duration_seconds:
                    break

            if max_packets is not None and max_packets > 0:
                if engine.stats.packets_received >= max_packets:
                    break

            try:
                data, _addr = sock.recvfrom(max_packet_size)
            except socket.timeout:
                continue

            engine.stats.packets_received += 1

            try:
                frame = parse_udp_packet(data, received_at_monotonic=time.monotonic())
            except Exception as exc:  # malformed packet
                engine.stats.packets_bad += 1
                if on_packet_error is not None:
                    on_packet_error(exc, engine.stats.packets_received)
                continue

            windows = engine.ingest_frame(frame)
            if on_window is not None:
                for window in windows:
                    on_window(window, engine.stats)
    finally:
        sock.close()

    return engine.stats

