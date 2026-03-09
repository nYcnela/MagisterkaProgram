from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .remote_ui import RemoteMainWindow
from .theme import APP_STYLE


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    win = RemoteMainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

