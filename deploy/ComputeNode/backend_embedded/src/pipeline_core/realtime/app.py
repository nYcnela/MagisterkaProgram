#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import List, Optional

from .contracts import FrameWindow, StreamStats
from .engine import RealtimeWindowEngine
from .udp_receiver import run_udp_window_loop
from .windowing import FixedStrideScheduler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Foundation for realtime pipeline (4s window / 3s stride scheduler)."
    )
    p.add_argument("--mode", choices=("preview", "listen"), default="preview", help="Execution mode")
    p.add_argument("--udp-host", default="0.0.0.0", help="UDP host bind")
    p.add_argument("--udp-port", type=int, default=5005, help="UDP port bind")
    p.add_argument("--input-hz", type=float, default=100.0, help="Expected incoming stream rate")
    p.add_argument("--window-seconds", type=float, default=4.0, help="Window length in seconds")
    p.add_argument("--stride-seconds", type=float, default=3.0, help="Window stride in seconds")
    p.add_argument(
        "--preview-seconds",
        type=int,
        default=20,
        help="How many seconds to preview scheduler decisions (foundation mode)",
    )
    p.add_argument(
        "--duration-seconds",
        type=float,
        default=30.0,
        help="Listen mode duration; <=0 means run until Ctrl+C.",
    )
    p.add_argument("--max-packets", type=int, default=0, help="Optional packet cap in listen mode")
    p.add_argument("--socket-timeout-ms", type=int, default=200, help="UDP socket timeout in milliseconds")
    p.add_argument("--max-packet-size", type=int, default=65535, help="Maximum UDP packet size")
    p.add_argument(
        "--suppress-packet-errors",
        action="store_true",
        help="Do not print parse errors for malformed packets.",
    )
    return p


def run_scheduler_preview(window_seconds: float, stride_seconds: float, preview_seconds: int) -> List[str]:
    scheduler = FixedStrideScheduler(window_seconds=window_seconds, stride_seconds=stride_seconds)
    lines: List[str] = []

    for tick in range(1, preview_seconds + 1):
        windows = scheduler.advance(1.0)
        for w in windows:
            lines.append(
                f"t={tick:>3}s -> window#{w.index:>3} [{w.start_s:.1f}s, {w.end_s:.1f}s]"
            )

    return lines


def format_stats(stats: StreamStats) -> str:
    return (
        f"packets_received={stats.packets_received} packets_parsed={stats.packets_parsed} "
        f"packets_bad={stats.packets_bad} missing_frames={stats.missing_frames} "
        f"duplicate_frames={stats.duplicate_frames} out_of_order_frames={stats.out_of_order_frames} "
        f"windows_emitted={stats.windows_emitted} windows_skipped_not_ready={stats.windows_skipped_not_ready}"
    )


def print_window(window: FrameWindow, stats: StreamStats) -> None:
    print(
        f"[WIN ] idx={window.window_index} "
        f"time=[{window.start_s:.2f},{window.end_s:.2f}] "
        f"frames={window.frame_count} frame_range=[{window.first_frame_number},{window.last_frame_number}] "
        f"missing_total={stats.missing_frames}"
    )


def run_listen_mode(args: argparse.Namespace) -> int:
    engine = RealtimeWindowEngine(
        input_hz=args.input_hz,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
    )

    duration_seconds = args.duration_seconds if args.duration_seconds > 0 else None
    max_packets = args.max_packets if args.max_packets > 0 else None

    print("[INFO] Realtime listen mode")
    print(
        f"[INFO] Binding UDP on {args.udp_host}:{args.udp_port}, input_hz={args.input_hz}, "
        f"window={args.window_seconds}s, stride={args.stride_seconds}s"
    )
    if duration_seconds is None:
        print("[INFO] Running without duration limit (Ctrl+C to stop).")
    else:
        print(f"[INFO] Duration limit: {duration_seconds:.1f}s")
    if max_packets is not None:
        print(f"[INFO] Packet limit: {max_packets}")

    def on_packet_error(exc: Exception, packet_no: int) -> None:
        if args.suppress_packet_errors:
            return
        print(f"[WARN] Malformed packet #{packet_no}: {exc}")

    try:
        stats = run_udp_window_loop(
            host=args.udp_host,
            port=args.udp_port,
            engine=engine,
            duration_seconds=duration_seconds,
            max_packets=max_packets,
            socket_timeout_ms=args.socket_timeout_ms,
            max_packet_size=args.max_packet_size,
            on_window=print_window,
            on_packet_error=on_packet_error,
        )
    except KeyboardInterrupt:
        print("\n[STOP] Interrupted by user.")
        stats = engine.stats

    print(f"[DONE] {format_stats(stats)}")
    if stats.unknown_marker_ids_seen:
        print(f"[WARN] Unknown marker IDs seen: {stats.unknown_marker_ids_seen}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.stride_seconds > args.window_seconds:
        parser.error("--stride-seconds cannot be larger than --window-seconds")

    if args.mode == "listen":
        return run_listen_mode(args)

    print("[INFO] Realtime foundation preview mode")
    print(
        f"[INFO] UDP={args.udp_host}:{args.udp_port} input_hz={args.input_hz} "
        f"window={args.window_seconds}s stride={args.stride_seconds}s"
    )
    preview_lines = run_scheduler_preview(
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
        preview_seconds=args.preview_seconds,
    )
    if not preview_lines:
        print("[INFO] Brak gotowych okien w zadanym preview.")
    else:
        print("[INFO] Podgląd harmonogramu okien:")
        for line in preview_lines:
            print(f"  {line}")

    print("[NEXT] Use --mode listen to receive live UDP packets and emit windows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
