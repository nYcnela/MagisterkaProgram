from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import ceil
from typing import Deque, Generic, List, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ScheduledWindow:
    index: int
    start_s: float
    end_s: float


class SlidingBuffer(Generic[T]):
    """Fixed-duration buffer over a fixed-rate stream."""

    def __init__(self, sample_rate_hz: float, window_seconds: float):
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.sample_rate_hz = float(sample_rate_hz)
        self.window_seconds = float(window_seconds)
        self.window_samples = int(ceil(self.sample_rate_hz * self.window_seconds))
        self._frames: Deque[T] = deque(maxlen=self.window_samples)

    def append_many(self, frames: List[T]) -> None:
        for frame in frames:
            self._frames.append(frame)

    def append(self, frame: T) -> None:
        self._frames.append(frame)

    @property
    def is_ready(self) -> bool:
        return len(self._frames) >= self.window_samples

    def snapshot(self) -> List[T]:
        return list(self._frames)


class FixedStrideScheduler:
    """Schedules window emissions for [window_seconds, stride_seconds] settings."""

    def __init__(self, window_seconds: float, stride_seconds: float):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if stride_seconds <= 0:
            raise ValueError("stride_seconds must be > 0")

        self.window_seconds = float(window_seconds)
        self.stride_seconds = float(stride_seconds)
        self._stream_time_s = 0.0
        self._next_emit_end_s = self.window_seconds
        self._window_index = 0

    def advance(self, delta_seconds: float) -> List[ScheduledWindow]:
        if delta_seconds < 0:
            raise ValueError("delta_seconds must be >= 0")
        self._stream_time_s += float(delta_seconds)

        emitted: List[ScheduledWindow] = []
        eps = 1e-9
        while self._stream_time_s + eps >= self._next_emit_end_s:
            start_s = self._next_emit_end_s - self.window_seconds
            emitted.append(
                ScheduledWindow(
                    index=self._window_index,
                    start_s=round(start_s, 6),
                    end_s=round(self._next_emit_end_s, 6),
                )
            )
            self._window_index += 1
            self._next_emit_end_s += self.stride_seconds
        return emitted

