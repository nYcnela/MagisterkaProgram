from __future__ import annotations

import json
import threading
from urllib import error, request
from urllib.parse import quote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

from .remote_settings import RemoteGuiConfig


class RemoteNodeClient(QObject):
    snapshot_loaded = Signal(object)
    analysis_runs_loaded = Signal(object)
    analysis_loaded = Signal(object)
    event_received = Signal(object)
    connection_changed = Signal(str, str)
    error = Signal(str)
    response = Signal(str, object)

    def __init__(self, cfg: RemoteGuiConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._ws = QWebSocket()
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_disconnected)
        self._ws.textMessageReceived.connect(self._on_message)
        self._ws.errorOccurred.connect(self._on_error)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(800)
        self._reconnect_timer.timeout.connect(self._ensure_connected)

        self._connected = False
        self._connecting = False

    def update_config(self, cfg: RemoteGuiConfig) -> None:
        self.cfg = cfg

    def start(self) -> None:
        if self.cfg.auto_connect:
            self.connect_node()
        self._reconnect_timer.start()

    def stop(self) -> None:
        self._reconnect_timer.stop()
        self._ws.abort()

    def connect_node(self) -> None:
        if self._connected or self._connecting:
            return
        self._connecting = True
        self.connection_changed.emit("CONNECTING", self.base_url())
        self._ws.open(QUrl(self.ws_url()))

    def fetch_snapshot(self) -> None:
        self._request_json("GET", "/snapshot", None, "snapshot")

    def start_llm(self) -> None:
        self._request_json("POST", "/llm/start", {}, "llm_start")

    def stop_llm(self) -> None:
        self._request_json("POST", "/llm/stop", {}, "llm_stop")

    def start_backend(self) -> None:
        self._request_json("POST", "/backend/start", {}, "backend_start")

    def stop_backend(self) -> None:
        self._request_json("POST", "/backend/stop", {}, "backend_stop")

    def start_session(self, payload: dict) -> None:
        self._request_json("POST", "/session/start", payload, "session_start")

    def prepare_session(self, payload: dict) -> None:
        self._request_json("POST", "/session/prepare", payload, "session_prepare")

    def stop_session(self, payload: dict | None = None) -> None:
        self._request_json("POST", "/session/stop", payload or {"reason": "remote_gui"}, "session_stop")

    def replay_run(self, payload: dict) -> None:
        self._request_json("POST", "/simulation/replay-run", payload, "simulation_replay_run")

    def set_dancer(self, first_name: str, last_name: str) -> None:
        self._request_json("POST", "/dancer/set", {"dancer_first_name": first_name, "dancer_last_name": last_name}, "set_dancer")

    def apply_live_thresholds(self, live_z_threshold: float, live_major_order_threshold: int) -> None:
        self._request_json(
            "POST",
            "/live-thresholds",
            {
                "live_z_threshold": float(live_z_threshold),
                "live_major_order_threshold": int(live_major_order_threshold),
            },
            "live_thresholds",
        )

    def fetch_analysis_runs(self) -> None:
        self._request_json("GET", "/analysis/runs", None, "analysis_runs")

    def fetch_analysis_run(self, run_id: str) -> None:
        encoded = quote(run_id, safe="")
        self._request_json("GET", f"/analysis/run/{encoded}", None, "analysis_run")

    def base_url(self) -> str:
        return f"http://{self.cfg.node_host}:{self.cfg.node_port}"

    def ws_url(self) -> str:
        return f"ws://{self.cfg.node_host}:{self.cfg.node_port}/ws/events"

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        self.connect_node()

    def _on_connected(self) -> None:
        self._connected = True
        self._connecting = False
        self.connection_changed.emit("READY", self.base_url())
        self.fetch_snapshot()

    def _on_disconnected(self) -> None:
        self._connected = False
        self._connecting = False
        self.connection_changed.emit("OFFLINE", self.base_url())

    def _on_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except Exception as exc:
            self.error.emit(f"Invalid WS payload: {exc}")
            return
        self.event_received.emit(payload)

    def _on_error(self, _code) -> None:
        self._connected = False
        self._connecting = False
        self.connection_changed.emit("ERROR", self.base_url())

    def _request_json(self, method: str, path: str, payload: dict | None, tag: str) -> None:
        def worker() -> None:
            url = f"{self.base_url()}{path}"
            body = None
            headers = {}
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            req = request.Request(url, data=body, headers=headers, method=method)
            timeout = 6.0 if method == "POST" else 3.0
            try:
                with request.urlopen(req, timeout=timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            except error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8")
                except Exception:
                    detail = str(exc)
                self.error.emit(f"{method} {path} -> {exc.code}: {detail}")
                return
            except Exception as exc:
                self.error.emit(f"{method} {path} failed: {exc}")
                return

            if tag == "snapshot":
                self.snapshot_loaded.emit(result)
            elif tag == "analysis_runs":
                self.analysis_runs_loaded.emit(result)
            elif tag == "analysis_run":
                self.analysis_loaded.emit(result)
            else:
                self.response.emit(tag, result)

        threading.Thread(target=worker, daemon=True, name=f"remote-{tag}").start()
