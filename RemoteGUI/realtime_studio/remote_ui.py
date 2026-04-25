from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any

from PySide6.QtCore import Qt, QRect, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPaintEvent
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
    QSizePolicy,
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


class _SeqDiagram(QWidget):
    """Sequence diagram: VR → RemoteGUI → ComputeNode session flow."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(520)

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()

        C = {
            "C1":     QColor("#0f2744"),
            "C2":     QColor("#0f2a1a"),
            "C3":     QColor("#2a1a2a"),
            "border": QColor("#334155"),
            "life":   QColor("#334155"),
            "arrow":  QColor("#38bdf8"),
            "data":   QColor("#4ade80"),
            "fb":     QColor("#fb923c"),
            "end":    QColor("#f87171"),
            "hdr":    QColor("#e2e8f0"),
            "tag":    QColor("#64748b"),
            "txt":    QColor("#94a3b8"),
            "sep":    QColor("#1e293b"),
        }

        x3 = int(W * 0.13)
        x1 = int(W * 0.50)
        x2 = int(W * 0.87)

        BW, BH, BY = 118, 46, 8

        def box(cx: int, ck: str, tag: str, name: str) -> None:
            bx = cx - BW // 2
            p.setPen(QPen(C["border"], 1))
            p.setBrush(QBrush(C[ck]))
            p.drawRoundedRect(bx, BY, BW, BH, 5, 5)
            p.setPen(C["tag"])
            p.setFont(QFont("Arial", 7))
            p.drawText(bx + 8, BY + 14, tag)
            p.setPen(C["hdr"])
            p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            p.drawText(bx + 8, BY + 32, name)

        box(x3, "C3", "KOMPUTER 3", "VR klient")
        box(x1, "C1", "KOMPUTER 1", "RemoteGUI")
        box(x2, "C2", "KOMPUTER 2", "ComputeNode")

        life_y0 = BY + BH
        p.setPen(QPen(C["life"], 1, Qt.PenStyle.DashLine))
        for cx in (x3, x1, x2):
            p.drawLine(cx, life_y0, cx, H - 8)

        def arrow(y: int, fx: int, tx: int, label: str, sub: str, ck: str) -> None:
            col = C[ck]
            right = tx > fx
            p.setPen(QPen(col, 1))
            p.setBrush(QBrush(col))
            p.drawLine(fx, y, tx, y)
            d = 6 if right else -6
            p.drawPolygon(QPolygon([QPoint(tx, y), QPoint(tx - d, y - 3), QPoint(tx - d, y + 3)]))
            mid = (fx + tx) // 2
            p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            p.setPen(col)
            p.drawText(mid - 44, y - 5, label)
            p.setFont(QFont("Arial", 7))
            p.setPen(C["txt"])
            p.drawText(mid - 44, y + 13, sub)

        def activity(y: int, cx: int, label: str, ck: str) -> None:
            aw = 88
            p.setPen(QPen(C["border"], 1))
            p.setBrush(QBrush(C[ck]))
            p.drawRoundedRect(cx - aw // 2, y - 11, aw, 22, 4, 4)
            p.setPen(C["hdr"])
            p.setFont(QFont("Arial", 8))
            fm = p.fontMetrics()
            p.drawText(cx - fm.horizontalAdvance(label) // 2, y + 4, label)

        def separator(y: int, label: str) -> None:
            p.setPen(QPen(C["sep"], 1, Qt.PenStyle.SolidLine))
            p.drawLine(12, y, W - 12, y)
            p.setFont(QFont("Arial", 7))
            p.setPen(C["tag"])
            p.drawText(14, y - 3, label)

        y = life_y0 + 24
        S = 42

        arrow(y, x3, x1, "session_prepare", "UDP",            "arrow"); y += S
        arrow(y, x3, x2, "session_prepare", "UDP",            "arrow"); y += S
        activity(y, x3, "3 · 2 · 1 · 0",   "C3");                       y += S
        arrow(y, x1, x2, "session_start",   "HTTP → UDP 5006","arrow"); y += S

        separator(y, "– sesja aktywna –"); y += 16

        arrow(y, x1, x2, "dane ruchu",  "UDP 5005  (100 Hz)", "data"); y += S
        arrow(y, x2, x1, "feedback",    "WS 8010",            "fb");   y += S
        arrow(y, x2, x3, "feedback",    "UDP 5007",           "fb");   y += S

        separator(y, "– koniec sesji –"); y += 16

        arrow(y, x3, x2, "session_end",  "UDP",               "end");  y += S
        arrow(y, x2, x3, "summary",      "avg score  UDP 5007","fb")

        p.end()


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
        self._main_content.addWidget(self._splitter_view)  # 1
        self._main_content.addWidget(self._info_page())    # 2
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

        layout.addStretch(1)

        self.node_url_label = QLabel("")
        self.node_url_label.setObjectName("Hint")
        layout.addWidget(self.node_url_label)

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.connect_btn = QPushButton("Polacz")
        self.connect_btn.setObjectName("AccentBtn")
        self.refresh_btn = QPushButton("Odswiez stan")
        self.refresh_btn.setObjectName("SubtleBtn")
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.refresh_btn)
        layout.addLayout(btn_row)

        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
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
        form.addRow("ID tanca", self.dance_id_combo)
        form.addRow("Sekwencja", self.sequence_name_edit)
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

        self.dancer_path_preview = QLabel()
        self.dancer_path_preview.setObjectName("Hint")
        self.dancer_path_preview.setWordWrap(True)
        part_layout.addWidget(self.dancer_path_preview)

        self.apply_dancer_btn = QPushButton("Zapisuj do katalogu osoby")
        self.apply_dancer_btn.setObjectName("SubtleBtn")
        part_layout.addWidget(self.apply_dancer_btn)

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
        self.apply_thresholds_btn = QPushButton("Zastosuj progi")
        self.apply_thresholds_btn.setObjectName("SubtleBtn")
        thresh_layout.addWidget(self.apply_thresholds_btn)

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

        return self._scroll_page(session_card, part_card, thresh_card, actions_card, llm_card)

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
        self.analysis_export_detailed_csv_btn = QPushButton("Szczegolowe CSV")
        self.analysis_export_detailed_csv_btn.setObjectName("SubtleBtn")
        self.analysis_export_detailed_csv_btn.setEnabled(False)

        btn_grid.addWidget(self.analysis_generate_btn, 0, 0)
        btn_grid.addWidget(self.analysis_export_png_btn, 0, 1)
        btn_grid.addWidget(self.analysis_export_svg_btn, 0, 2)
        btn_grid.addWidget(self.analysis_refresh_btn, 1, 0)
        btn_grid.addWidget(self.analysis_export_csv_btn, 1, 1)
        btn_grid.addWidget(self.analysis_export_detailed_csv_btn, 1, 2)
        layout.addLayout(btn_grid)

        return self._scroll_page(card)

    def _info_page(self) -> QScrollArea:
        C1 = "#0f2744"   # Komputer 1 — niebieski
        C2 = "#0f2a1a"   # Komputer 2 — zielony
        C3 = "#2a1a2a"   # Komputer 3 — fioletowy
        BORDER = "#334155"
        ARROW_CSS = "color:#38bdf8; font-size:11px; background:transparent; padding:0 0 0 16px;"
        TAG_CSS = "color:#475569; font-size:10px; background:transparent; border:none; padding:0;"
        NAME_CSS = "color:#e2e8f0; font-size:12px; font-weight:bold; background:transparent; border:none; padding:0;"
        LINE_CSS = "color:#94a3b8; font-size:11px; background:transparent; border:none; padding:0;"

        def node(tag: str, name: str, lines: list[str], color: str) -> QFrame:
            f = QFrame()
            f.setStyleSheet(
                f"QFrame{{background:{color};border:1px solid {BORDER};border-radius:6px;}}"
            )
            vl = QVBoxLayout(f)
            vl.setContentsMargins(12, 8, 12, 10)
            vl.setSpacing(2)
            t = QLabel(tag); t.setStyleSheet(TAG_CSS); vl.addWidget(t)
            n = QLabel(name); n.setStyleSheet(NAME_CSS); vl.addWidget(n)
            if lines:
                vl.addSpacing(3)
            for line in lines:
                l = QLabel(line); l.setStyleSheet(LINE_CSS); vl.addWidget(l)
            return f

        def arrow(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(ARROW_CSS)
            return lbl

        def sep(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color:#475569;font-size:10px;letter-spacing:2px;"
                "background:transparent;padding:8px 0 4px 0;"
            )
            return lbl

        seq_card, seq_layout = self._card("Przebieg sesji")
        seq_layout.addWidget(_SeqDiagram())

        flow_card, flow_layout = self._card("Przeplyw danych")

        flow_layout.addWidget(sep("— INICJALIZACJA SESJI —"))
        flow_layout.addWidget(node(
            "KOMPUTER 3", "VR klient",
            ["inicjuje sesje — wysyla session_prepare"], C3,
        ))
        prepare_row = QHBoxLayout()
        prepare_row.setSpacing(8)
        prepare_row.addWidget(node(
            "KOMPUTER 1", "RemoteGUI",
            ["odbiera session_prepare", "przekazuje do ComputeNode"],
            C1,
        ))
        prepare_row.addWidget(node(
            "KOMPUTER 2", "ComputeNode",
            ["odbiera session_prepare", "gotowy na dane"],
            C2,
        ))
        flow_layout.addLayout(prepare_row)
        flow_layout.addWidget(arrow("↓  session_start  (HTTP → UDP 5006)  ·  K1 → K2"))
        flow_layout.addWidget(sep("— PRZESYLANIE DANYCH —"))
        flow_layout.addWidget(node(
            "KOMPUTER 1", "Vicon / Kalman",
            ["nadajnik danych ruchu  (100 Hz)"], C1,
        ))
        flow_layout.addWidget(arrow("↓  UDP 5005"))
        flow_layout.addWidget(node(
            "KOMPUTER 2 — ComputeNode", "backend_embedded",
            [
                "• zbiera pakiety w okna czasowe (np. 4 s / co 3 s)",
                "• oblicza katy, normalizuje, downsampluje",
                "• segmentuje kroki, liczy metryki ramion",
                "• buduje prompt i wysyla do LLM",
            ], C2,
        ))
        flow_layout.addWidget(arrow("↓  HTTP POST  localhost:8000/generate"))
        flow_layout.addWidget(node(
            "KOMPUTER 2 — ComputeNode", "llm_server",
            [
                "• Danube3-4B + QLoRA  nf4 / 4-bit",
                "• zwraca JSON: { feedback, score, latency_s }",
            ], C2,
        ))
        flow_layout.addWidget(arrow("↓  stdout  [FEEDBACK] ..."))
        flow_layout.addWidget(node(
            "KOMPUTER 2 — ComputeNode", "node_manager",
            [
                "• parsuje linie [FEEDBACK] z backendu",
                "• WS 8010  →  RemoteGUI  (logi, feedback w trakcie sesji)",
                "• UDP 5007  →  VR klient  (feedback w trakcie sesji)",
                "• po session_end: wysyla summary z avg score  →  UDP 5007  →  VR",
            ], C2,
        ))

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        out_row.addWidget(node("KOMPUTER 1", "RemoteGUI", ["eventy WS 8010", "logi i feedback"], C1))
        out_row.addWidget(node("KOMPUTER 3", "VR klient", ["UDP 5007", "wyswietla feedback"], C3))
        flow_layout.addLayout(out_row)

        flow_layout.addWidget(sep("— ZAKONCZENIE SESJI —"))
        flow_layout.addWidget(node(
            "KOMPUTER 3", "VR klient",
            ["konczy sesje — wysyla session_end  →  UDP 5006  →  K2"], C3,
        ))
        flow_layout.addWidget(arrow("↓  session_end  →  ComputeNode"))
        flow_layout.addWidget(node(
            "KOMPUTER 2 — ComputeNode", "node_manager",
            [
                "• zatrzymuje backend i zapis danych",
                "• oblicza sredni wynik z calej sesji",
                "• wysyla summary (avg score)  →  UDP 5007  →  VR",
            ], C2,
        ))
        flow_layout.addWidget(arrow("↓  summary { avg_score }  →  UDP 5007"))
        flow_layout.addWidget(node(
            "KOMPUTER 3", "VR klient",
            ["wyswietla podsumowanie z srednim wynikiem"], C3,
        ))

        ctrl_card, ctrl_layout = self._card("Sterowanie")
        ctrl_layout.addWidget(node(
            "KOMPUTER 1", "RemoteGUI  →  ComputeNode",
            [
                "• HTTP 8010  →  node_manager  (start/stop backendu i LLM)",
                "• HTTP 8010  →  node_manager  →  UDP 5006  →  backend",
                "  (session_prepare / session_start / session_end)",
                "• WebSocket 8010  ←  eventy, logi, feedback",
            ], C1,
        ))

        startup_card, startup_layout = self._card("Kolejnosc uruchamiania")
        for step, desc in [
            ("1.  Start backend",
             "Uruchamia run_udp_controlled_session. Nasluchuje na UDP 5006,\n"
             "czeka na komendy sesji. LLM mozna uruchomic razem (auto-start)\n"
             "lub osobno przyciskiem 'Uruchom LLM'."),
            ("2.  Ustaw osobe  (opcjonalnie)",
             "Wpisz imie i nazwisko, kliknij 'Zapisuj do katalogu osoby'.\n"
             "Backend zapamietuje kontekst — kolejne sesje trafiaja\n"
             "do podkatalogu z ta osoba w runtime/realtime_e2e/."),
            ("3.  Start sesji",
             "Kliknij 'Start sesji' lub wyslij przez UDP:\n"
             "session_prepare  →  session_start  →  [dane UDP 5005]  →  session_end"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(10)
            step_lbl = QLabel(step)
            step_lbl.setStyleSheet(
                "color:#38bdf8;font-size:11px;font-weight:bold;"
                "background:transparent;min-width:160px;max-width:160px;"
            )
            step_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet("color:#94a3b8;font-size:11px;background:transparent;")
            desc_lbl.setWordWrap(True)
            row.addWidget(step_lbl)
            row.addWidget(desc_lbl, 1)
            startup_layout.addLayout(row)
            startup_layout.addSpacing(4)

        return self._scroll_page(seq_card, flow_card, ctrl_card, startup_card)

    # ── Right panel ───────────────────────────────────────

    def _analysis_only_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._analysis_chart_card(), 1)
        return panel

    def _feedback_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Feedback")
        title.setObjectName("SectionTitle")
        header_row.addWidget(title)
        header_row.addStretch()
        from PySide6.QtWidgets import QApplication, QStyle
        clear_btn = QPushButton()
        clear_btn.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        clear_btn.setToolTip("Wyczysc feedback")
        clear_btn.setFixedSize(40, 40)
        clear_btn.setStyleSheet(
            "QPushButton{border:none;background:#7f1d1d;border-radius:3px;padding:2px;margin:5px;}"
            "QPushButton:hover{background:#b91c1c;}"
        )
        clear_btn.clicked.connect(lambda: self.feedback_view.clear())
        header_row.addWidget(clear_btn)
        layout.addLayout(header_row)
        from PySide6.QtWidgets import QCheckBox
        self.show_input_check = QCheckBox("Pokaż input modelu")
        layout.addWidget(self.show_input_check)
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
            QTimer.singleShot(0, lambda: self._conn_controls.setMinimumHeight(
                self._feedback_frame.sizeHint().height()
            ))
        elif index == 2:
            # Analysis: controls left, chart right (no feedback/log visible)
            self.left_content_stack.setCurrentIndex(1)
            self.right_stack.setCurrentIndex(1)
            self._main_content.setCurrentIndex(1)
            def _fix_analysis_splitter():
                total = self._splitter.width() or 800
                self._splitter.setSizes([total * 3 // 8, total * 5 // 8])
            QTimer.singleShot(0, _fix_analysis_splitter)
        elif index == 3:
            # Info: osobny widok pelna szerokosc, bez splittera
            self._main_content.setCurrentIndex(2)
        else:
            # Session (1): controls left, feedback+log right
            self._right_default_layout.addWidget(self._feedback_frame)
            self._right_default_layout.addWidget(self._log_frame)
            self._right_default_layout.setStretch(
                self._right_default_layout.indexOf(self._feedback_frame), 1
            )
            self._right_default_layout.setStretch(
                self._right_default_layout.indexOf(self._log_frame), 2
            )
            self.left_content_stack.setCurrentIndex(0)
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
        self.apply_dancer_btn.clicked.connect(self._apply_dancer_clicked)
        self.apply_thresholds_btn.clicked.connect(self._apply_thresholds_clicked)
        self.dancer_first_name_edit.textChanged.connect(self._update_dancer_preview)
        self.dancer_last_name_edit.textChanged.connect(self._update_dancer_preview)
        self.analysis_refresh_btn.clicked.connect(self.client.fetch_analysis_runs)
        self.analysis_generate_btn.clicked.connect(self._analysis_generate_clicked)
        self.analysis_export_png_btn.clicked.connect(self._export_analysis_png)
        self.analysis_export_svg_btn.clicked.connect(self._export_analysis_svg)
        self.analysis_export_csv_btn.clicked.connect(self._export_analysis_csv)
        self.analysis_export_detailed_csv_btn.clicked.connect(self._export_analysis_detailed_csv)
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
        self.live_z_spin.setValue(self.cfg.live_z_threshold)
        self.live_order_spin.setValue(self.cfg.live_major_order_threshold)
        self.analysis_theme_combo.blockSignals(True)
        theme_label = _THEME_MAP_REV.get(self.cfg.analysis_chart_theme, "Jasny")
        self.analysis_theme_combo.setCurrentText(theme_label)
        self.analysis_theme_combo.blockSignals(False)
        self.auto_start_llm_check.setChecked(self.cfg.auto_start_llm)
        self.node_url_label.setText(f"API: http://{self.cfg.node_host}:{self.cfg.node_port}")
        self.analysis_chart.set_theme(self.cfg.analysis_chart_theme)
        self._update_dancer_preview()

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
            "step_type": _step_type_for_dance(self.dance_id_combo.currentText()),
            "session_id": f"k2_{int(time.time())}",
            "extra": extra,
        }
        self.client.start_session(payload)

    def _stop_session_clicked(self) -> None:
        self.session_label.setText("Sesja: (stopping...)")
        self.client.stop_session({"reason": "remote_gui"})

    def _update_dancer_preview(self) -> None:
        first = self.dancer_first_name_edit.text().strip()
        last = self.dancer_last_name_edit.text().strip()
        parts = [first, last]
        name = " ".join(p for p in parts if p)
        date_str = time.strftime("%Y-%m-%d")
        if name:
            self.dancer_path_preview.setText(f"\u2192  .../realtime_e2e/{date_str}/{name}/session_...")
        else:
            self.dancer_path_preview.setText(f"\u2192  .../realtime_e2e/{date_str}/session_...")

    def _apply_dancer_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self._update_dancer_preview()
        first = self.dancer_first_name_edit.text().strip()
        last = self.dancer_last_name_edit.text().strip()
        self.client.set_dancer(first, last)
        name = " ".join(p for p in [first, last] if p)
        if name:
            self._append_log(f"[INFO] Backend: sesje beda zapisywane do katalogu: {name}")
        else:
            self._append_log("[INFO] Backend: sesje beda zapisywane do glownego katalogu (brak osoby).")

    def _apply_thresholds_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self.client.update_config(self.cfg)
        self.client.apply_live_thresholds(
            float(self.live_z_spin.value()),
            int(self.live_order_spin.value()),
        )
        self._append_log(
            f"[INFO] Zapisano i wyslano progi live: z={self.live_z_spin.value():.2f}, order={self.live_order_spin.value()}."
        )

    def _save_clicked(self) -> None:
        self.cfg = self._collect_cfg()
        save_remote_gui_config(self.cfg)
        self.client.update_config(self.cfg)
        self.client.apply_live_thresholds(
            float(self.live_z_spin.value()),
            int(self.live_order_spin.value()),
        )
        self._append_log("[INFO] Zapisano konfiguracje i wyslano progi live do ComputeNode.")

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
                display = new_text
                if self.show_input_check.isChecked():
                    model_input = str(payload.get("model_input", "")).strip()
                    if model_input:
                        display = f"[Input] {model_input}\n{new_text}"
                if existing:
                    self.feedback_view.setPlainText(f"{header}\n{display}\n\n{existing}")
                else:
                    self.feedback_view.setPlainText(f"{header}\n{display}")
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
            label = session_id or dance_id or "?"
            ts = time.strftime("%H:%M:%S")
            header = f"── SESJA {label}  [{ts}] ──"
            existing = self.feedback_view.toPlainText().strip()
            self.feedback_view.setPlainText(
                f"{header}\n\n{existing}" if existing else header
            )
        elif kind == "session_stopped":
            self.session_label.setText("Sesja: -")
            self.client.fetch_analysis_runs()
        elif kind == "live_thresholds_updated":
            self._append_log(
                "[INFO] ComputeNode przyjal progi live: "
                f"z={payload.get('live_z_threshold', '')}, order={payload.get('live_major_order_threshold', '')}"
            )

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
        self.analysis_export_detailed_csv_btn.setEnabled(payload is not None)
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

    def _export_analysis_detailed_csv(self) -> None:
        if self.analysis_chart.export_detailed_csv():
            self._append_log("[INFO] Zapisano szczegolowe dane CSV z analizy.")

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
