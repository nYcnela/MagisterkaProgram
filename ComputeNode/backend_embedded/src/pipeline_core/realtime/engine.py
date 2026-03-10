from __future__ import annotations

from typing import List, Set

from .contracts import FrameWindow, MotionFrame, StreamStats
from .windowing import FixedStrideScheduler, ScheduledWindow, SlidingBuffer


class RealtimeWindowEngine:
    """Ingests parsed frames and emits sliding windows using 4s/3s scheduling."""

    def __init__(self, *, input_hz: float, window_seconds: float, stride_seconds: float):
        if input_hz <= 0:
            raise ValueError("input_hz must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if stride_seconds <= 0:
            raise ValueError("stride_seconds must be > 0")
        if stride_seconds > window_seconds:
            raise ValueError("stride_seconds cannot be greater than window_seconds")

        self.input_hz = float(input_hz)
        self.buffer = SlidingBuffer[MotionFrame](sample_rate_hz=input_hz, window_seconds=window_seconds)
        self.scheduler = FixedStrideScheduler(window_seconds=window_seconds, stride_seconds=stride_seconds)
        self.stats = StreamStats()
        self._unknown_ids_seen: Set[int] = set()
        self._last_frame: MotionFrame | None = None

    def ingest_frame(self, frame: MotionFrame) -> List[FrameWindow]:
        self.stats.packets_parsed += 1

        for marker_id in frame.unknown_marker_ids:
            self._unknown_ids_seen.add(marker_id)
        self.stats.unknown_marker_ids_seen = tuple(sorted(self._unknown_ids_seen))

        previous = self.stats.last_frame_number
        if previous is None:
            self.stats.last_frame_number = frame.frame_number
            self._last_frame = frame
            return self._append_and_emit(frame)

        frame_diff = frame.frame_number - previous
        if frame_diff == 0:
            self.stats.duplicate_frames += 1
            return []
        if frame_diff < 0:
            self.stats.out_of_order_frames += 1
            return []

        out: List[FrameWindow] = []
        if frame_diff > 1:
            self.stats.missing_frames += frame_diff - 1
            if self._last_frame is not None:
                for missing_frame_number in range(previous + 1, frame.frame_number):
                    filler = MotionFrame(
                        frame_number=missing_frame_number,
                        received_at_monotonic=self._last_frame.received_at_monotonic,
                        markers=self._last_frame.markers,
                        unknown_marker_ids=self._last_frame.unknown_marker_ids,
                    )
                    out.extend(self._append_and_emit(filler))

        self.stats.last_frame_number = frame.frame_number
        self._last_frame = frame
        out.extend(self._append_and_emit(frame))
        return out

    def _append_and_emit(self, frame: MotionFrame) -> List[FrameWindow]:
        self.buffer.append(frame)
        emitted_specs = self.scheduler.advance(1.0 / self.input_hz)
        return self._build_windows(emitted_specs)

    def _build_windows(self, specs: List[ScheduledWindow]) -> List[FrameWindow]:
        out: List[FrameWindow] = []
        for spec in specs:
            if not self.buffer.is_ready:
                self.stats.windows_skipped_not_ready += 1
                continue

            snapshot = self.buffer.snapshot()
            if not snapshot:
                self.stats.windows_skipped_not_ready += 1
                continue

            window = FrameWindow(
                window_index=spec.index,
                start_s=spec.start_s,
                end_s=spec.end_s,
                first_frame_number=snapshot[0].frame_number,
                last_frame_number=snapshot[-1].frame_number,
                frames=snapshot,
            )
            self.stats.windows_emitted += 1
            out.append(window)
        return out
