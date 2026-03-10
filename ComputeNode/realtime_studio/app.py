from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .theme import APP_STYLE
from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    win = MainWindow()
    win.show()
    return app.exec()
