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
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
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


def _step_type_for_dance(dance_id: str) -> str:
    return "step" if "krok" in dance_id else "static"


_THEME_MAP = {"Jasny": "light", "Ciemny": "dark"}
_THEME_MAP_REV = {v: k for k, v in _THEME_MAP.items()}

_NAV_ITEMS = [
    ("\u26A1", "Polaczenie"),
    ("\u25B6", "Sesja"),
    ("\u2261", "Analiza"),
    ("\u2139", "Info"),
]


class RemoteMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_remote_gui_config()
        self.client = RemoteNodeClient(self.cfg)
        self._analysis_runs: list[dict[str, Any]] = []
        self._nav_buttons: list[QPushButton] = []
        self._build_ui()
        self._load_into_widgets()
        self._bind_signals()
        self._on_nav_changed(0)
        self.client.start()

    # ── Layout ────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setWindowTitle("Remote Studio")
        self.resize(1400, 860)
        self.setMinimumSize(780, 480)

        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        main_area = QWidget()
        main_layout = QVBoxLayout(main_area)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        main_layout.addWidget(self._build_status_bar())

        # Shared cards — will be reparented between views
        self._feedback_frame = self._feedback_card()
        self._log_frame = self._log_card()

        # View 0: Connection (full-width grid)
        self._conn_view = QWidget()
        self._conn_layout = QVBoxLayout(self._conn_view)
        self._conn_layout.setContentsMargins(0, 0, 0, 0)
        self._conn_layout.setSpacing(8)
        self._conn_top_row = QHBoxLayout()
        self._conn_top_row.setSpacing(8)
        self._conn_controls = self._connection_page()
        self._conn_top_row.addWidget(self._conn_controls, 3)
        # feedback_frame inserted here dynamically (stretch 5)
        self._conn_layout.addLayout(self._conn_top_row)
        # log_frame appended here dynamically

        # View 1: Splitter (for session / analysis / info)
        self._splitter_view = QWidget()
        sv_layout = QVBoxLayout(self._splitter_view)
        sv_layout.setContentsMargins(0, 0, 0, 0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        self.left_content_stack = QStackedWidget()
        self.left_content_stack.addWidget(self._session_page())     # 0
        self.left_content_stack.addWidget(self._analysis_page())    # 1
        self.left_content_stack.addWidget(self._info_page())        # 2

        self._right_default = QWidget()
        self._right_default_layout = QVBoxLayout(self._right_default)
        self._right_default_layout.setContentsMargins(0, 0, 0, 0)
        self._right_default_layout.setSpacing(8)

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._right_default)             # 0
        self.right_stack.addWidget(self._analysis_only_panel())     # 1

        self._splitter.addWidget(self.left_content_stack)
        self._splitter.addWidget(self.right_stack)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 5)
        sv_layout.addWidget(self._splitter)

        # Main content switcher
        self._main_content = QStackedWidget()
        self._main_content.addWidget(self._conn_view)      # 0
        self._main_content.addWidget(self._splitter_view)   # 1
        main_layout.addWidget(self._main_content, 1)

        root_layout.addWidget(main_area, 1)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(56)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(6)

        brand = QLabel("RS")
        brand.setObjectName("BrandLabel")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)
        layout.addSpacing(10)

        for i, (icon, tooltip) in enumerate(_NAV_ITEMS):
            btn = QPushButton(icon)
            btn.setObjectName("NavBtn")
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self._on_nav_changed(idx))
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
            self._nav_buttons.append(btn)

        layout.addStretch(1)

        self.save_btn = QPushButton("\u2193")
        self.save_btn.setObjectName("NavBtn")
        self.save_btn.setToolTip("Zapisz konfiguracje")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignCenter)

        return sidebar

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(44)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        self.node_state_dot = QLabel()
        self.node_state_text = QLabel("OFFLINE")
        self.backend_state_dot = QLabel()
        self.backend_state_text = QLabel("STOPPED")
        self.llm_state_dot = QLabel()
        self.llm_state_text = QLabel("STOPPED")

        for dot in (self.node_state_dot, self.backend_state_dot, self.llm_state_dot):
            dot.setFixedSize(8, 8)

        for label_text, dot, text in [
            ("Node", self.node_state_dot, self.node_state_text),
            ("Backend", self.backend_state_dot, self.backend_state_text),
            ("LLM", self.llm_state_dot, self.llm_state_text),
        ]:
            lbl = QLabel(label_text)
            lbl.setObjectName("StatusLabel")
            text.setObjectName("StatusLabel")
            layout.addWidget(lbl)
            layout.addWidget(dot)
            layout.addWidget(text)
            layout.addSpacing(4)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: rgba(140,170,214,40);")
        sep.setFixedWidth(1)
        layout.addWidget(sep)
        layout.addSpacing(2)

        self.run_id_label = QLabel("Run: -")
        self.run_id_label.setObjectName("StatusMeta")
        self.run_id_label.setWordWrap(False)
        self.session_label = QLabel("Sesja: -")
        self.session_label.setObjectName("StatusMeta")
        self.session_label.setWordWrap(False)

        layout.addWidget(self.run_id_label, 1)
        layout.addWidget(self.session_label, 1)

        return bar

    # ── Pages ─────────────────────────────────────────────

    def _scroll_page(self, *contents: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(10)
        for w in contents:
            layout.addWidget(w)
        layout.addStretch(1)
        area.setWidget(host)
        return area

    def _connection_page(self) -> QFrame:
        card, layout = self._card("Polaczenie z ComputeNode")
        form = self._new_form()

        self.node_host_edit = QLineEdit()
        self.node_port_spin = QSpinBox()
        self.node_port_spin.setRange(1, 65535)
        self.auto_connect_check = QCheckBox("Auto-connect przy starcie")

        form.addRow("Host", self.node_host_edit)
        form.addRow("Port", self.node_port_spin)
        form.addRow("", self.auto_connect_check)
        layout.addLayout(form)

        self.node_url_label = QLabel("")
        self.node_url_label.setObjectName("Hint")
        layout.addWidget(self.node_url_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.connect_btn = QPushButton("Polacz")
        self.connect_btn.setObjectName("AccentBtn")
        self.refresh_btn = QPushButton("Odswiez stan")
        self.refresh_btn.setObjectName("SubtleBtn")
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.refresh_btn)
        layout.addLayout(btn_row)

        layout.addStretch(1)

        return card

    def _session_page(self) -> QScrollArea:
        # LLM card
        llm_card, llm_layout = self._card("LLM")
        self.auto_start_llm_check = QCheckBox("Auto-start z backendem")
        llm_layout.addWidget(self.auto_start_llm_check)
        llm_btns = QHBoxLayout()
        llm_btns.setSpacing(8)
        self.start_llm_btn = QPushButton("Uruchom LLM")
        self.start_llm_btn.setObjectName("AccentBtn")
        self.stop_llm_btn = QPushButton("Zatrzymaj LLM")
        self.stop_llm_btn.setObjectName("DangerBtn")
        llm_btns.addWidget(self.start_llm_btn)
        llm_btns.addWidget(self.stop_llm_btn)
        llm_layout.addLayout(llm_btns)

        # Session control card
        session_card, session_layout = self._card("Parametry sesji")
        form = self._new_form()
        self.dance_id_combo = self._styled_combo()
        self.dance_id_combo.setEditable(False)
        self.dance_id_combo.addItems(DANCE_CHOICES)
        self.sequence_name_edit = QLineEdit()
        self.gender_combo = self._styled_combo()
        self.gender_combo.addItems(["female", "male"])
        self.gender_combo.setMaxVisibleItems(10)
        form.addRow("ID tanca", self.dance_id_combo)
        form.addRow("Sekwencja", self.sequence_name_edit)
        form.addRow("Plec", self.gender_combo)
        session_layout.addLayout(form)

        # Participant card
        part_card, part_layout = self._card("Osoba")
        pform = self._new_form()
        self.dancer_first_name_edit = QLineEdit()
        self.dancer_first_name_edit.setPlaceholderText("np. Jan")
        self.dancer_last_name_edit = QLineEdit()
        self.dancer_last_name_edit.setPlaceholderText("np. Kowalski")
        pform.addRow("Imie", self.dancer_first_name_edit)
        pform.addRow("Nazwisko", self.dancer_last_name_edit)
        part_layout.addLayout(pform)

        # Thresholds card
        thresh_card, thresh_layout = self._card("Progi Live")
        tform = self._new_form()
        self.live_z_spin = QDoubleSpinBox()
        self.live_z_spin.setRange(0.0, 10.0)
        self.live_z_spin.setDecimals(2)
        self.live_z_spin.setSingleStep(0.1)
        self.live_order_spin = QSpinBox()
        self.live_order_spin.setRange(0, 1000)
        tform.addRow("Prog Z", self.live_z_spin)
        tform.addRow("Prog kolejnosci", self.live_order_spin)
        thresh_layout.addLayout(tform)

        # Actions card
        actions_card, actions_layout = self._card("Uruchom")
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.start_backend_btn = QPushButton("Start backend")
        self.start_backend_btn.setObjectName("AccentBtn")
        self.stop_backend_btn = QPushButton("Stop backend")
        self.stop_backend_btn.setObjectName("DangerBtn")
        row1.addWidget(self.start_backend_btn)
        row1.addWidget(self.stop_backend_btn)
        actions_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.start_session_btn = QPushButton("Start sesji")
        self.start_session_btn.setObjectName("AccentBtn")
        self.stop_session_btn = QPushButton("Stop sesji")
        self.stop_session_btn.setObjectName("DangerBtn")
        row2.addWidget(self.start_session_btn)
        row2.addWidget(self.stop_session_btn)
        actions_layout.addLayout(row2)

        return self._scroll_page(llm_card, session_card, part_card, thresh_card, actions_card)

    def _analysis_page(self) -> QScrollArea:
        card, layout = self._card("Analiza runow")

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.analysis_dance_filter = self._styled_combo()
        self.analysis_dance_filter.addItem("Wszystkie tance", "")
        self.analysis_dance_filter.setMinimumWidth(120)
        self.analysis_person_filter = QLineEdit()
        self.analysis_person_filter.setPlaceholderText("Filtr osoby")
        self.analysis_theme_combo = self._styled_combo()
        self.analysis_theme_combo.addItem("Jasny")
        self.analysis_theme_combo.addItem("Ciemny")
        self.analysis_theme_combo.setMaxVisibleItems(10)
        filter_row.addWidget(self.analysis_dance_filter, 1)
        filter_row.addWidget(self.analysis_person_filter, 1)
        filter_row.addWidget(self.analysis_theme_combo)
        layout.addLayout(filter_row)

        self.analysis_runs_list = QListWidget()
        self.analysis_runs_list.setMinimumHeight(100)
        layout.addWidget(self.analysis_runs_list, 1)

        self.analysis_meta_label = QLabel("Wybierz run, aby przygotowac analize.")
        self.analysis_meta_label.setObjectName("Hint")
        self.analysis_meta_label.setWordWrap(True)
        layout.addWidget(self.analysis_meta_label)

        btn_grid = QGridLayout()
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(8)
        self.analysis_generate_btn = QPushButton("Generuj wykresy")
        self.analysis_generate_btn.setObjectName("AccentBtn")
        self.analysis_refresh_btn = QPushButton("Odswiez runy")
        self.analysis_refresh_btn.setObjectName("SubtleBtn")
        self.analysis_export_png_btn = QPushButton("PNG")
        self.analysis_export_png_btn.setObjectName("SubtleBtn")
        self.analysis_export_png_btn.setEnabled(False)
        self.analysis_export_svg_btn = QPushButton("SVG")
        self.analysis_export_svg_btn.setObjectName("SubtleBtn")
        self.analysis_export_svg_btn.setEnabled(False)
        self.analysis_export_csv_btn = QPushButton("CSV")
        self.analysis_export_csv_btn.setObjectName("SubtleBtn")
        self.analysis_export_csv_btn.setEnabled(False)

        btn_grid.addWidget(self.analysis_generate_btn, 0, 0)
        btn_grid.addWidget(self.analysis_refresh_btn, 0, 1)
        btn_grid.addWidget(self.analysis_export_png_btn, 1, 0)
        btn_grid.addWidget(self.analysis_export_svg_btn, 1, 1)
        btn_grid.addWidget(self.analysis_export_csv_btn, 1, 2)
        layout.addLayout(btn_grid)

        return self._scroll_page(card)

    def _info_page(self) -> QScrollArea:
        card, layout = self._card("Tryb pracy")
        hint = QLabel(
            "RemoteGUI jest tylko klientem sterujacym.\n"
            "Backend, LLM i dane z Kalmana pracuja na ComputeNode.\n"
            "Logi i feedback przychodza tu przez WebSocket."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return self._scroll_page(card)

    # ── Right panel ───────────────────────────────────────

    def _analysis_only_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._analysis_chart_card(), 1)
        return panel

    def _feedback_card(self) -> QFrame:
        card, layout = self._card("Feedback")
        self.feedback_view = QTextEdit()
        self.feedback_view.setReadOnly(True)
        self.feedback_view.setMinimumHeight(50)
        layout.addWidget(self.feedback_view)
        return card

    def _log_card(self) -> QFrame:
        card, layout = self._card("Log")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(60)
        layout.addWidget(self.log_view)
        return card

    def _analysis_chart_card(self) -> QFrame:
        card, layout = self._card("Analiza porownawcza")
        self.analysis_chart = AnalysisFigureWidget()
        layout.addWidget(self.analysis_chart, 1)
        return card

    # ── Helpers ────────────────────────────────────────────

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

    @staticmethod
    def _styled_combo() -> QComboBox:
        combo = QComboBox()
        view = QListView()
        view.setMouseTracking(True)
        combo.setView(view)
        return combo

    # ── Navigation ────────────────────────────────────────

    def _on_nav_changed(self, index: int) -> None:
        for i, btn in enumerate(self._nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if index == 0:
            # Connection view: feedback beside connection, log below both
            self._conn_top_row.addWidget(self._feedback_frame, 5)
            self._conn_layout.addWidget(self._log_frame, 1)
            self._main_content.setCurrentIndex(0)
        elif index == 2:
            # Analysis: controls left, chart right (no feedback/log visible)
            self.left_content_stack.setCurrentIndex(1)
            self.right_stack.setCurrentIndex(1)
            self._main_content.setCurrentIndex(1)
        else:
            # Session (1) / Info (3): controls left, feedback+log right
            self._right_default_layout.addWidget(self._feedback_frame)
            self._right_default_layout.addWidget(self._log_frame)
            self._right_default_layout.setStretch(
                self._right_default_layout.indexOf(self._feedback_frame), 1
            )
            self._right_default_layout.setStretch(
                self._right_default_layout.indexOf(self._log_frame), 2
            )
            stack_idx = 0 if index == 1 else 2
            self.left_content_stack.setCurrentIndex(stack_idx)
            self.right_stack.setCurrentIndex(0)
            self._main_content.setCurrentIndex(1)
            # Restore splitter proportions after reparenting
            total = self._splitter.width() or 800
            self._splitter.setSizes([total * 3 // 8, total * 5 // 8])

    # ── Signals ───────────────────────────────────────────

    def _bind_signals(self) -> None:
        self.connect_btn.clicked.connect(self._connect_clicked)
        self.refresh_btn.clicked.connect(self.client.fetch_snapshot)
        self.start_llm_btn.clicked.connect(self._start_llm_clicked)
        self.stop_llm_btn.clicked.connect(self._stop_llm_clicked)
        self.start_backend_btn.clicked.connect(self._start_backend_clicked)
        self.stop_backend_btn.clicked.connect(self._stop_backend_clicked)
        self.start_session_btn.clicked.connect(self._start_session_clicked)
        self.stop_session_btn.clicked.connect(self._stop_session_clicked)
        self.save_btn.clicked.connect(self._save_clicked)
        self.analysis_refresh_btn.clicked.connect(self.client.fetch_analysis_runs)
        self.analysis_generate_btn.clicked.connect(self._analysis_generate_clicked)
        self.analysis_export_png_btn.clicked.connect(self._export_analysis_png)
        self.analysis_export_svg_btn.clicked.connect(self._export_analysis_svg)
        self.analysis_export_csv_btn.clicked.connect(self._export_analysis_csv)
        self.analysis_dance_filter.currentIndexChanged.connect(self._refilter_analysis_runs)
        self.analysis_person_filter.textChanged.connect(self._refilter_analysis_runs)
        self.analysis_runs_list.itemSelectionChanged.connect(self._update_analysis_meta)
        self.analysis_theme_combo.currentIndexChanged.connect(self._analysis_theme_changed)

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
            step_type=_step_type_for_dance(self.dance_id_combo.currentText()),
            live_z_threshold=float(self.live_z_spin.value()),
            live_major_order_threshold=int(self.live_order_spin.value()),
            analysis_chart_theme=_THEME_MAP.get(self.analysis_theme_combo.currentText(), "dark"),
            auto_start_llm=bool(self.auto_start_llm_check.isChecked()),
        )

    def _load_into_widgets(self) -> None:
        self.node_host_edit.setText(self.cfg.node_host)
        self.node_port_spin.setValue(self.cfg.node_port)
        self.auto_connect_check.setChecked(self.cfg.auto_connect)
        self.dancer_first_name_edit.setText(self.cfg.dancer_first_name)
        self.dancer_last_name_edit.setText(self.cfg.dancer_last_name)
        idx = self.dance_id_combo.findText(self.cfg.dance_id)
        if idx >= 0:
            self.dance_id_combo.setCurrentIndex(idx)
        self.sequence_name_edit.setText(self.cfg.sequence_name)
        idx = self.gender_combo.findText(self.cfg.gender)
        if idx >= 0:
            self.gender_combo.setCurrentIndex(idx)
        self.live_z_spin.setValue(self.cfg.live_z_threshold)
        self.live_order_spin.setValue(self.cfg.live_major_order_threshold)
        self.analysis_theme_combo.blockSignals(True)
        theme_label = _THEME_MAP_REV.get(self.cfg.analysis_chart_theme, "Jasny")
        self.analysis_theme_combo.setCurrentText(theme_label)
        self.analysis_theme_combo.blockSignals(False)
        self.auto_start_llm_check.setChecked(self.cfg.auto_start_llm)
        self.node_url_label.setText(f"API: http://{self.cfg.node_host}:{self.cfg.node_port}")
        self.analysis_chart.set_theme(self.cfg.analysis_chart_theme)

    # ── Pill helper ───────────────────────────────────────

    def _set_pill(self, dot: QLabel, text_label: QLabel, state: str, details: str = "") -> None:
        dot_colors = {
            "OFFLINE": "#475569",
            "CONNECTING": "#38bdf8",
            "READY": "#4ade80",
            "STOPPED": "#475569",
            "STARTING": "#38bdf8",
            "ERROR": "#f87171",
        }
        color = dot_colors.get(state, "#475569")
        dot.setStyleSheet(
            f"background:{color}; border-radius:4px;"
        )
        text_label.setText(state if not details else f"{state} \u00b7 {details}")

    # ── Button handlers ───────────────────────────────────

    def _connect_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        self.client.update_config(self.cfg)
        self.node_url_label.setText(f"API: http://{self.cfg.node_host}:{self.cfg.node_port}")
        self.client.connect_node()

    def _start_llm_clicked(self) -> None:
        self._set_pill(self.llm_state_dot, self.llm_state_text, "STARTING", "sending request...")
        self.client.start_llm()

    def _stop_llm_clicked(self) -> None:
        self._set_pill(self.llm_state_dot, self.llm_state_text, "STOPPED", "stopping...")
        self.client.stop_llm()

    def _start_backend_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        self.client.update_config(self.cfg)
        self._set_pill(self.backend_state_dot, self.backend_state_text, "STARTING", "sending request...")
        if self.cfg.auto_start_llm:
            self._set_pill(self.llm_state_dot, self.llm_state_text, "STARTING", "sending request...")
        self.client.start_backend()

    def _stop_backend_clicked(self) -> None:
        self._set_pill(self.backend_state_dot, self.backend_state_text, "STOPPED", "stopping...")
        self.client.stop_backend()

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
            "step_type": _step_type_for_dance(self.dance_id_combo.currentText()),
            "session_id": f"k2_{int(time.time())}",
            "extra": extra,
        }
        self.client.start_session(payload)

    def _stop_session_clicked(self) -> None:
        self.session_label.setText("Sesja: (stopping...)")
        self.client.stop_session({"reason": "remote_gui"})

    def _save_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self._append_log("[INFO] Zapisano konfiguracje.")

    # ── Event handlers ────────────────────────────────────

    def _on_connection_changed(self, state: str, details: str) -> None:
        self._set_pill(self.node_state_dot, self.node_state_text, state, details if state != "READY" else "")
        if state == "READY":
            self._append_log(f"[INFO] Polaczono z ComputeNode: {details}")
            self.client.fetch_analysis_runs()
        elif state in {"OFFLINE", "ERROR"}:
            self._append_log(f"[WARN] Polaczenie z ComputeNode: {state} ({details})")

    def _apply_snapshot(self, snapshot: dict) -> None:
        self._apply_snapshot_like(snapshot)
        self._append_log("[INFO] Odebrano snapshot stanu z ComputeNode.")

    def _apply_event(self, event: dict) -> None:
        kind = str(event.get("type", ""))
        payload = dict(event.get("payload", {}))
        if kind == "log":
            self._append_log(payload.get("line", ""))
        elif kind == "feedback":
            new_text = str(payload.get("text", ""))
            if new_text.strip():
                ts = time.strftime("%H:%M:%S")
                existing = self.feedback_view.toPlainText().strip()
                header = f"── {ts} ──"
                if existing:
                    self.feedback_view.setPlainText(f"{header}\n{new_text}\n\n{existing}")
                else:
                    self.feedback_view.setPlainText(f"{header}\n{new_text}")
                sb = self.feedback_view.verticalScrollBar()
                sb.setValue(sb.minimum())
        elif kind == "backend_state":
            self._set_pill(self.backend_state_dot, self.backend_state_text, payload.get("state", "STOPPED"), payload.get("details", ""))
        elif kind == "llm_state":
            self._set_pill(self.llm_state_dot, self.llm_state_text, payload.get("state", "STOPPED"), payload.get("details", ""))
        elif kind == "session_prepared":
            run_id = payload.get("run_id", "")
            dance_id = payload.get("dance_id", "")
            if run_id:
                self.run_id_label.setText(f"Run: {run_id}")
            if dance_id:
                self.session_label.setText(f"Sesja: (prepare) / {dance_id}")
        elif kind == "session_started":
            session_id = payload.get("session_id", "")
            dance_id = payload.get("dance_id", "")
            run_id = payload.get("run_id", "")
            self.session_label.setText(f"Sesja: {session_id or '-'} / {dance_id or '-'}")
            if run_id:
                self.run_id_label.setText(f"Run: {run_id}")
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
        self._set_pill(self.backend_state_dot, self.backend_state_text, backend.get("state", "STOPPED"), backend.get("details", ""))
        self._set_pill(self.llm_state_dot, self.llm_state_text, llm.get("state", "STOPPED"), llm.get("details", ""))
        self.run_id_label.setText(f"Run: {snapshot.get('run_id', '-') or '-'}")
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

    # ── Analysis ──────────────────────────────────────────

    def _apply_analysis_runs(self, payload: dict) -> None:
        self._analysis_runs = list(payload.get("runs", [])) if isinstance(payload, dict) else []
        current_value = self.analysis_dance_filter.currentData() or ""
        options = sorted({str(item.get("dance_id") or "").strip() for item in self._analysis_runs if item.get("dance_id")})
        self.analysis_dance_filter.blockSignals(True)
        self.analysis_dance_filter.clear()
        self.analysis_dance_filter.addItem("Wszystkie tance", "")
        for dance_id in options:
            self.analysis_dance_filter.addItem(dance_id, dance_id)
        index = self.analysis_dance_filter.findData(current_value)
        self.analysis_dance_filter.setCurrentIndex(index if index >= 0 else 0)
        self.analysis_dance_filter.blockSignals(False)
        self._refilter_analysis_runs()
        self._append_log(f"[INFO] Odebrano liste runow: {len(self._analysis_runs)}")

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
            label = f"{created_at} | {dance_id or '-'} | {dancer_name or 'bez osoby'} | {item.get('run_id', '-')}"
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, dict(item))
            self.analysis_runs_list.addItem(row)

        if self.analysis_runs_list.count() == 0:
            self.analysis_meta_label.setText("Brak runow pasujacych do filtrow.")
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
            self.analysis_meta_label.setText("Wybierz run, aby przygotowac analize.")
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
        self.analysis_chart.set_message(f"Ladowanie analizy dla {run_id} ...")
        self.client.fetch_analysis_run(run_id)

    def _apply_analysis_payload(self, payload: dict) -> None:
        self.analysis_chart.set_theme(_THEME_MAP.get(self.analysis_theme_combo.currentText(), "dark"))
        self.analysis_chart.render_analysis(payload)
        enabled = self.analysis_chart.has_data()
        self.analysis_export_png_btn.setEnabled(enabled)
        self.analysis_export_svg_btn.setEnabled(enabled)
        self.analysis_export_csv_btn.setEnabled(payload is not None)
        run_meta = dict(payload.get("run", {})) if isinstance(payload, dict) else {}
        run_id = run_meta.get("run_id", "-")
        self._append_log(f"[INFO] Wygenerowano analize dla runu: {run_id}")

    def _export_analysis_png(self) -> None:
        if self.analysis_chart.export_png():
            self._append_log("[INFO] Zapisano wykresy PNG.")

    def _export_analysis_svg(self) -> None:
        if self.analysis_chart.export_svg():
            self._append_log("[INFO] Zapisano wykresy SVG.")

    def _export_analysis_csv(self) -> None:
        if self.analysis_chart.export_csv():
            self._append_log("[INFO] Zapisano dane CSV z analizy.")

    def _analysis_theme_changed(self) -> None:
        theme = _THEME_MAP.get(self.analysis_theme_combo.currentText(), "dark")
        self.analysis_chart.set_theme(theme)

    # ── Log / Error ───────────────────────────────────────

    def _append_error(self, message: str) -> None:
        self._append_log(f"[ERROR] {message}")

    def _append_log(self, line: str) -> None:
        if not line:
            return
        self.log_view.append(line)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Lifecycle ─────────────────────────────────────────

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self.client.stop()
        super().closeEvent(event)

    def debug_dump_config(self) -> dict:
        return asdict(self._collect_cfg())
