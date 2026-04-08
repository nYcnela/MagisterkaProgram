from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
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

from .analysis import build_run_analysis, list_analysis_runs
from .compute_settings import ComputeNodeConfig, load_compute_config
from .control_contracts import NodeSnapshot, ProcessStatus, SessionStartRequest, SessionStopRequest, SetDancerRequest, WsEvent
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
        self._llm_external = False

        self._vr_sock: socket.socket | None = None
        if cfg.vr_feedback_enabled:
            self._vr_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._session_scores: list[float] = []

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
            self._send_vr_feedback(feedback)
            score = self._extract_feedback_score(line)
            if score is not None:
                with self._lock:
                    self._session_scores.append(score)

        if source == "backend":
            self._consume_backend_line(line)

    @staticmethod
    def _extract_feedback_score(line: str) -> float | None:
        m = re.search(r"\(score=([0-9.]+)", line)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _send_vr_feedback(self, feedback: str) -> None:
        self._send_vr_packet({"type": "feedback", "text": feedback})

    def _send_vr_summary(self) -> None:
        with self._lock:
            scores = list(self._session_scores)
        if not scores:
            return
        avg = round(sum(scores) / len(scores), 2)
        self._append_log("node", f"Session summary: {len(scores)} feedback(s), avg score={avg}")
        self._send_vr_packet({"type": "summary", "text": str(avg)})

    def _send_vr_packet(self, payload: dict) -> None:
        if self._vr_sock is None:
            return
        try:
            packet = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._vr_sock.sendto(packet, (self.cfg.vr_feedback_host, self.cfg.vr_feedback_port))
        except Exception:
            pass

    def _parse_control_kv(self, line: str, prefix: str) -> dict[str, str]:
        kv: dict[str, str] = {}
        for part in line.replace(prefix, "", 1).split():
            if "=" in part:
                k, v = part.split("=", 1)
                kv[k] = v
        return kv

    def _consume_backend_line(self, line: str) -> None:
        if line.startswith("[CONTROL] PREP session_id="):
            kv = self._parse_control_kv(line, "[CONTROL] PREP ")
            run_id = kv.get("run_id", "")
            dance_id = kv.get("dance_id", "")
            with self._lock:
                if run_id:
                    self.snapshot.run_id = run_id
                if dance_id:
                    self.snapshot.dance_id = dance_id
            self._publish("session_prepared", {"run_id": run_id, "dance_id": dance_id})

        elif line.startswith("[CONTROL] session_id="):
            kv = self._parse_control_kv(line, "[CONTROL] ")
            session_id = kv.get("session_id", "")
            dance_id = kv.get("dance_id", "")
            run_id = kv.get("run_id", "")
            with self._lock:
                self.snapshot.session_active = True
                self.snapshot.session_id = session_id
                self.snapshot.dance_id = dance_id
                if run_id:
                    self.snapshot.run_id = run_id
            with self._lock:
                self._session_scores.clear()
            self._publish(
                "session_started",
                {"session_id": session_id, "dance_id": dance_id, "run_id": run_id},
            )

        elif line.startswith("[CONTROL] STOP session_id="):
            self._send_vr_summary()
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
            step_type=self.cfg.step_type,
            live_z_threshold=self.cfg.live_z_threshold,
            live_major_order_threshold=self.cfg.live_major_order_threshold,
            live_emit_minor_order_text=self.cfg.live_emit_minor_order_text,
            output_root=self.cfg.output_root,
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

    def _connect_host(self, host: str) -> str:
        clean = host.strip()
        if clean in {"", "0.0.0.0", "::"}:
            return "127.0.0.1"
        return clean

    def _probe_llm_health(self, timeout: float = 0.4) -> dict | None:
        url = f"http://{self._connect_host(self.cfg.llm_host)}:{self.cfg.llm_port}/health"
        try:
            from urllib import request

            req = request.Request(url, method="GET")
            with request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _port_in_use(self, host: str, port: int, timeout: float = 0.2) -> bool:
        target_host = self._connect_host(host)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((target_host, int(port))) == 0
        except Exception:
            return False
        finally:
            sock.close()

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

        # Try to detect an existing LLM server (two attempts, increasing timeout).
        for timeout in (0.6, 1.5):
            existing = self._probe_llm_health(timeout=timeout)
            if existing is not None:
                self._llm_external = True
                loaded = bool(existing.get("model_loaded", False))
                details = "existing server" if loaded else "existing server loading"
                pid = existing.get("pid") if isinstance(existing.get("pid"), int) else None
                self._append_log("node", f"LLM already responding on {cfg.llm_host}:{cfg.llm_port}; reusing existing server.")
                self._set_process_status("llm", "READY" if loaded else "STARTING", details, pid)
                return

        if self._port_in_use(cfg.llm_host, int(cfg.llm_port)):
            # Port occupied but health endpoint not ready yet — assume LLM is booting.
            self._llm_external = True
            self._append_log("node", f"Port {cfg.llm_port} in use; waiting for LLM health endpoint.")
            self._set_process_status("llm", "STARTING", f"port {cfg.llm_port} occupied, probing", None)
            return

        program, args, backend_root = build_llm_command(cfg)
        self._llm_external = False
        self._append_log("node", f"Starting LLM on {cfg.llm_host}:{cfg.llm_port}")
        self._spawn("llm", program, args, backend_root)

    def stop_llm(self) -> None:
        with self._lock:
            proc = self._llm_proc
            external = self._llm_external
        if proc is None or proc.poll() is not None:
            if external:
                existing = self._probe_llm_health(timeout=0.3)
                if existing is not None:
                    loaded = bool(existing.get("model_loaded", False))
                    pid = existing.get("pid") if isinstance(existing.get("pid"), int) else None
                    self._append_log("node", "LLM is provided by an external server; stop skipped.")
                    self._set_process_status("llm", "READY" if loaded else "STARTING", "external server", pid)
                    return
                self._llm_external = False
            self._set_process_status("llm", "STOPPED", "")
            return
        self._llm_external = False
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
            "step_type": req.step_type,
        }
        if req.run_id.strip():
            payload["run_id"] = req.run_id.strip()
        payload.update(req.extra)
        self._send_control_packet(payload)
        self._append_log("node", f"Sent session_start for {session_id}")
        return payload

    def set_dancer(self, first_name: str, last_name: str) -> dict:
        payload = {
            "type": "set_dancer",
            "dancer_first_name": first_name.strip(),
            "dancer_last_name": last_name.strip(),
        }
        self._send_control_packet(payload)
        self._append_log("node", f"Sent set_dancer first={first_name.strip()!r} last={last_name.strip()!r}")
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
                external = self._llm_external
            if (llm_proc is None or llm_proc.poll() is not None) and not external:
                continue

            payload = self._probe_llm_health(timeout=0.4)
            if payload is not None:
                loaded = bool(payload.get("model_loaded", False))
                pid = payload.get("pid") if isinstance(payload.get("pid"), int) else None
                if external:
                    details = "external server" if loaded else "external server loading"
                else:
                    details = "model loaded" if loaded else "loading model"
                    if pid is None and llm_proc is not None:
                        pid = llm_proc.pid
                self._set_process_status("llm", "READY" if loaded else "STARTING", details, pid)
            elif external:
                with self._lock:
                    self._llm_external = False
                self._set_process_status("llm", "STOPPED", "")
            elif llm_proc is not None and llm_proc.poll() is None:
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
        if self._vr_sock is not None:
            self._vr_sock.close()


def create_app(cfg: ComputeNodeConfig | None = None) -> FastAPI:
    manager = ComputeNodeManager(cfg or load_compute_config())
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager._hub.bind_loop(asyncio.get_running_loop())
        try:
            yield
        finally:
            manager.shutdown()

    app = FastAPI(title="Realtime Compute Node", lifespan=lifespan)
    app.state.manager = manager

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

    @app.post("/dancer/set")
    def dancer_set(req: SetDancerRequest):
        payload = manager.set_dancer(req.dancer_first_name, req.dancer_last_name)
        return {"sent": payload}

    @app.post("/session/stop")
    def session_stop(req: SessionStopRequest):
        payload = manager.stop_session(req)
        return {"sent": payload, "snapshot": manager.snapshot_data().model_dump()}

    @app.get("/analysis/runs")
    def analysis_runs():
        return {"runs": list_analysis_runs(manager.cfg)}

    @app.get("/analysis/run/{run_id}")
    def analysis_run(run_id: str):
        try:
            payload = build_run_analysis(manager.cfg, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return payload

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket):
        await manager.ws_events(websocket)

    return app


def main() -> int:
    cfg = load_compute_config()
    app = create_app(cfg)
    print("[NODE] ComputeNode READY", flush=True)
    print(f"[NODE] HTTP health: http://{cfg.manager_host}:{cfg.manager_port}/health", flush=True)
    print(f"[NODE] WebSocket: ws://{cfg.manager_host}:{cfg.manager_port}/ws/events", flush=True)
    if cfg.vr_feedback_enabled:
        print(f"[NODE] VR feedback UDP: {cfg.vr_feedback_host}:{cfg.vr_feedback_port}", flush=True)
    print("[NODE] Backend i LLM uruchamiasz z RemoteGUI.", flush=True)
    uvicorn.run(app, host=cfg.manager_host, port=cfg.manager_port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
