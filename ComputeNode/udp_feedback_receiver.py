#!/usr/bin/env python3
"""Test receiver for VR feedback UDP packets.

Listens on a UDP port and prints incoming feedback JSON to the console.
Usage:
    python udp_feedback_receiver.py [--host 0.0.0.0] [--port 5007]
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime


def main() -> int:
    parser = argparse.ArgumentParser(description="UDP feedback receiver (test)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5007, help="UDP port (default: 5007)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"Listening for VR feedback on {args.host}:{args.port} ...")
    print("-" * 60)

    try:
        while True:
            data, addr = sock.recvfrom(65536)
            now = datetime.now().strftime("%H:%M:%S")
            try:
                payload = json.loads(data.decode("utf-8"))
                ptype = payload.get("type", "?")
                text = payload.get("text", data.decode("utf-8"))
                print(f"[{now}] from {addr[0]}:{addr[1]}  type={ptype}")
                print(f"  {text}")
                print()
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"[{now}] raw from {addr[0]}:{addr[1]}: {data!r}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
