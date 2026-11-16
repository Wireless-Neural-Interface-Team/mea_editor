"""Minimal PyQt5 window (standalone, not a NeuroRehab zone)."""

from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from neurorehab_plugin.button_style import PUSHBUTTON_STYLESHEET, configure_push_button


def main() -> None:
    """Build and run a minimal standalone PyQt5 demo window."""
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("Plugin GUI demo")
    window.setMinimumSize(420, 180)
    window.setStyleSheet(
        "QMainWindow { background-color: #2e3338; color: #d8dee8; }\n"
        + PUSHBUTTON_STYLESHEET
    )

    central = QWidget()
    layout = QVBoxLayout(central)
    title = QLabel("Standalone plugin window")
    title.setAlignment(Qt.AlignCenter)
    layout.addWidget(title)
    layout.addWidget(QLabel("Opened via api.launch_script() — no row selected."))
    close_btn = configure_push_button(QPushButton("Close"))
    close_btn.clicked.connect(window.close)
    layout.addWidget(close_btn)

    window.setCentralWidget(central)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
