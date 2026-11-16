"""Automatic Information panel button (run_trigger = on_select)."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import ZONE_RECORD_PANEL, PluginUi

FIELD_KEYS = ["status", "label"]


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Re-render the record-panel summary button on every selection change.

    Invoked automatically on each selection because ``run_trigger`` is set
    to ``on_select`` in ``plugin.toml``.
    """
    records = context.applicable_records or context.selected_records
    if not records:
        ui.clear()
        return
    record = records[0]

    def _summary() -> None:
        """Show a read-only message with the configured fields of the record."""
        fields = api.get_fields(record, FIELD_KEYS)
        lines = [
            f"Table: {context.entity_key}",
            f"Row ID: {record.id}",
            f"Label: {record.display_label}",
        ]
        for key, value in fields.items():
            lines.append(f"{key}: {value!r}")
        ui.show_message("Summary", "\n".join(lines))

    ui.add_button(
        f"Summary — {record.display_label}",
        _summary,
        zone=ZONE_RECORD_PANEL,
    )
