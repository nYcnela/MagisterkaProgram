from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RuntimeDefaults:
    udp_host: str
    udp_port: int
    input_hz: float
    window_seconds: float
    stride_seconds: float
    duration_seconds: float
    max_windows: int
    live_z_threshold: float
    live_major_order_threshold: int
    live_emit_minor_order_text: bool
    gender: str
    step_type: str
    sequence_name: str


class SessionRunner:
    def __init__(
        self,
        *,
        python_exec: str,
        output_root: Path,
        candidate_root: Path,
        offline_runs_root: Path,
        llm_url: str | None,
    ) -> None:
        self.python_exec = python_exec
        self.output_root = output_root
        self.candidate_root = candidate_root
        self.offline_runs_root = offline_runs_root
        self.llm_url = llm_url

        self.proc: Optional[subprocess.Popen[str]] = None
        self.proc_reader: Optional[threading.Thread] = None
        self.current_session_id: Optional[str] = None
        self.current_run_id: Optional[str] = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _stream_logs(self, proc: subprocess.Popen[str], prefix: str) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"{prefix}{line.rstrip()}")

    def _write_session_meta(
        self,
        *,
        session_id: str,
        run_id: str,
        dance_id: str,
        pattern_file: Path,
        control_payload: dict[str, Any],
    ) -> None:
        run_root = self.output_root / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": session_id,
            "run_id": run_id,
            "dance_id": dance_id,
            "pattern_file": str(pattern_file),
            "sequence_name": str(control_payload.get("sequence_name") or "").strip(),
            "gender": str(control_payload.get("gender") or "").strip(),
            "step_type": str(control_payload.get("step_type") or "").strip(),
            "dancer_first_name": str(control_payload.get("dancer_first_name") or "").strip(),
            "dancer_last_name": str(control_payload.get("dancer_last_name") or "").strip(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "control_payload": control_payload,
        }
        (run_root / "session_meta.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def start_session(
        self,
        *,
        session_id: str,
        run_id: str,
        dance_id: str,
        pattern_file: Path,
        defaults: RuntimeDefaults,
        control_payload: dict[str, Any],
    ) -> None:
        if self.is_running():
            self.stop_session("replace")

        script = PROJECT_ROOT / "apps/realtime/run_udp_e2e_test.py"
        if not script.exists():
            raise FileNotFoundError(f"Missing receiver script: {script}")
        if not pattern_file.exists():
            raise FileNotFoundError(f"Missing pattern file: {pattern_file}")

        # Allow overrides from control payload.
        udp_host = str(control_payload.get("udp_host", defaults.udp_host))
        udp_port = int(control_payload.get("udp_port", defaults.udp_port))
        input_hz = float(control_payload.get("input_hz", defaults.input_hz))
        window_seconds = float(control_payload.get("window_seconds", defaults.window_seconds))
        stride_seconds = float(control_payload.get("stride_seconds", defaults.stride_seconds))
        duration_seconds = float(control_payload.get("duration_seconds", defaults.duration_seconds))
        max_windows = int(control_payload.get("max_windows", defaults.max_windows))

        gender = str(control_payload.get("gender", defaults.gender))
        step_type = str(control_payload.get("step_type", defaults.step_type))
        sequence_name = str(control_payload.get("sequence_name", defaults.sequence_name))

        live_z_threshold = float(control_payload.get("live_z_threshold", defaults.live_z_threshold))
        live_major_order_threshold = int(
            control_payload.get("live_major_order_threshold", defaults.live_major_order_threshold)
        )
        live_emit_minor_order_text = bool(
            control_payload.get("live_emit_minor_order_text", defaults.live_emit_minor_order_text)
        )

        cmd = [
            self.python_exec,
            "-u",
            str(script),
            "--udp-host",
            udp_host,
            "--udp-port",
            str(udp_port),
            "--input-hz",
            str(input_hz),
            "--window-seconds",
            str(window_seconds),
            "--stride-seconds",
            str(stride_seconds),
            "--duration-seconds",
            str(duration_seconds),
            "--max-windows",
            str(max_windows),
            "--sequence-name",
            sequence_name,
            "--gender",
            gender,
            "--step-type",
            step_type,
            "--pattern-file",
            str(pattern_file),
            "--model-inputs-only",
            "--output-root",
            str(self.output_root),
            "--candidate-root",
            str(self.candidate_root),
            "--offline-runs-root",
            str(self.offline_runs_root),
            "--run-id",
            run_id,
            "--live-z-threshold",
            str(live_z_threshold),
            "--live-major-order-threshold",
            str(live_major_order_threshold),
        ]

        if live_emit_minor_order_text:
            cmd.append("--live-emit-minor-order-text")
        if self.llm_url:
            cmd.extend(["--llm-url", self.llm_url])

        print("[CONTROL] START session")
        print(f"[CONTROL] session_id={session_id} dance_id={dance_id} run_id={run_id}")
        print("[CONTROL] CMD", shlex.join(cmd))

        self._write_session_meta(
            session_id=session_id,
            run_id=run_id,
            dance_id=dance_id,
            pattern_file=pattern_file,
            control_payload=control_payload,
        )

        child_env = dict(os.environ)
        child_env["PYTHONUNBUFFERED"] = "1"
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=child_env,
            creationflags=creationflags,
        )
        self.current_session_id = session_id
        self.current_run_id = run_id

        self.proc_reader = threading.Thread(
            target=self._stream_logs,
            args=(self.proc, "[RX ] "),
            daemon=True,
        )
        self.proc_reader.start()

    def stop_session(self, reason: str) -> None:
        if not self.is_running():
            self.current_session_id = None
            self.current_run_id = None
            return

        assert self.proc is not None
        print(f"[CONTROL] STOP session_id={self.current_session_id} reason={reason}")
        try:
            if sys.platform == "win32":
                ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
                if ctrl_break is not None:
                    self.proc.send_signal(ctrl_break)
                else:
                    self.proc.terminate()
            else:
                self.proc.send_signal(signal.SIGINT)
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            print("[CONTROL][warn] Graceful stop timeout. Killing process.")
            self.proc.kill()
            self.proc.wait(timeout=3)
        except Exception as exc:
            print(f"[CONTROL][warn] Graceful stop failed ({exc}). Terminating process.")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                print("[CONTROL][warn] Terminate timeout. Killing process.")
                self.proc.kill()
                self.proc.wait(timeout=3)

        code = self.proc.returncode
        print(f"[CONTROL] receiver_exit_code={code}")
        self.proc = None
        self.proc_reader = None
        self.current_session_id = None
        self.current_run_id = None


class ControlServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        defaults: RuntimeDefaults,
        runner: SessionRunner,
    ) -> None:
        self.host = host
        self.port = port
        self.defaults = defaults
        self.runner = runner

        self.last_payload: dict[str, Any] = {}
        self.active_meta: dict[str, Any] = {}

    def _resolve_pattern_file(self, payload: dict[str, Any]) -> tuple[str, Path]:
        dance_id = str(payload.get("dance_id") or payload.get("dance") or "").strip()
        pattern_override = str(payload.get("pattern_file") or "").strip()

        if pattern_override:
            p = Path(pattern_override)
            if not p.is_absolute():
                p = (PROJECT_ROOT / p).resolve()
            return dance_id or p.stem.replace("_pattern", ""), p

        if not dance_id:
            if self.active_meta.get("dance_id"):
                dance_id = str(self.active_meta["dance_id"])
            else:
                raise ValueError("Control packet missing dance_id and pattern_file.")

        p = PROJECT_ROOT / "data/json/manual/pipeline/8_patterns/enriched" / f"{dance_id}_pattern.json"
        return dance_id, p

    def _build_run_id(self, payload: dict[str, Any], session_id: str, dance_id: str) -> str:
        custom = str(payload.get("run_id") or "").strip()
        if custom:
            return custom
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_dance = dance_id.replace("/", "_")
        return f"session_{safe_dance}_{session_id}_{ts}"

    def handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = str(msg.get("type") or msg.get("event") or "").strip().lower()
        if not msg_type:
            print("[CONTROL][warn] Missing 'type' in control packet.")
            return

        if msg_type in {"session_prepare", "prepare"}:
            self.last_payload = dict(msg)
            print(f"[CONTROL] PREP cached session meta: {json.dumps(self.last_payload, ensure_ascii=False)}")
            return

        if msg_type in {"session_start", "start_now", "start"}:
            merged = dict(self.last_payload)
            merged.update(msg)

            session_id = str(merged.get("session_id") or f"s{int(time.time())}")
            dance_id, pattern_file = self._resolve_pattern_file(merged)
            run_id = self._build_run_id(merged, session_id, dance_id)

            self.active_meta = {
                "session_id": session_id,
                "dance_id": dance_id,
                "gender": merged.get("gender", self.defaults.gender),
                "step_type": merged.get("step_type", self.defaults.step_type),
                "sequence_name": merged.get("sequence_name", self.defaults.sequence_name),
            }

            self.runner.start_session(
                session_id=session_id,
                run_id=run_id,
                dance_id=dance_id,
                pattern_file=pattern_file,
                defaults=self.defaults,
                control_payload=merged,
            )
            return

        if msg_type in {"session_end", "end", "stop", "stop_all"}:
            self.runner.stop_session(msg_type)
            self.active_meta = {}
            self.last_payload = {}
            return

        if msg_type in {"heartbeat", "ping"}:
            sid = msg.get("session_id", "-")
            print(f"[CONTROL] HEARTBEAT session_id={sid}")
            return

        print(f"[CONTROL][warn] Unknown message type: {msg_type}")

    def serve_forever(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for attempt in range(5):
            try:
                sock.bind((self.host, self.port))
                break
            except OSError as exc:
                if attempt < 4:
                    print(f"[CONTROL][warn] Port {self.port} busy, retry {attempt+1}/5 ...")
                    time.sleep(1.0)
                else:
                    print(f"[CONTROL][err] Cannot bind to {self.host}:{self.port}: {exc}")
                    print(f"[CONTROL][err] Check if another process uses port {self.port} or try a different port.")
                    raise
        print(f"[CONTROL] Listening on {self.host}:{self.port}")
        print("[CONTROL] Expected JSON datagrams with type=session_prepare/session_start/session_end")
        try:
            while True:
                data, addr = sock.recvfrom(65535)
                raw = data.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                    if not isinstance(msg, dict):
                        raise ValueError("JSON is not an object")
                except Exception as exc:
                    print(f"[CONTROL][warn] Bad JSON from {addr}: {exc} | raw={raw[:200]}")
                    continue

                print(f"[CONTROL] <= {addr[0]}:{addr[1]} {raw}")
                try:
                    self.handle_message(msg)
                except Exception as exc:
                    print(f"[CONTROL][err] {exc}")
        except KeyboardInterrupt:
            print("\n[CONTROL] Interrupted by user.")
        finally:
            try:
                self.runner.stop_session("shutdown")
            except Exception:
                pass
            sock.close()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Control-plane UDP listener that starts/stops run_udp_e2e_test.py per VR session."
    )
    ap.add_argument("--control-host", default="0.0.0.0", help="Bind host for control UDP channel")
    ap.add_argument("--control-port", type=int, default=5006, help="Bind port for control UDP channel")

    ap.add_argument("--python-exec", default=sys.executable, help="Python executable for child receiver process")
    ap.add_argument("--llm-url", default=None, help="Optional LLM URL, e.g. http://127.0.0.1:8000")

    ap.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data/tmp/realtime_controlled")
    ap.add_argument("--candidate-root", type=Path, default=Path("/tmp/realtime_controlled_candidate"))
    ap.add_argument("--offline-runs-root", type=Path, default=Path("/tmp/realtime_controlled_runs"))

    ap.add_argument("--udp-host", default="0.0.0.0", help="Default data UDP host for child receiver")
    ap.add_argument("--udp-port", type=int, default=5005, help="Default data UDP port for child receiver")
    ap.add_argument("--input-hz", type=float, default=100.0)
    ap.add_argument("--window-seconds", type=float, default=4.0)
    ap.add_argument("--stride-seconds", type=float, default=3.0)
    ap.add_argument("--duration-seconds", type=float, default=0.0)
    ap.add_argument("--max-windows", type=int, default=0)

    ap.add_argument("--gender", choices=["female", "male"], default="female")
    ap.add_argument("--step-type", choices=["step", "static"], default="step")
    ap.add_argument("--sequence-name", default="udp_sequence")

    ap.add_argument("--live-z-threshold", type=float, default=1.7)
    ap.add_argument("--live-major-order-threshold", type=int, default=60)
    ap.add_argument("--live-emit-minor-order-text", action="store_true")

    return ap.parse_args()


def main() -> int:
    args = parse_args()

    output_root = args.output_root if args.output_root.is_absolute() else (PROJECT_ROOT / args.output_root)
    candidate_root = args.candidate_root if args.candidate_root.is_absolute() else (PROJECT_ROOT / args.candidate_root)
    offline_runs_root = (
        args.offline_runs_root if args.offline_runs_root.is_absolute() else (PROJECT_ROOT / args.offline_runs_root)
    )

    output_root = output_root.resolve()
    candidate_root = candidate_root.resolve()
    offline_runs_root = offline_runs_root.resolve()

    output_root.mkdir(parents=True, exist_ok=True)
    candidate_root.mkdir(parents=True, exist_ok=True)
    offline_runs_root.mkdir(parents=True, exist_ok=True)

    defaults = RuntimeDefaults(
        udp_host=args.udp_host,
        udp_port=args.udp_port,
        input_hz=args.input_hz,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
        duration_seconds=args.duration_seconds,
        max_windows=args.max_windows,
        live_z_threshold=args.live_z_threshold,
        live_major_order_threshold=args.live_major_order_threshold,
        live_emit_minor_order_text=args.live_emit_minor_order_text,
        gender=args.gender,
        step_type=args.step_type,
        sequence_name=args.sequence_name,
    )

    runner = SessionRunner(
        python_exec=args.python_exec,
        output_root=output_root,
        candidate_root=candidate_root,
        offline_runs_root=offline_runs_root,
        llm_url=args.llm_url,
    )
    server = ControlServer(
        host=args.control_host,
        port=args.control_port,
        defaults=defaults,
        runner=runner,
    )

    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
