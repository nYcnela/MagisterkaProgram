from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Tuple
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

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


def _looks_like_backend_root(root: Path) -> bool:
    return (
        (root / "apps/realtime/run_udp_e2e_test.py").exists()
        and (root / "apps/realtime/llm_server.py").exists()
    )


def _app_anchor_dir() -> Path:
    """
    Base dir for relative path resolution.
    - source run: .../realtime_studio/
    - frozen app: directory with executable
    """
    if getattr(sys, "frozen", False):  # type: ignore[attr-defined]
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _read_backend_hint(anchor: Path) -> Path | None:
    """
    Optional one-line hint file with backend root path.
    Supported names:
      - .realtime_studio_backend_root
      - realtime_studio.backend_root
    Relative value is resolved against hint file directory.
    """
    hint_names = (".realtime_studio_backend_root", "realtime_studio.backend_root")
    search_dirs = (anchor, anchor.parent)
    for d in search_dirs:
        for name in hint_names:
            hint = d / name
            if not hint.exists():
                continue
            try:
                raw = hint.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if not raw:
                continue
            p = Path(os.path.expandvars(raw)).expanduser()
            if not p.is_absolute():
                p = (hint.parent / p).resolve()
            return p
    return None


def _embedded_backend_candidates(anchor: Path) -> list[Path]:
    return [
        anchor / "backend_embedded",
        anchor / "backend_runtime",
        anchor / "backend_runtime" / "Magisterka",
        anchor.parent / "backend_embedded",
        anchor.parent / "backend_runtime",
        anchor.parent / "backend_runtime" / "Magisterka",
    ]


def discover_backend_root(explicit_root: str = "") -> Path:
    candidates: list[Path] = []
    seen: set[str] = set()
    anchor = _app_anchor_dir()

    def add(path: Path | str | None, *, base: Path | None = None) -> None:
        if not path:
            return
        p = Path(os.path.expandvars(str(path))).expanduser()
        if not p.is_absolute() and base is not None:
            p = (base / p).resolve()
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        candidates.append(p)

    explicit = explicit_root.strip()
    if explicit:
        add(explicit)
        add(explicit, base=anchor)

    env_root = os.getenv("REALTIME_STUDIO_BACKEND_ROOT", "").strip()
    if env_root:
        add(env_root)
        add(env_root, base=anchor)

    hint_root = _read_backend_hint(anchor)
    if hint_root is not None:
        add(hint_root)

    # Prefer embedded/backend bundle next to app.
    for c in _embedded_backend_candidates(anchor):
        add(c)

    cwd = Path.cwd()
    add(cwd)
    for p in cwd.parents:
        add(p)

    here = Path(__file__).resolve()
    add(here.parent)
    for p in here.parents:
        add(p)

    # Prefer deterministic relative-to-app candidates first.
    add(anchor)
    add(anchor.parent)
    add(anchor / "Magisterka")
    add(anchor.parent / "Magisterka")
    add(anchor.parent.parent if anchor.parent != anchor.parent.parent else None)
    add(anchor.parent.parent / "Magisterka")

    # Common local locations.
    home = Path.home()
    add(home / "PycharmProjects" / "Magisterka")
    add(home / "Nextcloud" / "Studia" / "Magisterka")

    # Also try sibling Magisterka folder from each candidate.
    expanded: list[Path] = []
    for c in candidates:
        expanded.append(c)
        expanded.append(c / "Magisterka")

    for c in expanded:
        root = c.resolve()
        if _looks_like_backend_root(root):
            return root

    raise FileNotFoundError(
        "Could not auto-detect backend root. "
        "Set REALTIME_STUDIO_BACKEND_ROOT, or create .realtime_studio_backend_root "
        "next to app with a relative path like ../Magisterka."
    )


def _resolve_under_root(path_like: str, root: Path) -> Path:
    p = Path(path_like)
    if p.is_absolute():
        return p
    return (root / p).resolve()


def _extract_feedback_text(line: str) -> str | None:
    marker = "[FEEDBACK]"
    if marker not in line:
        return None
    return line.split(marker, 1)[1].strip()


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

    def build_command(self, cfg: StudioConfig, run_id: str | None = None) -> Tuple[str, list[str], str]:
        run_id = run_id or datetime.now().strftime("studio_%Y%m%d_%H%M%S")

        backend_root = discover_backend_root(cfg.backend_root)
        self.last_backend_root = str(backend_root)

        output_root = _resolve_under_root(cfg.output_root, backend_root)
        candidate_root = _resolve_under_root(cfg.candidate_root, backend_root)
        offline_runs_root = _resolve_under_root(cfg.offline_runs_root, backend_root)

        if cfg.session_mode:
            # --- Tryb sesyjny: nasłuch 5006, VR steruje sesjami ---
            script = backend_root / "apps/realtime/run_udp_controlled_session.py"
            if not script.exists():
                raise FileNotFoundError(f"Missing session script: {script}")

            args: list[str] = [
                str(script),
                "--control-host", str(cfg.udp_host),
                "--control-port", str(cfg.udp_control_port),
                "--udp-host", str(cfg.udp_host),
                "--udp-port", str(cfg.udp_data_port),
                "--input-hz", str(cfg.input_hz),
                "--window-seconds", str(cfg.window_seconds),
                "--stride-seconds", str(cfg.stride_seconds),
                "--duration-seconds", str(cfg.duration_seconds),
                "--max-windows", str(cfg.max_windows),
                "--gender", str(cfg.gender),
                "--step-type", str(cfg.step_type),
                "--sequence-name", str(cfg.sequence_name),
                "--output-root", str(output_root),
                "--candidate-root", str(candidate_root),
                "--offline-runs-root", str(offline_runs_root),
                "--live-z-threshold", str(cfg.live_z_threshold),
                "--live-major-order-threshold", str(cfg.live_major_order_threshold),
            ]
            if cfg.live_emit_minor_order_text:
                args.append("--live-emit-minor-order-text")
            if cfg.llm_enabled:
                args.extend(["--llm-url", f"http://{cfg.llm_host}:{cfg.llm_port}"])
        else:
            # --- Tryb ręczny: klasyczny start receivera ---
            script = backend_root / "apps/realtime/run_udp_e2e_test.py"
            if not script.exists():
                raise FileNotFoundError(f"Missing receiver script: {script}")

            pattern_file = _resolve_under_root(cfg.resolved_pattern_file(), backend_root)
            if not pattern_file.exists():
                raise FileNotFoundError(f"Missing pattern file: {pattern_file}")

            args = [
                str(script),
                "--udp-host", str(cfg.udp_host),
                "--udp-port", str(cfg.udp_data_port),
                "--input-hz", str(cfg.input_hz),
                "--window-seconds", str(cfg.window_seconds),
                "--stride-seconds", str(cfg.stride_seconds),
                "--duration-seconds", str(cfg.duration_seconds),
                "--max-windows", str(cfg.max_windows),
                "--sequence-name", str(cfg.sequence_name),
                "--gender", str(cfg.gender),
                "--step-type", str(cfg.step_type),
                "--pattern-file", str(pattern_file),
                "--model-inputs-only",
                "--output-root", str(output_root),
                "--candidate-root", str(candidate_root),
                "--offline-runs-root", str(offline_runs_root),
                "--run-id", run_id,
                "--live-z-threshold", str(cfg.live_z_threshold),
                "--live-major-order-threshold", str(cfg.live_major_order_threshold),
            ]
            if cfg.live_emit_minor_order_text:
                args.append("--live-emit-minor-order-text")
            if cfg.llm_enabled:
                args.extend(["--llm-url", f"http://{cfg.llm_host}:{cfg.llm_port}"])

        program = cfg.python_exec.strip() or sys.executable
        # -u = unbuffered stdout so QProcess receives print() output in real time
        args.insert(0, "-u")
        return program, args, run_id

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
            feedback = _extract_feedback_text(line)
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
            backend_root = discover_backend_root(cfg.backend_root)
            script = backend_root / "apps/realtime/llm_server.py"
            if not script.exists():
                raise FileNotFoundError(f"Missing LLM server script: {script}")

            adapter_dir = _resolve_under_root(cfg.llm_adapter_dir, backend_root)
            if not adapter_dir.exists():
                raise FileNotFoundError(f"Missing adapter dir: {adapter_dir}")

            args = [
                "-u",
                str(script),
                "--adapter-dir",
                str(adapter_dir),
                "--host",
                str(cfg.llm_host),
                "--port",
                str(cfg.llm_port),
            ]
            if cfg.llm_model_id.strip():
                args.extend(["--model-id", cfg.llm_model_id.strip()])
            if not cfg.llm_use_4bit:
                args.append("--no-4bit")

            program = cfg.python_exec.strip() or sys.executable
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
