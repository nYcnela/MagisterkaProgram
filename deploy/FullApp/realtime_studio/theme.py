from __future__ import annotations


APP_STYLE = """
QMainWindow {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #0c1a34, stop:0.45 #101f3f, stop:1 #0f2a4f);
}
QWidget {
  color: #e2e8f0;
  font-family: "SF Pro Text", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial;
  font-size: 13px;
}
QFrame#HeaderCard {
  background: rgba(8, 18, 38, 160);
  border: 1px solid rgba(140, 170, 214, 70);
  border-radius: 14px;
}
QFrame#Card {
  background: rgba(7, 18, 39, 210);
  border: 1px solid rgba(140, 170, 214, 65);
  border-radius: 14px;
}
QLabel#Title {
  font-size: 34px;
  font-weight: 760;
  color: #f8fafc;
}
QLabel#Subtitle {
  color: #a8bdd9;
  font-size: 13px;
}
QLabel#SectionTitle {
  font-size: 17px;
  font-weight: 700;
  color: #f8fafc;
}
QLabel#Hint {
  color: #9cc4ef;
  font-size: 12px;
}
QLabel#StatePill {
  border-radius: 11px;
  padding: 4px 10px;
  font-weight: 700;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
  background: rgba(2, 9, 24, 205);
  border: 1px solid rgba(155, 174, 201, 90);
  border-radius: 9px;
  min-height: 33px;
  padding: 0 11px;
  color: #f1f5f9;
}
QComboBox {
  padding-right: 26px;
}
QComboBox::drop-down {
  border: none;
  width: 24px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
  border: 1px solid #5dd6ff;
}
QPushButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #18a2f4, stop:1 #16c4aa);
  border: none;
  border-radius: 10px;
  min-height: 36px;
  padding: 0 16px;
  color: #f8fafc;
  font-weight: 700;
}
QPushButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #44c1ff, stop:1 #37dcc5);
}
QPushButton:disabled {
  background: rgba(100, 116, 139, 120);
  color: rgba(241, 245, 249, 120);
}
QTextEdit, QPlainTextEdit {
  background: rgba(1, 9, 26, 220);
  border: 1px solid rgba(155, 174, 201, 90);
  border-radius: 11px;
  color: #dbeafe;
  font-family: "JetBrains Mono", "SF Mono", Consolas, monospace;
  font-size: 12px;
}
QCheckBox {
  color: #d1d5db;
}
QTabWidget#ConfigTabs::pane {
  border: 1px solid rgba(140, 170, 214, 65);
  border-radius: 12px;
  background: rgba(8, 20, 42, 170);
  top: -1px;
}
QTabBar::tab {
  background: rgba(9, 27, 54, 150);
  border: 1px solid rgba(140, 170, 214, 55);
  border-bottom: none;
  padding: 8px 14px;
  margin-right: 4px;
  border-top-left-radius: 10px;
  border-top-right-radius: 10px;
  color: #b9cae2;
  min-width: 90px;
}
QTabBar::tab:selected {
  background: rgba(21, 54, 95, 210);
  color: #f8fafc;
}
QTabBar::tab:hover {
  color: #dff5ff;
}
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
QScrollBar:vertical {
  background: transparent;
  width: 12px;
  margin: 2px;
}
QScrollBar::handle:vertical {
  background: rgba(148, 163, 184, 165);
  border-radius: 6px;
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
