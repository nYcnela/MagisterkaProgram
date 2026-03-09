from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .launch import (
    build_backend_command,
    build_llm_command,
    discover_backend_root,
    extract_feedback_text,
)
from .settings import StudioConfig


def _kill_process_tree(qproc: QProcess) -> None:
    """Kill a QProcess and all its child processes (Windows: taskkill /T /F)."""
    pid = qproc.processId()
    if pid and sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            qproc.kill()
    else:
        qproc.terminate()
        if not qproc.waitForFinished(2000):
            qproc.kill()
    qproc.waitForFinished(1000)


class BackendRunner(QObject):
    started = Signal(str)
    stopped = Signal(int, str)
    log_line = Signal(str)
    error = Signal(str)
    feedback_line = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_ready_read)
        self._process.finished.connect(self._on_finished)
        self._run_id = ""
        self.last_backend_root = ""

    def is_running(self) -> bool:
        return self._process.state() == QProcess.ProcessState.Running

    def build_command(self, cfg: StudioConfig, run_id: str | None = None) -> tuple[str, list[str], str]:
        program, args, resolved_run_id, backend_root = build_backend_command(cfg, run_id=run_id)
        self.last_backend_root = str(backend_root)
        return program, args, resolved_run_id

    def start(self, cfg: StudioConfig) -> bool:
        if self.is_running():
            self.error.emit("Receiver is already running.")
            return False

        try:
            program, args, run_id = self.build_command(cfg)
        except Exception as exc:
            self.error.emit(str(exc))
            return False

        self._run_id = run_id
        self._process.setProgram(program)
        self._process.setArguments(args)
        self._process.start()

        if not self._process.waitForStarted(3000):
            self.error.emit("Failed to start receiver process.")
            return False

        self.started.emit(run_id)
        return True

    def stop(self) -> None:
        if not self.is_running():
            return
        _kill_process_tree(self._process)

    def _on_ready_read(self) -> None:
        payload = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in payload.splitlines():
            self.log_line.emit(line)
            feedback = extract_feedback_text(line)
            if feedback is not None:
                self.feedback_line.emit(feedback)

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self.stopped.emit(exit_code, self._run_id)


class LLMRunner(QObject):
    state_changed = Signal(str, str)  # state, details
    log_line = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_ready_read)
        self._process.finished.connect(self._on_finished)

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(800)
        self._health_timer.timeout.connect(self._poll_health)

        self._host = "127.0.0.1"
        self._port = 8000
        self._state = "STOPPED"

    def is_running(self) -> bool:
        return self._process.state() == QProcess.ProcessState.Running

    def start(self, cfg: StudioConfig) -> bool:
        if self.is_running():
            self.state_changed.emit("READY", "already running")
            return True

        try:
            program, args, _backend_root = build_llm_command(cfg)
            self._host = cfg.llm_host
            self._port = int(cfg.llm_port)

            self._process.setProgram(program)
            self._process.setArguments(args)
            self._process.start()

            if not self._process.waitForStarted(3500):
                raise RuntimeError("Failed to start LLM process.")

            self._state = "STARTING"
            self.state_changed.emit("STARTING", "loading model")
            self._health_timer.start()
            return True

        except Exception as exc:
            self._state = "ERROR"
            self.error.emit(str(exc))
            self.state_changed.emit("ERROR", "start failed")
            return False

    def stop(self) -> None:
        self._health_timer.stop()
        if not self.is_running():
            self._state = "STOPPED"
            self.state_changed.emit("STOPPED", "")
            return

        _kill_process_tree(self._process)

    def _poll_health(self) -> None:
        if not self.is_running():
            self._health_timer.stop()
            return

        url = f"http://{self._host}:{self._port}/health"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=0.4) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            loaded = bool(payload.get("model_loaded", False))
            if loaded and self._state != "READY":
                self._state = "READY"
                self.state_changed.emit("READY", "model loaded")
            elif not loaded and self._state != "STARTING":
                self._state = "STARTING"
                self.state_changed.emit("STARTING", "loading model")
        except urllib.error.URLError:
            if self._state != "STARTING":
                self._state = "STARTING"
                self.state_changed.emit("STARTING", "booting")
        except Exception:
            if self._state != "STARTING":
                self._state = "STARTING"
                self.state_changed.emit("STARTING", "booting")

    def _on_ready_read(self) -> None:
        payload = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in payload.splitlines():
            self.log_line.emit(f"[LLM] {line}")

    def _on_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._health_timer.stop()
        if exit_code == 0:
            self._state = "STOPPED"
            self.state_changed.emit("STOPPED", "")
        else:
            self._state = "ERROR"
            self.state_changed.emit("ERROR", f"exit={exit_code}")
