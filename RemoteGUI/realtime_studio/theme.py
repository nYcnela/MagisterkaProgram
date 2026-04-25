from __future__ import annotations


APP_STYLE = """
/* ── Base ─────────────────────────────────────────────── */
QMainWindow {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #0c1a34, stop:0.45 #101f3f, stop:1 #0f2a4f);
}
QWidget {
  color: #e2e8f0;
  font-family: "SF Pro Text", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial;
  font-size: 13px;
}

/* ── Sidebar ──────────────────────────────────────────── */
QFrame#Sidebar {
  background: rgba(4, 12, 30, 230);
  border-right: 1px solid rgba(140, 170, 214, 35);
}
QLabel#BrandLabel {
  color: #5dd6ff;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 1px;
}
QPushButton#NavBtn {
  background: transparent;
  border: none;
  border-radius: 12px;
  min-width: 40px;
  max-width: 40px;
  min-height: 40px;
  max-height: 40px;
  color: rgba(168, 189, 217, 160);
  font-size: 18px;
  font-weight: 400;
}
QPushButton#NavBtn:hover {
  background: rgba(21, 54, 95, 160);
  color: #dff5ff;
}
QPushButton#NavBtn[active="true"] {
  background: rgba(24, 162, 244, 45);
  color: #5dd6ff;
}

/* ── Status Bar ───────────────────────────────────────── */
QFrame#StatusBar {
  background: rgba(6, 15, 35, 200);
  border: 1px solid rgba(140, 170, 214, 40);
  border-radius: 12px;
}
QLabel#StatusLabel {
  color: #8ba3c4;
  font-size: 11px;
}
QLabel#StatusMeta {
  color: #7a95b8;
  font-size: 11px;
}

/* ── Cards ────────────────────────────────────────────── */
QFrame#Card {
  background: rgba(7, 18, 39, 190);
  border-top: 1px solid rgba(180, 210, 240, 55);
  border-left: 1px solid rgba(140, 170, 214, 40);
  border-right: 1px solid rgba(140, 170, 214, 30);
  border-bottom: 1px solid rgba(100, 130, 170, 25);
  border-radius: 14px;
}
QLabel#SectionTitle {
  font-size: 15px;
  font-weight: 700;
  color: #f8fafc;
}
QLabel#Hint {
  color: #9cc4ef;
  font-size: 12px;
}
QLabel#FieldLabel {
  color: #9cc4ef;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 0 0 0;
}

/* ── Inputs ───────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background: rgba(2, 9, 24, 205);
  border: 1px solid rgba(155, 174, 201, 90);
  border-radius: 9px;
  min-height: 32px;
  padding: 0 10px;
  color: #f1f5f9;
}
QComboBox {
  padding-right: 26px;
}
QComboBox::drop-down {
  border: none;
  width: 24px;
}
QComboBox QAbstractItemView {
  background: rgba(2, 9, 24, 240);
  border: 1px solid rgba(155, 174, 201, 90);
  border-radius: 6px;
  selection-background-color: rgba(24, 162, 244, 80);
  selection-color: #f8fafc;
  padding: 4px;
}
QComboBox QAbstractItemView::item {
  min-height: 28px;
  padding: 4px 10px;
  border-radius: 4px;
}
QComboBox QAbstractItemView::item:hover {
  background: rgba(21, 54, 95, 180);
  color: #dff5ff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
  border: 1px solid #5dd6ff;
}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #18a2f4, stop:1 #16c4aa);
  border: none;
  border-radius: 10px;
  min-height: 34px;
  padding: 0 14px;
  color: #f8fafc;
  font-weight: 700;
  font-size: 12px;
}
QPushButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #44c1ff, stop:1 #37dcc5);
}
QPushButton:disabled {
  background: rgba(100, 116, 139, 120);
  color: rgba(241, 245, 249, 120);
}
QPushButton#AccentBtn {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #18a2f4, stop:1 #16c4aa);
}
QPushButton#AccentBtn:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #44c1ff, stop:1 #37dcc5);
}
QPushButton#DangerBtn {
  background: rgba(120, 30, 30, 150);
  border: 1px solid rgba(239, 68, 68, 80);
  color: #fca5a5;
}
QPushButton#DangerBtn:hover {
  background: rgba(153, 27, 27, 210);
  color: #fecaca;
  border: 1px solid rgba(239, 68, 68, 140);
}
QPushButton#SubtleBtn {
  background: rgba(30, 41, 59, 170);
  border: 1px solid rgba(148, 163, 184, 60);
  color: #cbd5e1;
}
QPushButton#SubtleBtn:hover {
  background: rgba(51, 65, 85, 210);
  color: #f1f5f9;
  border: 1px solid rgba(148, 163, 184, 100);
}

/* ── Text Areas ───────────────────────────────────────── */
QTextEdit, QPlainTextEdit {
  background: rgba(1, 9, 26, 220);
  border: 1px solid rgba(155, 174, 201, 90);
  border-radius: 11px;
  color: #dbeafe;
  font-family: "JetBrains Mono", "SF Mono", Consolas, monospace;
  font-size: 12px;
}

/* ── List Widget ──────────────────────────────────────── */
QListWidget {
  background: rgba(1, 9, 26, 220);
  border: 1px solid rgba(155, 174, 201, 90);
  border-radius: 11px;
  padding: 4px;
  outline: none;
  color: #dbeafe;
}
QListWidget::item {
  padding: 7px 10px;
  margin: 2px 0;
  border-radius: 8px;
}
QListWidget::item:selected {
  background: rgba(21, 54, 95, 210);
  color: #f8fafc;
}
QListWidget::item:hover {
  background: rgba(14, 44, 80, 180);
}

/* ── Checkbox ─────────────────────────────────────────── */
QCheckBox {
  color: #d1d5db;
}

/* ── Splitter ─────────────────────────────────────────── */
QSplitter::handle {
  background: transparent;
}
QSplitter::handle:hover {
  background: rgba(141, 180, 230, 60);
  border-radius: 2px;
}
QSplitter::handle:horizontal {
  width: 5px;
}
QSplitter::handle:vertical {
  height: 5px;
}

/* ── Progress Bar ─────────────────────────────────────── */
QProgressBar#BootBar {
  border: 1px solid rgba(84, 119, 165, 120);
  border-radius: 6px;
  background: rgba(18, 35, 63, 180);
  min-height: 12px;
  max-height: 12px;
}
QProgressBar#BootBar::chunk {
  border-radius: 5px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #16a5f4, stop:1 #1ad0bc);
}

/* ── Scrollbar ────────────────────────────────────────── */
QScrollBar:vertical {
  background: transparent;
  width: 10px;
  margin: 2px;
}
QScrollBar::handle:vertical {
  background: rgba(148, 163, 184, 140);
  border-radius: 5px;
  min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
  height: 0px;
}
QScrollArea {
  background: transparent;
  border: none;
}
QScrollArea > QWidget > QWidget {
  background: transparent;
}
"""
