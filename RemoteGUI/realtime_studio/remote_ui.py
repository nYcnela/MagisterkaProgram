from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .analysis_view import AnalysisFigureWidget
from .remote_client import RemoteNodeClient
from .remote_settings import RemoteGuiConfig, load_remote_gui_config, save_remote_gui_config


DANCE_CHOICES = [
    "k_krok_podstaw_uklon_polonez",
    "k_krok_podstawowy_polonez",
    "k_obrot_uklon_polonez",
    "k_uklon_1takt_polonez",
    "k_uklon_2takty_polonez",
    "m_krok_podstaw_uklon_polonez",
    "m_krok_podstawowy_polonez",
    "m_uklon_1takt_polonez",
    "m_uklon_2takty_polonez",
]


class RemoteMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_remote_gui_config()
        self.client = RemoteNodeClient(self.cfg)
        self._analysis_runs: list[dict[str, Any]] = []
        self._build_ui()
        self._bind_signals()
        self._load_into_widgets()
        self.client.start()

    def _build_ui(self) -> None:
        self.setWindowTitle("Remote Studio")
        self.resize(1480, 920)
        self.setMinimumSize(1180, 760)

        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("HeaderCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 10)
        title = QLabel("Remote Studio")
        title.setObjectName("Title")
        subtitle = QLabel("Zdalny panel sterowania dla ComputeNode")
        subtitle.setObjectName("Subtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root_layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_layout.addWidget(self._tabs_panel(), 1)
        left_layout.addWidget(self._actions_card())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addWidget(self._status_card())
        right_layout.addWidget(self._analysis_card(), 1)
        right_layout.addWidget(self._feedback_card())
        right_layout.addWidget(self._log_card(), 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([560, 880])

    def _tabs_panel(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("ConfigTabs")
        tabs.addTab(self._scroll_tab(self._connection_card()), "Połączenie")
        tabs.addTab(
            self._scroll_tab(
                self._session_card(),
                self._participant_card(),
                self._thresholds_card(),
            ),
            "Sesja",
        )
        tabs.addTab(self._scroll_tab(self._analysis_controls_card()), "Analiza")
        tabs.addTab(self._scroll_tab(self._notes_card()), "Info")
        return tabs

    def _scroll_tab(self, *contents: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(10)
        for content in contents:
            layout.addWidget(content)
        layout.addStretch(1)
        area.setWidget(host)
        return area

    def _card(self, title_text: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        return card, layout

    def _new_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        return form

    def _connection_card(self) -> QWidget:
        card, layout = self._card("ComputeNode")
        form = self._new_form()

        self.node_host_edit = QLineEdit()
        self.node_port_spin = QSpinBox()
        self.node_port_spin.setRange(1, 65535)
        self.auto_connect_check = QCheckBox("Auto-connect przy starcie")

        form.addRow("Host", self.node_host_edit)
        form.addRow("Port", self.node_port_spin)
        form.addRow("", self.auto_connect_check)

        self.node_url_label = QLabel("")
        self.node_url_label.setObjectName("Hint")

        layout.addLayout(form)
        layout.addWidget(self.node_url_label)
        return card

    def _session_card(self) -> QWidget:
        card, layout = self._card("Sterowanie sesją")
        form = self._new_form()

        self.dance_id_combo = QComboBox()
        self.dance_id_combo.setEditable(True)
        self.dance_id_combo.addItems(DANCE_CHOICES)

        self.sequence_name_edit = QLineEdit()
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["female", "male"])
        self.step_type_combo = QComboBox()
        self.step_type_combo.addItems(["step", "static"])

        form.addRow("ID tańca", self.dance_id_combo)
        form.addRow("Nazwa sekwencji", self.sequence_name_edit)
        form.addRow("Płeć", self.gender_combo)
        form.addRow("Typ kroku", self.step_type_combo)

        layout.addLayout(form)
        return card

    def _participant_card(self) -> QWidget:
        card, layout = self._card("Osoba")
        form = self._new_form()

        self.dancer_first_name_edit = QLineEdit()
        self.dancer_first_name_edit.setPlaceholderText("np. Jan")
        self.dancer_last_name_edit = QLineEdit()
        self.dancer_last_name_edit.setPlaceholderText("np. Kowalski")

        form.addRow("Imię", self.dancer_first_name_edit)
        form.addRow("Nazwisko", self.dancer_last_name_edit)

        layout.addLayout(form)
        return card

    def _thresholds_card(self) -> QWidget:
        card, layout = self._card("Progi Live")
        form = self._new_form()

        self.live_z_spin = QDoubleSpinBox()
        self.live_z_spin.setRange(0.0, 10.0)
        self.live_z_spin.setDecimals(2)
        self.live_z_spin.setSingleStep(0.1)

        self.live_order_spin = QSpinBox()
        self.live_order_spin.setRange(0, 1000)

        self.auto_start_llm_check = QCheckBox("Uruchom LLM przed backendem")

        form.addRow("Próg Z", self.live_z_spin)
        form.addRow("Próg kolejności", self.live_order_spin)
        form.addRow("", self.auto_start_llm_check)

        layout.addLayout(form)
        return card

    def _notes_card(self) -> QWidget:
        card, layout = self._card("Tryb pracy")
        hint = QLabel(
            "RemoteGUI jest tylko klientem sterującym.\n"
            "Backend, LLM i dane z Kalmana pracują na ComputeNode.\n"
            "Logi i feedback przychodzą tu przez WebSocket."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return card

    def _analysis_controls_card(self) -> QWidget:
        card, layout = self._card("Analiza runów")

        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self.analysis_dance_filter = QComboBox()
        self.analysis_dance_filter.addItem("Wszystkie tańce", "")
        self.analysis_dance_filter.setMinimumWidth(220)

        self.analysis_person_filter = QLineEdit()
        self.analysis_person_filter.setPlaceholderText("Filtr osoby")

        self.analysis_refresh_btn = QPushButton("Odśwież runy")

        filter_row.addWidget(self.analysis_dance_filter, 1)
        filter_row.addWidget(self.analysis_person_filter, 1)
        layout.addLayout(filter_row)

        self.analysis_runs_list = QListWidget()
        self.analysis_runs_list.setMinimumHeight(250)
        layout.addWidget(self.analysis_runs_list)

        self.analysis_meta_label = QLabel("Wybierz run, aby przygotować analizę.")
        self.analysis_meta_label.setObjectName("Hint")
        self.analysis_meta_label.setWordWrap(True)
        layout.addWidget(self.analysis_meta_label)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(10)
        self.analysis_generate_btn = QPushButton("Generuj wykresy")
        self.analysis_export_png_btn = QPushButton("Eksport PNG")
        self.analysis_export_svg_btn = QPushButton("Eksport SVG")
        self.analysis_export_csv_btn = QPushButton("Eksport CSV")
        self.analysis_export_png_btn.setEnabled(False)
        self.analysis_export_svg_btn.setEnabled(False)
        self.analysis_export_csv_btn.setEnabled(False)

        actions.addWidget(self.analysis_generate_btn, 0, 0)
        actions.addWidget(self.analysis_refresh_btn, 0, 1)
        actions.addWidget(self.analysis_export_png_btn, 1, 0)
        actions.addWidget(self.analysis_export_svg_btn, 1, 1)
        actions.addWidget(self.analysis_export_csv_btn, 2, 0, 1, 2)
        layout.addLayout(actions)
        return card

    def _actions_card(self) -> QFrame:
        card, layout = self._card("Akcje")

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.connect_btn = QPushButton("Połącz")
        self.refresh_btn = QPushButton("Odśwież stan")
        self.start_llm_btn = QPushButton("Uruchom LLM")
        self.stop_llm_btn = QPushButton("Zatrzymaj LLM")
        self.start_backend_btn = QPushButton("Uruchom backend")
        self.stop_backend_btn = QPushButton("Zatrzymaj backend")
        self.start_session_btn = QPushButton("Start sesji")
        self.stop_session_btn = QPushButton("Stop sesji")
        self.save_btn = QPushButton("Zapisz konfigurację")

        grid.addWidget(self.connect_btn, 0, 0)
        grid.addWidget(self.refresh_btn, 0, 1)
        grid.addWidget(self.start_llm_btn, 1, 0)
        grid.addWidget(self.stop_llm_btn, 1, 1)
        grid.addWidget(self.start_backend_btn, 2, 0)
        grid.addWidget(self.stop_backend_btn, 2, 1)
        grid.addWidget(self.start_session_btn, 3, 0)
        grid.addWidget(self.stop_session_btn, 3, 1)
        grid.addWidget(self.save_btn, 4, 0, 1, 2)

        layout.addLayout(grid)
        return card

    def _status_card(self) -> QFrame:
        card, layout = self._card("Status ComputeNode")

        self.node_state_pill = QLabel("OFFLINE")
        self.backend_state_pill = QLabel("STOPPED")
        self.llm_state_pill = QLabel("STOPPED")
        self.run_id_label = QLabel("Run ID: -")
        self.session_label = QLabel("Sesja: -")
        for label in [self.node_state_pill, self.backend_state_pill, self.llm_state_pill]:
            label.setObjectName("StatePill")

        layout.addWidget(QLabel("Połączenie"))
        layout.addWidget(self.node_state_pill)
        layout.addWidget(QLabel("Backend"))
        layout.addWidget(self.backend_state_pill)
        layout.addWidget(QLabel("LLM"))
        layout.addWidget(self.llm_state_pill)
        layout.addWidget(self.run_id_label)
        layout.addWidget(self.session_label)
        return card

    def _feedback_card(self) -> QFrame:
        card, layout = self._card("Ostatnia informacja zwrotna")
        self.feedback_view = QTextEdit()
        self.feedback_view.setReadOnly(True)
        self.feedback_view.setMinimumHeight(110)
        layout.addWidget(self.feedback_view)
        return card

    def _analysis_card(self) -> QFrame:
        card, layout = self._card("Analiza porównawcza")
        self.analysis_chart = AnalysisFigureWidget()
        layout.addWidget(self.analysis_chart, 1)
        return card

    def _log_card(self) -> QFrame:
        card, layout = self._card("Log z K1")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(300)
        layout.addWidget(self.log_view)
        return card

    def _bind_signals(self) -> None:
        self.connect_btn.clicked.connect(self._connect_clicked)
        self.refresh_btn.clicked.connect(self.client.fetch_snapshot)
        self.start_llm_btn.clicked.connect(self.client.start_llm)
        self.stop_llm_btn.clicked.connect(self.client.stop_llm)
        self.start_backend_btn.clicked.connect(self._start_backend_clicked)
        self.stop_backend_btn.clicked.connect(self.client.stop_backend)
        self.start_session_btn.clicked.connect(self._start_session_clicked)
        self.stop_session_btn.clicked.connect(lambda: self.client.stop_session({"reason": "remote_gui"}))
        self.save_btn.clicked.connect(self._save_clicked)
        self.analysis_refresh_btn.clicked.connect(self.client.fetch_analysis_runs)
        self.analysis_generate_btn.clicked.connect(self._analysis_generate_clicked)
        self.analysis_export_png_btn.clicked.connect(self._export_analysis_png)
        self.analysis_export_svg_btn.clicked.connect(self._export_analysis_svg)
        self.analysis_export_csv_btn.clicked.connect(self._export_analysis_csv)
        self.analysis_dance_filter.currentIndexChanged.connect(self._refilter_analysis_runs)
        self.analysis_person_filter.textChanged.connect(self._refilter_analysis_runs)
        self.analysis_runs_list.itemSelectionChanged.connect(self._update_analysis_meta)

        self.client.connection_changed.connect(self._on_connection_changed)
        self.client.snapshot_loaded.connect(self._apply_snapshot)
        self.client.analysis_runs_loaded.connect(self._apply_analysis_runs)
        self.client.analysis_loaded.connect(self._apply_analysis_payload)
        self.client.event_received.connect(self._apply_event)
        self.client.response.connect(self._on_response)
        self.client.error.connect(self._append_error)

    def _collect_cfg(self) -> RemoteGuiConfig:
        return RemoteGuiConfig(
            node_host=self.node_host_edit.text().strip(),
            node_port=int(self.node_port_spin.value()),
            auto_connect=bool(self.auto_connect_check.isChecked()),
            dancer_first_name=self.dancer_first_name_edit.text().strip(),
            dancer_last_name=self.dancer_last_name_edit.text().strip(),
            dance_id=self.dance_id_combo.currentText().strip(),
            sequence_name=self.sequence_name_edit.text().strip(),
            gender=self.gender_combo.currentText(),
            step_type=self.step_type_combo.currentText(),
            live_z_threshold=float(self.live_z_spin.value()),
            live_major_order_threshold=int(self.live_order_spin.value()),
            auto_start_llm=bool(self.auto_start_llm_check.isChecked()),
        )

    def _load_into_widgets(self) -> None:
        self.node_host_edit.setText(self.cfg.node_host)
        self.node_port_spin.setValue(self.cfg.node_port)
        self.auto_connect_check.setChecked(self.cfg.auto_connect)
        self.dancer_first_name_edit.setText(self.cfg.dancer_first_name)
        self.dancer_last_name_edit.setText(self.cfg.dancer_last_name)
        self.dance_id_combo.setCurrentText(self.cfg.dance_id)
        self.sequence_name_edit.setText(self.cfg.sequence_name)
        self.gender_combo.setCurrentText(self.cfg.gender)
        self.step_type_combo.setCurrentText(self.cfg.step_type)
        self.live_z_spin.setValue(self.cfg.live_z_threshold)
        self.live_order_spin.setValue(self.cfg.live_major_order_threshold)
        self.auto_start_llm_check.setChecked(self.cfg.auto_start_llm)
        self.node_url_label.setText(f"API: http://{self.cfg.node_host}:{self.cfg.node_port}")

    def _set_pill(self, label: QLabel, state: str, details: str = "") -> None:
        palette = {
            "OFFLINE": ("#334155", "#e2e8f0"),
            "CONNECTING": ("#0c4a6e", "#bae6fd"),
            "READY": ("#166534", "#dcfce7"),
            "STOPPED": ("#334155", "#e2e8f0"),
            "STARTING": ("#0c4a6e", "#bae6fd"),
            "ERROR": ("#7f1d1d", "#fecaca"),
        }
        bg, fg = palette.get(state, ("#1e293b", "#f8fafc"))
        label.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:11px; padding:4px 10px; font-weight:700;"
        )
        label.setText(state if not details else f"{state} · {details}")

    def _connect_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        self.client.update_config(self.cfg)
        self.node_url_label.setText(f"API: http://{self.cfg.node_host}:{self.cfg.node_port}")
        self.client.connect_node()

    def _start_backend_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        self.client.update_config(self.cfg)
        if self.cfg.auto_start_llm:
            self.client.start_llm()
        self.client.start_backend()

    def _start_session_clicked(self) -> None:
        extra: dict[str, object] = {
            "live_z_threshold": float(self.live_z_spin.value()),
            "live_major_order_threshold": int(self.live_order_spin.value()),
        }
        dancer_first_name = self.dancer_first_name_edit.text().strip()
        dancer_last_name = self.dancer_last_name_edit.text().strip()
        if dancer_first_name:
            extra["dancer_first_name"] = dancer_first_name
        if dancer_last_name:
            extra["dancer_last_name"] = dancer_last_name

        payload = {
            "dance_id": self.dance_id_combo.currentText().strip(),
            "sequence_name": self.sequence_name_edit.text().strip(),
            "gender": self.gender_combo.currentText(),
            "step_type": self.step_type_combo.currentText(),
            "session_id": f"k2_{int(time.time())}",
            "extra": extra,
        }
        self.client.start_session(payload)

    def _save_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self._append_log("[INFO] Zapisano konfigurację.")

    def _on_connection_changed(self, state: str, details: str) -> None:
        self._set_pill(self.node_state_pill, state, details if state != "READY" else "")
        if state == "READY":
            self._append_log(f"[INFO] Połączono z ComputeNode: {details}")
            self.client.fetch_analysis_runs()
        elif state in {"OFFLINE", "ERROR"}:
            self._append_log(f"[WARN] Połączenie z ComputeNode: {state} ({details})")

    def _apply_snapshot(self, snapshot: dict) -> None:
        self._apply_snapshot_like(snapshot)
        self._append_log("[INFO] Odebrano snapshot stanu z ComputeNode.")

    def _apply_event(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        payload = dict(event.get("payload", {}))
        if kind == "log":
            self._append_log(payload.get("line", ""))
        elif kind == "feedback":
            self.feedback_view.setPlainText(str(payload.get("text", "")))
        elif kind == "backend_state":
            self._set_pill(self.backend_state_pill, payload.get("state", "STOPPED"), payload.get("details", ""))
        elif kind == "llm_state":
            self._set_pill(self.llm_state_pill, payload.get("state", "STOPPED"), payload.get("details", ""))
        elif kind == "session_started":
            session_id = payload.get("session_id", "")
            dance_id = payload.get("dance_id", "")
            run_id = payload.get("run_id", "")
            self.session_label.setText(f"Sesja: {session_id or '-'} / {dance_id or '-'}")
            if run_id:
                self.run_id_label.setText(f"Run ID: {run_id}")
        elif kind == "session_stopped":
            self.session_label.setText("Sesja: -")
            self.client.fetch_analysis_runs()

    def _on_response(self, tag: str, payload: dict) -> None:
        if "snapshot" in payload:
            self._apply_snapshot_like(payload["snapshot"])
        elif "backend" in payload or "llm" in payload:
            self._apply_snapshot_like(payload)
        self._append_log(f"[INFO] {tag}")

    def _apply_snapshot_like(self, snapshot: dict) -> None:
        backend = snapshot.get("backend", {})
        llm = snapshot.get("llm", {})
        self._set_pill(self.backend_state_pill, backend.get("state", "STOPPED"), backend.get("details", ""))
        self._set_pill(self.llm_state_pill, llm.get("state", "STOPPED"), llm.get("details", ""))
        self.run_id_label.setText(f"Run ID: {snapshot.get('run_id', '-') or '-'}")
        session_id = snapshot.get("session_id", "") or "-"
        dance_id = snapshot.get("dance_id", "") or "-"
        active = bool(snapshot.get("session_active", False))
        self.session_label.setText(f"Sesja: {session_id} / {dance_id}" if active else "Sesja: -")
        self.feedback_view.setPlainText(str(snapshot.get("last_feedback", "")))

        logs = snapshot.get("recent_logs", [])
        if logs:
            self.log_view.setPlainText("\n".join(logs))
            sb = self.log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _apply_analysis_runs(self, payload: dict) -> None:
        self._analysis_runs = list(payload.get("runs", [])) if isinstance(payload, dict) else []
        current_value = self.analysis_dance_filter.currentData() or ""
        options = sorted({str(item.get("dance_id") or "").strip() for item in self._analysis_runs if item.get("dance_id")})
        self.analysis_dance_filter.blockSignals(True)
        self.analysis_dance_filter.clear()
        self.analysis_dance_filter.addItem("Wszystkie tańce", "")
        for dance_id in options:
            self.analysis_dance_filter.addItem(dance_id, dance_id)
        index = self.analysis_dance_filter.findData(current_value)
        self.analysis_dance_filter.setCurrentIndex(index if index >= 0 else 0)
        self.analysis_dance_filter.blockSignals(False)
        self._refilter_analysis_runs()
        self._append_log(f"[INFO] Odebrano listę runów: {len(self._analysis_runs)}")

    def _refilter_analysis_runs(self) -> None:
        selected_run_id = self._selected_analysis_run_id()
        dance_filter = str(self.analysis_dance_filter.currentData() or "").strip()
        person_filter = self.analysis_person_filter.text().strip().lower()

        self.analysis_runs_list.clear()
        for item in self._analysis_runs:
            dance_id = str(item.get("dance_id") or "").strip()
            dancer_name = str(item.get("dancer_name") or "").strip()
            if dance_filter and dance_id != dance_filter:
                continue
            if person_filter and person_filter not in dancer_name.lower():
                continue
            created_at = str(item.get("created_at") or "-")
            label = f"{created_at} | {dance_id or '-'} | {dancer_name or 'bez osoby'} | {item.get('run_id', '-') }"
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, dict(item))
            self.analysis_runs_list.addItem(row)

        if self.analysis_runs_list.count() == 0:
            self.analysis_meta_label.setText("Brak runów pasujących do filtrów.")
            return

        for idx in range(self.analysis_runs_list.count()):
            row = self.analysis_runs_list.item(idx)
            item = row.data(Qt.ItemDataRole.UserRole) or {}
            if str(item.get("run_id") or "") == selected_run_id:
                self.analysis_runs_list.setCurrentRow(idx)
                break
        else:
            self.analysis_runs_list.setCurrentRow(0)
        self._update_analysis_meta()

    def _selected_analysis_run_id(self) -> str:
        item = self.analysis_runs_list.currentItem()
        if item is None:
            return ""
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        return str(payload.get("run_id") or "")

    def _update_analysis_meta(self) -> None:
        item = self.analysis_runs_list.currentItem()
        if item is None:
            self.analysis_meta_label.setText("Wybierz run, aby przygotować analizę.")
            return
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        self.analysis_meta_label.setText(
            f"Run: {payload.get('run_id', '-')}\n"
            f"Taniec: {payload.get('dance_id', '-')} | Osoba: {payload.get('dancer_name', 'brak')}\n"
            f"Okna: {payload.get('window_count', 0)} | Feedback: {payload.get('feedback_count', 0)}"
        )

    def _analysis_generate_clicked(self) -> None:
        run_id = self._selected_analysis_run_id()
        if not run_id:
            self.analysis_chart.set_message("Najpierw wybierz run z listy.")
            return
        self.analysis_chart.set_message(f"Ładowanie analizy dla {run_id} ...")
        self.client.fetch_analysis_run(run_id)

    def _apply_analysis_payload(self, payload: dict) -> None:
        self.analysis_chart.render_analysis(payload)
        enabled = self.analysis_chart.has_data()
        self.analysis_export_png_btn.setEnabled(enabled)
        self.analysis_export_svg_btn.setEnabled(enabled)
        self.analysis_export_csv_btn.setEnabled(payload is not None)
        run_meta = dict(payload.get("run", {})) if isinstance(payload, dict) else {}
        run_id = run_meta.get("run_id", "-")
        self._append_log(f"[INFO] Wygenerowano analizę dla runu: {run_id}")

    def _export_analysis_png(self) -> None:
        if self.analysis_chart.export_png():
            self._append_log("[INFO] Zapisano wykresy PNG.")

    def _export_analysis_svg(self) -> None:
        if self.analysis_chart.export_svg():
            self._append_log("[INFO] Zapisano wykresy SVG.")

    def _export_analysis_csv(self) -> None:
        if self.analysis_chart.export_csv():
            self._append_log("[INFO] Zapisano dane CSV z analizy.")

    def _append_error(self, message: str) -> None:
        self._append_log(f"[ERROR] {message}")

    def _append_log(self, line: str) -> None:
        if not line:
            return
        self.log_view.append(line)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self.client.stop()
        super().closeEvent(event)

    def debug_dump_config(self) -> dict:
        return asdict(self._collect_cfg())
