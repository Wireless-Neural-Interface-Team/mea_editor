"""Floating Qt window in the worker (ui.open_window)."""

from __future__ import annotations

from typing import Any

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import ZONE_RECORD_PANEL, PluginUi, window_builder_is_alive

_SESSION: dict[str, Any] = {"builder": None, "label": None}


def build_ui(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Register the persistent "Open viewer" button in the record panel."""
    records = context.applicable_records or context.selected_records
    ui.add_button(
        "Open viewer",
        lambda: _open(ui, records),
        zone=ZONE_RECORD_PANEL,
        enabled=len(records) == 1,
    )


def _open(ui: PluginUi, records) -> None:
    """Open (or update) the floating viewer window for the first record.

    Reuses the existing worker window if it is still alive; otherwise
    creates a new one and remembers it in ``_SESSION`` for next time.
    """
    if not records:
        return
    record = records[0]
    title = f"#{record.id}"
    builder = _SESSION.get("builder")
    if not window_builder_is_alive(builder):
        builder = ui.open_window(title, width=480, height=320)
        _SESSION["builder"] = builder
        builder.add_button(
            "Summary",
            lambda: ui.show_message("Summary", record.display_label),
        )
        try:
            from PySide6.QtWidgets import QLabel

            label = QLabel(record.display_label, builder._parent)
            builder._layout.addWidget(label)
            _SESSION["label"] = label
        except ImportError:
            _SESSION["label"] = None
        return

    builder._parent.setWindowTitle(title)
    label = _SESSION.get("label")
    if label is not None:
        label.setText(record.display_label)
