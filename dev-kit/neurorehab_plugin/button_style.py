"""Shared button styles for plugin worker Qt windows.

Provides a Qt stylesheet matching the NeuroRehab desktop client's look and
feel, plus small helpers to apply it to ``QPushButton`` widgets and to
compute their preferred size, so plugin-created windows stay visually
consistent with the host application. Supports both PySide6 and PyQt5
(the Qt binding is resolved dynamically at call time).
"""

from __future__ import annotations

from typing import Any

PUSHBUTTON_STYLESHEET = """
QPushButton {
    background-color: #525f72;
    color: #ffffff;
    border: 1px solid #8896aa;
    border-top-color: #9aa8bc;
    border-left-color: #9aa8bc;
    border-right-color: #3a4452;
    border-bottom-color: #3a4452;
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 26px;
    font-weight: 600;
}
QPushButton:hover:enabled {
    background-color: #627088;
    color: #ffffff;
    border-top-color: #b0bdd0;
    border-left-color: #b0bdd0;
}
QPushButton:pressed:enabled {
    background-color: #343e4c;
    color: #f4f7fb;
    border: 2px inset #78859a;
    padding-top: 8px;
    padding-bottom: 4px;
    padding-left: 15px;
    padding-right: 13px;
}
QPushButton:disabled {
    background-color: #242a34;
    color: #78859a;
    border: 1px solid #3a4452;
    border-top-color: #3a4452;
    border-left-color: #3a4452;
    border-right-color: #3a4452;
    border-bottom-color: #3a4452;
}
"""

WORKER_DIALOG_STYLESHEET = (
    "QDialog { background-color: #181c22; color: #f4f7fb; }\n" + PUSHBUTTON_STYLESHEET
)


def _qt_core() -> Any:
    """Import and return the ``QtCore.Qt`` namespace, preferring PySide6 over PyQt5."""
    try:
        from PySide6.QtCore import Qt

        return Qt
    except ImportError:
        from PyQt5.QtCore import Qt

        return Qt


def _qt_widgets() -> Any:
    """Import and return the ``QtWidgets`` module, preferring PySide6 over PyQt5."""
    try:
        from PySide6 import QtWidgets

        return QtWidgets
    except ImportError:
        from PyQt5 import QtWidgets

        return QtWidgets


def _focus_strong(Qt: Any) -> Any:
    """Return the ``StrongFocus`` enum value, compatible with both Qt bindings."""
    if hasattr(Qt, "FocusPolicy"):
        return Qt.FocusPolicy.StrongFocus
    return Qt.StrongFocus


def _cursor_pointing(Qt: Any) -> Any:
    """Return the pointing-hand cursor shape, compatible with both Qt bindings."""
    if hasattr(Qt, "CursorShape"):
        return Qt.CursorShape.PointingHandCursor
    return Qt.PointingHandCursor


def _cursor_arrow(Qt: Any) -> Any:
    """Return the default arrow cursor shape, compatible with both Qt bindings."""
    if hasattr(Qt, "CursorShape"):
        return Qt.CursorShape.ArrowCursor
    return Qt.ArrowCursor


def configure_push_button(button: Any) -> Any:
    """Apply the shared button style (matching the NeuroRehab desktop client).

    Sets the stylesheet, disables auto-default/default behavior (so Enter
    key presses in a dialog don't accidentally trigger the button),
    enables strong keyboard focus, and sets the appropriate mouse cursor.

    Args:
        button: A ``QPushButton`` (PySide6 or PyQt5) to style.

    Returns:
        The same ``button`` instance, for convenient chaining.
    """
    Qt = _qt_core()
    button.setStyleSheet(PUSHBUTTON_STYLESHEET)
    button.setAutoDefault(False)
    button.setDefault(False)
    button.setFocusPolicy(_focus_strong(Qt))
    update_push_button_cursor(button)
    return button


def update_push_button_cursor(button: Any) -> None:
    """Set the button's mouse cursor based on its current enabled state.

    Args:
        button: A ``QPushButton`` (PySide6 or PyQt5) to update.
    """
    Qt = _qt_core()
    button.setCursor(
        _cursor_pointing(Qt) if button.isEnabled() else _cursor_arrow(Qt)
    )


def push_button_preferred_height(button: Any | None = None) -> int:
    """Compute a button's preferred height after the shared style is applied.

    Args:
        button: An existing, already-styled ``QPushButton`` to measure. If
            ``None``, a throwaway probe button is created (requires a live
            ``QApplication``) to compute a representative height.

    Returns:
        The preferred height in pixels, or ``40`` as a fallback when no
        ``QApplication`` instance exists to measure against.
    """
    if button is not None:
        style = button.style()
        if style is not None:
            style.polish(button)
        return button.sizeHint().height()
    QtWidgets = _qt_widgets()
    app = QtWidgets.QApplication.instance()
    if app is None:
        return 40
    probe = configure_push_button(QtWidgets.QPushButton("Ag"))
    return push_button_preferred_height(probe)
