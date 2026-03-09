from __future__ import annotations

import asyncio
from collections import deque
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from .compute_settings import ComputeNodeConfig, load_compute_config
from .control_contracts import NodeSnapshot, ProcessStatus, SessionStartRequest, SessionStopRequest, WsEvent
from .launch import build_backend_command, build_llm_command, extract_feedback_text
from .settings import StudioConfig


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            proc.kill()
    else:
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


class EventHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: dict[int, asyncio.Queue[dict]] = {}
        self._lock = threading.Lock()
        self._next_id = 1

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def subscribe(self) -> tuple[int, asyncio.Queue[dict]]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        with self._lock:
            sub_id = self._next_id
            self._next_id += 1
            self._subs[sub_id] = queue
        return sub_id, queue

    def unsubscribe(self, sub_id: int) -> None:
        with self._lock:
            self._subs.pop(sub_id, None)

    def publish(self, event: dict) -> None:
        if self._loop is None:
            return
        with self._lock:
            queues = list(self._subs.values())
        for queue in queues:
            self._loop.call_soon_threadsafe(queue.put_nowait, event)


class ComputeNodeManager:
    def __init__(self, cfg: ComputeNodeConfig) -> None:
        self.cfg = cfg
        self.snapshot = NodeSnapshot()
        self.snapshot.llm.details = f"http://{cfg.llm_host}:{cfg.llm_port}"
        self._recent_logs: deque[str] = deque(maxlen=400)
        self._hub = EventHub()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        self._backend_proc: Optional[subprocess.Popen[str]] = None
        self._llm_proc: Optional[subprocess.Popen[str]] = None
        self._backend_thread: Optional[threading.Thread] = None
        self._llm_thread: Optional[threading.Thread] = None

        self._health_thread = threading.Thread(target=self._health_loop, name="llm-health", daemon=True)
        self._health_thread.start()

    def _publish(self, event_type: str, payload: dict) -> None:
        self._hub.publish(WsEvent(type=event_type, payload=payload).model_dump())

    def _append_log(self, source: str, line: str) -> None:
        entry = f"[{source.upper()}] {line}"
        with self._lock:
            self._recent_logs.append(entry)
            self.snapshot.recent_logs = list(self._recent_logs)
        self._publish("log", {"source": source, "line": entry})

        feedback = extract_feedback_text(line)
        if feedback:
            with self._lock:
                self.snapshot.last_feedback = feedback
            self._publish("feedback", {"text": feedback})

        if source == "backend":
            self._consume_backend_line(line)

    def _consume_backend_line(self, line: str) -> None:
        if line.startswith("[CONTROL] session_id="):
            session_id = ""
            dance_id = ""
            run_id = ""
            for part in line.replace("[CONTROL] ", "").split():
                if part.startswith("session_id="):
                    session_id = part.split("=", 1)[1]
                elif part.startswith("dance_id="):
                    dance_id = part.split("=", 1)[1]
                elif part.startswith("run_id="):
                    run_id = part.split("=", 1)[1]
            with self._lock:
                self.snapshot.session_active = True
                self.snapshot.session_id = session_id
                self.snapshot.dance_id = dance_id
                if run_id:
                    self.snapshot.run_id = run_id
            self._publish(
                "session_started",
                {"session_id": session_id, "dance_id": dance_id, "run_id": run_id},
            )
        elif line.startswith("[CONTROL] STOP session_id="):
            with self._lock:
                self.snapshot.session_active = False
                self.snapshot.session_id = ""
            self._publish("session_stopped", {"reason": line})

    def _studio_cfg(self) -> StudioConfig:
        return StudioConfig(
            backend_root=self.cfg.backend_root,
            python_exec=self.cfg.python_exec or sys.executable,
            udp_host=self.cfg.udp_host,
            udp_data_port=self.cfg.udp_data_port,
            udp_control_port=self.cfg.udp_control_port,
            llm_enabled=self.cfg.llm_enabled,
            llm_host=self.cfg.llm_host,
            llm_port=self.cfg.llm_port,
            llm_adapter_dir=self.cfg.llm_adapter_dir,
            llm_model_id=self.cfg.llm_model_id,
            llm_use_4bit=self.cfg.llm_use_4bit,
            auto_start_llm=self.cfg.auto_start_llm_with_backend,
            input_hz=self.cfg.input_hz,
            window_seconds=self.cfg.window_seconds,
            stride_seconds=self.cfg.stride_seconds,
            duration_seconds=self.cfg.duration_seconds,
            max_windows=self.cfg.max_windows,
            dance_id=self.cfg.dance_id,
            sequence_name=self.cfg.sequence_name,
            gender=self.cfg.gender,
            step_type=self.cfg.step_type,
            live_z_threshold=self.cfg.live_z_threshold,
            live_major_order_threshold=self.cfg.live_major_order_threshold,
            live_emit_minor_order_text=self.cfg.live_emit_minor_order_text,
            output_root=self.cfg.output_root,
            candidate_root=self.cfg.candidate_root,
            offline_runs_root=self.cfg.offline_runs_root,
            auto_control_port=self.cfg.auto_control_port,
            auto_detect_dance=self.cfg.auto_detect_dance,
            session_mode=self.cfg.session_mode,
        )

    def _set_process_status(self, kind: str, state: str, details: str = "", pid: int | None = None) -> None:
        with self._lock:
            target = self.snapshot.backend if kind == "backend" else self.snapshot.llm
            target.state = state
            target.details = details
            target.pid = pid
            payload = target.model_dump()
        self._publish(f"{kind}_state", payload)

    def _stream_proc(self, kind: str, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            self._append_log(kind, raw_line.rstrip())

        code = proc.wait()
        if kind == "backend":
            with self._lock:
                self._backend_proc = None
                self._backend_thread = None
                self.snapshot.session_active = False
                self.snapshot.session_id = ""
            state = "STOPPED" if code == 0 else "ERROR"
            details = "" if code == 0 else f"exit={code}"
        else:
            with self._lock:
                self._llm_proc = None
                self._llm_thread = None
            state = "STOPPED" if code == 0 else "ERROR"
            details = "" if code == 0 else f"exit={code}"
        self._set_process_status(kind, state, details, None)

    def _spawn(self, kind: str, program: str, args: list[str], cwd: Path) -> None:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [program, *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        thread = threading.Thread(target=self._stream_proc, args=(kind, proc), daemon=True, name=f"{kind}-stream")
        thread.start()

        if kind == "backend":
            with self._lock:
                self._backend_proc = proc
                self._backend_thread = thread
            self._set_process_status("backend", "READY", "listening", proc.pid)
        else:
            with self._lock:
                self._llm_proc = proc
                self._llm_thread = thread
            self._set_process_status("llm", "STARTING", "booting", proc.pid)

    def start_llm(self) -> None:
        with self._lock:
            if self._llm_proc is not None and self._llm_proc.poll() is None:
                return
        cfg = self._studio_cfg()
        program, args, backend_root = build_llm_command(cfg)
        self._append_log("node", f"Starting LLM on {cfg.llm_host}:{cfg.llm_port}")
        self._spawn("llm", program, args, backend_root)

    def stop_llm(self) -> None:
        with self._lock:
            proc = self._llm_proc
        if proc is None or proc.poll() is not None:
            self._set_process_status("llm", "STOPPED", "")
            return
        self._append_log("node", "Stopping LLM")
        _kill_process_tree(proc)

    def start_backend(self) -> str:
        with self._lock:
            if self._backend_proc is not None and self._backend_proc.poll() is None:
                return self.snapshot.run_id

        if self.cfg.auto_start_llm_with_backend and self.cfg.llm_enabled:
            self.start_llm()

        cfg = self._studio_cfg()
        program, args, run_id, backend_root = build_backend_command(cfg)
        with self._lock:
            self.snapshot.run_id = run_id
        self._append_log("node", f"Starting backend run_id={run_id}")
        self._spawn("backend", program, args, backend_root)
        return run_id

    def stop_backend(self) -> None:
        with self._lock:
            proc = self._backend_proc
        if proc is None or proc.poll() is not None:
            self._set_process_status("backend", "STOPPED", "")
            return
        self._append_log("node", "Stopping backend")
        _kill_process_tree(proc)

    def _send_control_packet(self, payload: dict) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                ("127.0.0.1", int(self.cfg.udp_control_port)),
            )
        finally:
            sock.close()

    def start_session(self, req: SessionStartRequest) -> dict:
        with self._lock:
            proc = self._backend_proc
        if proc is None or proc.poll() is not None:
            raise RuntimeError("Backend is not running.")

        session_id = req.session_id.strip() or f"s{int(time.time())}"
        payload = {
            "type": "session_start",
            "session_id": session_id,
            "dance_id": req.dance_id,
            "sequence_name": req.sequence_name,
            "gender": req.gender,
            "step_type": req.step_type,
        }
        if req.run_id.strip():
            payload["run_id"] = req.run_id.strip()
        payload.update(req.extra)
        self._send_control_packet(payload)
        self._append_log("node", f"Sent session_start for {session_id}")
        return payload

    def stop_session(self, req: SessionStopRequest) -> dict:
        payload = {"type": "session_end", "reason": req.reason}
        self._send_control_packet(payload)
        self._append_log("node", f"Sent session_end reason={req.reason}")
        return payload

    def snapshot_data(self) -> NodeSnapshot:
        with self._lock:
            return NodeSnapshot.model_validate(self.snapshot.model_dump())

    def _health_loop(self) -> None:
        while not self._stop_event.wait(0.8):
            with self._lock:
                llm_proc = self._llm_proc
            if llm_proc is None or llm_proc.poll() is not None:
                continue

            url = f"http://{self.cfg.llm_host}:{self.cfg.llm_port}/health"
            try:
                from urllib import request

                req = request.Request(url, method="GET")
                with request.urlopen(req, timeout=0.4) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                loaded = bool(payload.get("model_loaded", False))
                if loaded:
                    self._set_process_status("llm", "READY", "model loaded", llm_proc.pid)
                else:
                    self._set_process_status("llm", "STARTING", "loading model", llm_proc.pid)
            except Exception:
                self._set_process_status("llm", "STARTING", "booting", llm_proc.pid)

    async def ws_events(self, websocket: WebSocket) -> None:
        await websocket.accept()
        sub_id, queue = await self._hub.subscribe()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            self._hub.unsubscribe(sub_id)

    def shutdown(self) -> None:
        self._stop_event.set()
        self.stop_backend()
        self.stop_llm()


def create_app(cfg: ComputeNodeConfig | None = None) -> FastAPI:
    manager = ComputeNodeManager(cfg or load_compute_config())
    app = FastAPI(title="Realtime Compute Node")
    app.state.manager = manager

    @app.on_event("startup")
    async def _startup() -> None:
        manager._hub.bind_loop(asyncio.get_running_loop())

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        manager.shutdown()

    @app.get("/health")
    def health():
        return manager.snapshot_data().model_dump()

    @app.get("/snapshot")
    def snapshot():
        return manager.snapshot_data().model_dump()

    @app.post("/llm/start")
    def llm_start():
        manager.start_llm()
        return manager.snapshot_data().model_dump()

    @app.post("/llm/stop")
    def llm_stop():
        manager.stop_llm()
        return manager.snapshot_data().model_dump()

    @app.post("/backend/start")
    def backend_start():
        run_id = manager.start_backend()
        return {"run_id": run_id, "snapshot": manager.snapshot_data().model_dump()}

    @app.post("/backend/stop")
    def backend_stop():
        manager.stop_backend()
        return manager.snapshot_data().model_dump()

    @app.post("/session/start")
    def session_start(req: SessionStartRequest):
        try:
            payload = manager.start_session(req)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"sent": payload, "snapshot": manager.snapshot_data().model_dump()}

    @app.post("/session/stop")
    def session_stop(req: SessionStopRequest):
        payload = manager.stop_session(req)
        return {"sent": payload, "snapshot": manager.snapshot_data().model_dump()}

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket):
        await manager.ws_events(websocket)

    return app


def main() -> int:
    cfg = load_compute_config()
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.manager_host, port=cfg.manager_port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

