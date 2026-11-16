"""Standalone window that embeds The Useless Web."""

from __future__ import annotations

import sys

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

USELESS_WEB_URL = "https://theuselessweb.com"


def main() -> None:
    """Show a main window with an embedded browser on The Useless Web."""
    # Required before QApplication when using Qt WebEngine.
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)

    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as exc:
        raise SystemExit(
            "PySide6 WebEngine is missing. Declare PySide6 in requirements.txt."
        ) from exc

    window = QMainWindow()
    window.setWindowTitle("The Useless Web")
    window.resize(1024, 720)

    central = QWidget()
    layout = QVBoxLayout(central)
    layout.setContentsMargins(0, 0, 0, 0)

    view = QWebEngineView(central)
    view.setUrl(QUrl(USELESS_WEB_URL))
    layout.addWidget(view)

    window.setCentralWidget(central)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
