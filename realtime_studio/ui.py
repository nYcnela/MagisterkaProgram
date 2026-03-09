from __future__ import annotations

import re
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .backend import BackendRunner, LLMRunner, discover_backend_root
from .settings import StudioConfig, load_config, save_config


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

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(value: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.split(value.lower()) if tok}


def infer_dance_id(sequence_name: str, gender: str, step_type: str) -> str | None:
    seq = sequence_name.strip().lower()
    if not seq:
        return None

    for dance in DANCE_CHOICES:
        if dance == seq or dance in seq:
            if gender and dance.startswith(gender[:1].lower() + "_"):
                return dance
    for dance in DANCE_CHOICES:
        if dance == seq or dance in seq:
            return dance

    seq_tokens = _tokenize(seq)
    if not seq_tokens:
        return None

    best: tuple[int, int, str] | None = None
    for dance in DANCE_CHOICES:
        dance_tokens = _tokenize(dance)
        common = len(seq_tokens & dance_tokens)
        if common == 0:
            continue

        score = common * 4
        if gender and dance.startswith(gender[:1].lower() + "_"):
            score += 2

        is_turn = "obrot" in dance
        if step_type == "static":
            score += 2 if is_turn else -1
        else:
            score += 1 if not is_turn else -1

        candidate = (score, len(dance_tokens), dance)
        if best is None or candidate > best:
            best = candidate

    if best is None or best[0] < 4:
        return None
    return best[2]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.runner = BackendRunner()
        self.llm_runner = LLMRunner()

        self._pending_receiver_start = False
        self._detected_backend_root: Path | None = None

        self._build_ui()
        self._bind_signals()
        self._load_into_widgets()
        self._refresh_backend_root_view()
        self._refresh_pattern_preview()
        self._refresh_command_preview()

    def _build_ui(self) -> None:
        self.setWindowTitle("Realtime Studio")
        self.resize(1520, 940)
        self.setMinimumSize(1220, 760)

        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("HeaderCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 10)
        header_layout.setSpacing(2)
        title = QLabel("Realtime Studio")
        title.setObjectName("Title")
        subtitle = QLabel("Live UDP + LLM control center for Polonaise pipeline")
        subtitle.setObjectName("Subtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root_layout.addWidget(header)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(12)
        root_layout.addWidget(self.main_splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)
        left_layout.addWidget(self._tabs_panel(), 1)
        left_layout.addWidget(self._actions_card())

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setHandleWidth(10)

        right_top = QWidget()
        right_top_layout = QVBoxLayout(right_top)
        right_top_layout.setContentsMargins(0, 0, 0, 0)
        right_top_layout.setSpacing(10)
        right_top_layout.addWidget(self._status_card())
        right_top_layout.addWidget(self._last_feedback_card())
        right_top_layout.addWidget(self._command_card(), 1)

        right_splitter.addWidget(right_top)
        right_splitter.addWidget(self._log_card())
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 3)

        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(right_splitter)
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 5)
        self.main_splitter.setSizes([620, 900])

    def _tabs_panel(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("ConfigTabs")

        tab_connection = QWidget()
        tab_connection_layout = QVBoxLayout(tab_connection)
        tab_connection_layout.setContentsMargins(0, 2, 0, 0)
        tab_connection_layout.setSpacing(10)
        tab_connection_layout.addWidget(self._backend_card())
        tab_connection_layout.addWidget(self._network_card())
        tab_connection_layout.addWidget(self._llm_card())
        tab_connection_layout.addStretch(1)

        tab_session = QWidget()
        tab_session_layout = QVBoxLayout(tab_session)
        tab_session_layout.setContentsMargins(0, 2, 0, 0)
        tab_session_layout.setSpacing(10)
        tab_session_layout.addWidget(self._session_card())
        tab_session_layout.addWidget(self._tuning_card())
        tab_session_layout.addStretch(1)

        tab_workflow = QWidget()
        tab_workflow_layout = QVBoxLayout(tab_workflow)
        tab_workflow_layout.setContentsMargins(0, 2, 0, 0)
        tab_workflow_layout.setSpacing(10)
        workflow_card, workflow_layout = self._card("Workflow")
        workflow_hint = QLabel(
            "1) Kliknij Start LLM (lub zostaw Auto-start LLM).\n"
            "2) Ustaw Session params i Start Receiver.\n"
            "3) Podgląd READY dla LLM i Backend.\n"
            "4) Feedback i log pojawią się live."
        )
        workflow_hint.setObjectName("Hint")
        workflow_hint.setWordWrap(True)
        workflow_layout.addWidget(workflow_hint)
        tab_workflow_layout.addWidget(workflow_card)
        tab_workflow_layout.addStretch(1)

        tabs.addTab(tab_connection, "Connection")
        tabs.addTab(tab_session, "Session")
        tabs.addTab(tab_workflow, "Guide")
        return tabs

    def _new_form(self) -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        return form

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

    def _backend_card(self) -> QFrame:
        card, layout = self._card("Backend")
        form = self._new_form()

        self.backend_root_view = QLineEdit()
        self.backend_root_view.setReadOnly(True)
        self.backend_root_view.setPlaceholderText("Auto-detecting backend...")

        rescan_btn = QPushButton("Rescan")
        rescan_btn.clicked.connect(self._refresh_backend_root_view)

        root_row = QHBoxLayout()
        root_row.setSpacing(8)
        root_row.addWidget(self.backend_root_view, 1)
        root_row.addWidget(rescan_btn)

        root_host = QWidget()
        root_host.setLayout(root_row)

        self.python_exec_view = QLineEdit(sys.executable)
        self.python_exec_view.setReadOnly(True)

        form.addRow("Backend root (auto)", root_host)
        form.addRow("Python exec", self.python_exec_view)

        self.pattern_preview = QLabel("")
        self.pattern_preview.setObjectName("Hint")
        self.pattern_preview.setWordWrap(True)

        layout.addLayout(form)
        layout.addWidget(self.pattern_preview)
        return card

    def _network_card(self) -> QFrame:
        card, layout = self._card("Network")
        form = self._new_form()

        self.udp_host_edit = QLineEdit()
        self.udp_data_port_spin = QSpinBox()
        self.udp_data_port_spin.setRange(1, 65535)
        self.udp_control_port_spin = QSpinBox()
        self.udp_control_port_spin.setRange(1, 65535)
        self.auto_control_port_check = QCheckBox("Control port = Data port + 1")

        self.llm_enabled_check = QCheckBox("Send to LLM")
        self.llm_host_edit = QLineEdit()
        self.llm_port_spin = QSpinBox()
        self.llm_port_spin.setRange(1, 65535)

        form.addRow("UDP host", self.udp_host_edit)
        form.addRow("UDP data port", self.udp_data_port_spin)
        form.addRow("UDP control port", self.udp_control_port_spin)
        form.addRow("", self.auto_control_port_check)
        form.addRow("", self.llm_enabled_check)
        form.addRow("LLM host", self.llm_host_edit)
        form.addRow("LLM port", self.llm_port_spin)
        layout.addLayout(form)
        return card

    def _llm_card(self) -> QFrame:
        card, layout = self._card("LLM Runtime")
        form = self._new_form()

        self.llm_adapter_edit = QLineEdit()
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_adapter_dir)

        adapter_row = QHBoxLayout()
        adapter_row.setSpacing(8)
        adapter_row.addWidget(self.llm_adapter_edit, 1)
        adapter_row.addWidget(browse_btn)

        adapter_host = QWidget()
        adapter_host.setLayout(adapter_row)

        self.llm_use_4bit_check = QCheckBox("Use 4-bit quantization")
        self.llm_model_id_edit = QLineEdit()
        self.llm_model_id_edit.setPlaceholderText("(optional override)")
        self.llm_auto_start_check = QCheckBox("Auto-start LLM when starting receiver")

        form.addRow("Adapter dir", adapter_host)
        form.addRow("Model id", self.llm_model_id_edit)
        form.addRow("", self.llm_use_4bit_check)
        form.addRow("", self.llm_auto_start_check)

        layout.addLayout(form)
        return card

    def _session_card(self) -> QFrame:
        card, layout = self._card("Session")
        form = self._new_form()

        self.dance_id_combo = QComboBox()
        self.dance_id_combo.setEditable(True)
        self.dance_id_combo.addItems(DANCE_CHOICES)

        self.auto_dance_check = QCheckBox("Auto-detect dance from sequence name")
        self.auto_dance_check.setChecked(True)
        self.detected_dance_label = QLabel("Detected dance: -")
        self.detected_dance_label.setObjectName("Hint")
        self.detected_dance_label.setWordWrap(True)

        self.sequence_name_edit = QLineEdit()
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["female", "male"])
        self.step_type_combo = QComboBox()
        self.step_type_combo.addItems(["step", "static"])

        self.input_hz_spin = QDoubleSpinBox()
        self.input_hz_spin.setRange(1.0, 300.0)
        self.input_hz_spin.setSingleStep(1.0)

        self.window_sec_spin = QDoubleSpinBox()
        self.window_sec_spin.setRange(1.0, 20.0)
        self.window_sec_spin.setSingleStep(0.5)

        self.stride_sec_spin = QDoubleSpinBox()
        self.stride_sec_spin.setRange(0.1, 20.0)
        self.stride_sec_spin.setSingleStep(0.5)

        self.duration_sec_spin = QDoubleSpinBox()
        self.duration_sec_spin.setRange(0.0, 3600.0)
        self.duration_sec_spin.setSingleStep(5.0)

        self.max_windows_spin = QSpinBox()
        self.max_windows_spin.setRange(0, 100000)

        form.addRow("Dance id", self.dance_id_combo)
        form.addRow("", self.auto_dance_check)
        form.addRow("", self.detected_dance_label)
        form.addRow("Sequence name", self.sequence_name_edit)
        form.addRow("Gender", self.gender_combo)
        form.addRow("Step type", self.step_type_combo)
        form.addRow("Input Hz", self.input_hz_spin)
        form.addRow("Window seconds", self.window_sec_spin)
        form.addRow("Stride seconds", self.stride_sec_spin)
        form.addRow("Duration seconds", self.duration_sec_spin)
        form.addRow("Max windows", self.max_windows_spin)
        layout.addLayout(form)
        return card

    def _tuning_card(self) -> QFrame:
        card, layout = self._card("Live Tuning")
        form = self._new_form()

        self.live_z_spin = QDoubleSpinBox()
        self.live_z_spin.setRange(0.1, 5.0)
        self.live_z_spin.setSingleStep(0.1)

        self.live_order_spin = QSpinBox()
        self.live_order_spin.setRange(1, 100)

        self.live_minor_check = QCheckBox("Emit 'minor deviations' text")

        form.addRow("Z threshold", self.live_z_spin)
        form.addRow("Major order threshold", self.live_order_spin)
        form.addRow("", self.live_minor_check)

        layout.addLayout(form)
        return card

    def _actions_card(self) -> QFrame:
        card, layout = self._card("Actions")

        self.session_mode_check = QCheckBox("Session mode (5006 control)")
        self.session_mode_check.setToolTip(
            "ON: czeka na session_start z VR na porcie 5006\n"
            "OFF: ręczny start receivera (tryb testowy)"
        )
        layout.addWidget(self.session_mode_check)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.start_btn = QPushButton("Start Receiver")
        self.stop_btn = QPushButton("Stop Receiver")
        self.stop_btn.setEnabled(False)

        self.start_llm_btn = QPushButton("Start LLM")
        self.stop_llm_btn = QPushButton("Stop LLM")
        self.stop_llm_btn.setEnabled(False)

        self.save_btn = QPushButton("Save Profile")
        self.reload_btn = QPushButton("Reload Profile")

        grid.addWidget(self.start_btn, 0, 0)
        grid.addWidget(self.stop_btn, 0, 1)
        grid.addWidget(self.start_llm_btn, 1, 0)
        grid.addWidget(self.stop_llm_btn, 1, 1)
        grid.addWidget(self.save_btn, 2, 0)
        grid.addWidget(self.reload_btn, 2, 1)
        layout.addLayout(grid)

        hint = QLabel("Tip: LLM status 'READY' oznacza, że model jest już w pamięci i można startować receiver.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return card

    def _status_card(self) -> QFrame:
        card, layout = self._card("Runtime Status")

        b_row = QHBoxLayout()
        b_row.setSpacing(8)
        b_label = QLabel("Backend")
        b_label.setObjectName("Hint")
        self.backend_state_pill = QLabel("STOPPED")
        self.backend_state_pill.setObjectName("StatePill")
        self.backend_boot_bar = QProgressBar()
        self.backend_boot_bar.setObjectName("BootBar")
        self.backend_boot_bar.setTextVisible(False)
        self.backend_boot_bar.setRange(0, 0)
        self.backend_boot_bar.setVisible(False)
        b_row.addWidget(b_label)
        b_row.addWidget(self.backend_state_pill)
        b_row.addWidget(self.backend_boot_bar, 1)

        l_row = QHBoxLayout()
        l_row.setSpacing(8)
        l_label = QLabel("LLM")
        l_label.setObjectName("Hint")
        self.llm_state_pill = QLabel("STOPPED")
        self.llm_state_pill.setObjectName("StatePill")
        self.llm_boot_bar = QProgressBar()
        self.llm_boot_bar.setObjectName("BootBar")
        self.llm_boot_bar.setTextVisible(False)
        self.llm_boot_bar.setRange(0, 0)
        self.llm_boot_bar.setVisible(False)
        l_row.addWidget(l_label)
        l_row.addWidget(self.llm_state_pill)
        l_row.addWidget(self.llm_boot_bar, 1)

        self.run_id_label = QLabel("Run id: -")
        self.run_id_label.setObjectName("Hint")

        layout.addLayout(b_row)
        layout.addLayout(l_row)
        layout.addWidget(self.run_id_label)

        self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "STOPPED", "")
        self._set_component_state(self.llm_state_pill, self.llm_boot_bar, "STOPPED", "")
        return card

    def _last_feedback_card(self) -> QFrame:
        card, layout = self._card("Last Feedback")
        self.feedback_view = QTextEdit()
        self.feedback_view.setReadOnly(True)
        self.feedback_view.setMinimumHeight(105)
        layout.addWidget(self.feedback_view)
        return card

    def _command_card(self) -> QFrame:
        card, layout = self._card("Command Preview")
        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setMinimumHeight(120)
        self.command_preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.command_preview)
        return card

    def _log_card(self) -> QFrame:
        card, layout = self._card("Live Log")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(260)
        layout.addWidget(self.log_view)
        return card

    def _bind_signals(self) -> None:
        self.start_btn.clicked.connect(self._start_clicked)
        self.stop_btn.clicked.connect(self.runner.stop)
        self.start_llm_btn.clicked.connect(self._start_llm_clicked)
        self.stop_llm_btn.clicked.connect(self.llm_runner.stop)
        self.save_btn.clicked.connect(self._save_clicked)
        self.reload_btn.clicked.connect(self._reload_clicked)

        self.runner.started.connect(self._on_runner_started)
        self.runner.stopped.connect(self._on_runner_stopped)
        self.runner.log_line.connect(self._append_log)
        self.runner.error.connect(self._on_runner_error)
        self.runner.feedback_line.connect(self.feedback_view.setPlainText)

        self.llm_runner.state_changed.connect(self._on_llm_state_changed)
        self.llm_runner.log_line.connect(self._append_log)
        self.llm_runner.error.connect(self._on_llm_error)

        self.udp_data_port_spin.valueChanged.connect(self._sync_control_port)

        watched = [
            self.udp_host_edit,
            self.llm_host_edit,
            self.sequence_name_edit,
            self.dance_id_combo.lineEdit(),
            self.llm_adapter_edit,
            self.llm_model_id_edit,
        ]
        for w in watched:
            w.textChanged.connect(self._refresh_command_preview)

        spin_watched = [
            self.udp_data_port_spin,
            self.udp_control_port_spin,
            self.llm_port_spin,
            self.input_hz_spin,
            self.window_sec_spin,
            self.stride_sec_spin,
            self.duration_sec_spin,
            self.max_windows_spin,
            self.live_z_spin,
            self.live_order_spin,
        ]
        for s in spin_watched:
            s.valueChanged.connect(self._refresh_command_preview)

        for c in [
            self.gender_combo,
            self.step_type_combo,
            self.dance_id_combo,
        ]:
            c.currentTextChanged.connect(self._on_dance_or_mode_changed)

        self.sequence_name_edit.textChanged.connect(self._on_dance_or_mode_changed)
        self.auto_dance_check.toggled.connect(self._on_dance_or_mode_changed)

        for c in [
            self.llm_enabled_check,
            self.live_minor_check,
            self.auto_control_port_check,
            self.llm_use_4bit_check,
            self.llm_auto_start_check,
            self.session_mode_check,
        ]:
            c.toggled.connect(self._refresh_command_preview)

    def _set_component_state(
        self,
        pill: QLabel,
        boot_bar: QProgressBar,
        state: str,
        details: str,
    ) -> None:
        palette = {
            "STOPPED": ("#334155", "#e2e8f0"),
            "STARTING": ("#0c4a6e", "#bae6fd"),
            "RUNNING": ("#166534", "#dcfce7"),
            "READY": ("#166534", "#dcfce7"),
            "ERROR": ("#7f1d1d", "#fecaca"),
        }
        bg, fg = palette.get(state, ("#1e293b", "#f8fafc"))
        pill.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:11px; padding:4px 10px; font-weight:700;"
        )
        txt = state if not details else f"{state} · {details}"
        pill.setText(txt)
        boot_bar.setVisible(state == "STARTING")

    def _resolve_dance_id(self) -> tuple[str, str]:
        fallback = self.dance_id_combo.currentText().strip() or DANCE_CHOICES[0]
        if not self.auto_dance_check.isChecked():
            return fallback, "manual"

        detected = infer_dance_id(
            self.sequence_name_edit.text(),
            self.gender_combo.currentText(),
            self.step_type_combo.currentText(),
        )
        if detected:
            return detected, "auto"
        return fallback, "fallback"

    def _refresh_backend_root_view(self) -> None:
        try:
            root = discover_backend_root(self.cfg.backend_root)
            self._detected_backend_root = root
            self.backend_root_view.setText(str(root))
            self.backend_root_view.setToolTip(str(root))
        except Exception as exc:
            self._detected_backend_root = None
            self.backend_root_view.setText("backend not found")
            self.backend_root_view.setToolTip(str(exc))
            self._append_log(f"[WARN] {exc}")

        self._refresh_pattern_preview()
        self._refresh_command_preview()

    def _on_dance_or_mode_changed(self) -> None:
        self.dance_id_combo.setEnabled(not self.auto_dance_check.isChecked())
        self._refresh_pattern_preview()
        self._refresh_command_preview()

    def _refresh_pattern_preview(self) -> None:
        cfg = self._collect_from_widgets()
        dance_id, source = self._resolve_dance_id()
        self.detected_dance_label.setText(f"Detected dance: {dance_id} ({source})")
        self.pattern_preview.setText(f"Pattern: {cfg.resolved_pattern_file()}")

    def _sync_control_port(self) -> None:
        if self.auto_control_port_check.isChecked():
            self.udp_control_port_spin.setValue(min(65535, self.udp_data_port_spin.value() + 1))
        self._refresh_command_preview()

    def _collect_from_widgets(self) -> StudioConfig:
        resolved_dance_id, _ = self._resolve_dance_id()
        backend_root = str(self._detected_backend_root) if self._detected_backend_root else self.cfg.backend_root

        cfg = StudioConfig(
            backend_root=backend_root,
            python_exec=sys.executable,
            udp_host=self.udp_host_edit.text().strip(),
            udp_data_port=int(self.udp_data_port_spin.value()),
            udp_control_port=int(self.udp_control_port_spin.value()),
            llm_enabled=bool(self.llm_enabled_check.isChecked()),
            llm_host=self.llm_host_edit.text().strip(),
            llm_port=int(self.llm_port_spin.value()),
            input_hz=float(self.input_hz_spin.value()),
            window_seconds=float(self.window_sec_spin.value()),
            stride_seconds=float(self.stride_sec_spin.value()),
            duration_seconds=float(self.duration_sec_spin.value()),
            max_windows=int(self.max_windows_spin.value()),
            dance_id=resolved_dance_id,
            sequence_name=self.sequence_name_edit.text().strip(),
            gender=self.gender_combo.currentText(),
            step_type=self.step_type_combo.currentText(),
            live_z_threshold=float(self.live_z_spin.value()),
            live_major_order_threshold=int(self.live_order_spin.value()),
            live_emit_minor_order_text=bool(self.live_minor_check.isChecked()),
            output_root=self.cfg.output_root,
            candidate_root=self.cfg.candidate_root,
            offline_runs_root=self.cfg.offline_runs_root,
            pattern_file=self.cfg.pattern_file,
            auto_control_port=bool(self.auto_control_port_check.isChecked()),
            auto_detect_dance=bool(self.auto_dance_check.isChecked()),
            llm_adapter_dir=self.llm_adapter_edit.text().strip(),
            llm_model_id=self.llm_model_id_edit.text().strip(),
            llm_use_4bit=bool(self.llm_use_4bit_check.isChecked()),
            auto_start_llm=bool(self.llm_auto_start_check.isChecked()),
            session_mode=bool(self.session_mode_check.isChecked()),
        )
        return cfg

    def _load_into_widgets(self) -> None:
        c = self.cfg

        self.python_exec_view.setText(sys.executable)
        self.udp_host_edit.setText(c.udp_host)
        self.udp_data_port_spin.setValue(c.udp_data_port)
        self.udp_control_port_spin.setValue(c.udp_control_port)
        self.auto_control_port_check.setChecked(c.auto_control_port)
        self.llm_enabled_check.setChecked(c.llm_enabled)
        self.llm_host_edit.setText(c.llm_host)
        self.llm_port_spin.setValue(c.llm_port)

        self.llm_adapter_edit.setText(c.llm_adapter_dir)
        self.llm_model_id_edit.setText(c.llm_model_id)
        self.llm_use_4bit_check.setChecked(c.llm_use_4bit)
        self.llm_auto_start_check.setChecked(c.auto_start_llm)

        self.input_hz_spin.setValue(c.input_hz)
        self.window_sec_spin.setValue(c.window_seconds)
        self.stride_sec_spin.setValue(c.stride_seconds)
        self.duration_sec_spin.setValue(c.duration_seconds)
        self.max_windows_spin.setValue(c.max_windows)

        self.dance_id_combo.setCurrentText(c.dance_id)
        self.auto_dance_check.setChecked(getattr(c, "auto_detect_dance", True))

        self.sequence_name_edit.setText(c.sequence_name)
        self.gender_combo.setCurrentText(c.gender)
        self.step_type_combo.setCurrentText(c.step_type)
        self.live_z_spin.setValue(c.live_z_threshold)
        self.live_order_spin.setValue(c.live_major_order_threshold)
        self.live_minor_check.setChecked(c.live_emit_minor_order_text)

        self.session_mode_check.setChecked(getattr(c, "session_mode", True))

        self.dance_id_combo.setEnabled(not self.auto_dance_check.isChecked())

    def _save_clicked(self) -> None:
        self.cfg = self._collect_from_widgets()
        save_config(self.cfg)
        self._append_log("[INFO] Profile saved.")

    def _reload_clicked(self) -> None:
        self.cfg = load_config()
        self._load_into_widgets()
        self._refresh_backend_root_view()
        self._refresh_pattern_preview()
        self._refresh_command_preview()
        self._append_log("[INFO] Profile reloaded.")

    def _refresh_command_preview(self) -> None:
        cfg = self._collect_from_widgets()
        try:
            program, args, run_id = self.runner.build_command(cfg, run_id="preview_run")
            preview = " ".join([program, *args])
            self.command_preview.setPlainText(preview)
            self.run_id_label.setText(f"Run id (next): {run_id}")
        except Exception as exc:
            self.command_preview.setPlainText(str(exc))

    def _browse_adapter_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select LoRA adapter directory")
        if selected:
            self.llm_adapter_edit.setText(selected)
            self._refresh_command_preview()

    def _start_llm_clicked(self) -> None:
        self.cfg = self._collect_from_widgets()
        save_config(self.cfg)

        if self.llm_runner.start(self.cfg):
            self.start_llm_btn.setEnabled(False)
            self.stop_llm_btn.setEnabled(True)
            self._set_component_state(self.llm_state_pill, self.llm_boot_bar, "STARTING", "booting")

    def _start_receiver_now(self) -> None:
        if self.runner.start(self.cfg):
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "STARTING", "booting")

    def _start_clicked(self) -> None:
        self.cfg = self._collect_from_widgets()
        save_config(self.cfg)

        if self.cfg.llm_enabled and self.cfg.auto_start_llm and not self.llm_runner.is_running():
            started = self.llm_runner.start(self.cfg)
            if not started:
                return
            self.start_llm_btn.setEnabled(False)
            self.stop_llm_btn.setEnabled(True)
            self._set_component_state(self.llm_state_pill, self.llm_boot_bar, "STARTING", "booting")

            self._pending_receiver_start = True
            self.start_btn.setEnabled(False)
            self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "STARTING", "waiting LLM")
            self._append_log("[INFO] Waiting for LLM READY before starting receiver...")
            return

        self._start_receiver_now()

    def _on_runner_started(self, run_id: str) -> None:
        self.run_id_label.setText(f"Run id: {run_id}")
        self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "READY", "live")
        self._append_log(f"[INFO] Receiver started. run_id={run_id}")

    def _on_runner_stopped(self, exit_code: int, run_id: str) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        state = "STOPPED" if exit_code == 0 else "ERROR"
        details = "" if exit_code == 0 else f"exit={exit_code}"
        self._set_component_state(self.backend_state_pill, self.backend_boot_bar, state, details)
        self._append_log(f"[INFO] Receiver stopped. run_id={run_id} exit_code={exit_code}")

    def _on_runner_error(self, message: str) -> None:
        self._pending_receiver_start = False
        self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "ERROR", "start failed")
        self._append_log(f"[ERROR] {message}")
        QMessageBox.critical(self, "Realtime Studio", message)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def _on_llm_state_changed(self, state: str, details: str) -> None:
        self._set_component_state(self.llm_state_pill, self.llm_boot_bar, state, details)

        if state == "READY":
            self.start_llm_btn.setEnabled(False)
            self.stop_llm_btn.setEnabled(True)
            if self._pending_receiver_start:
                self._pending_receiver_start = False
                self._start_receiver_now()

        elif state == "STARTING":
            self.start_llm_btn.setEnabled(False)
            self.stop_llm_btn.setEnabled(True)

        elif state == "STOPPED":
            self.start_llm_btn.setEnabled(True)
            self.stop_llm_btn.setEnabled(False)
            if self._pending_receiver_start:
                self._pending_receiver_start = False
                self.start_btn.setEnabled(True)
                self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "STOPPED", "")

        elif state == "ERROR":
            self.start_llm_btn.setEnabled(True)
            self.stop_llm_btn.setEnabled(False)
            if self._pending_receiver_start:
                self._pending_receiver_start = False
                self.start_btn.setEnabled(True)
                self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "ERROR", "LLM failed")

    def _on_llm_error(self, message: str) -> None:
        self._append_log(f"[ERROR] {message}")

    def _append_log(self, line: str) -> None:
        # Fallback status sync from runtime logs (helps when Qt start signal timing differs per platform).
        if line.startswith("[INFO] Receiver started."):
            self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "READY", "live")
        elif line.startswith("[INFO] Waiting for LLM READY"):
            self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "STARTING", "waiting LLM")
        elif line.startswith("[INFO] Capture UDP on"):
            self._set_component_state(self.backend_state_pill, self.backend_boot_bar, "STARTING", "capturing")

        self.log_view.append(line)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.cfg = self._collect_from_widgets()
        save_config(self.cfg)
        self._pending_receiver_start = False
        self.runner.stop()
        self.llm_runner.stop()
        super().closeEvent(event)

    def debug_dump_config(self) -> dict:
        return asdict(self._collect_from_widgets())
