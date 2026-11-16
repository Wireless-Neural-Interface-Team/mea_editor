"""Persistent buttons via build_ui() — no launcher button."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext, PluginRecord
from neurorehab_plugin.ui import ZONE_PLUGIN_PANEL, ZONE_RECORD_PANEL, PluginUi

ATTRIBUTE_KEYS = ["field_name"]


def build_ui(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Register the persistent "Analyze row" and "Help" buttons."""
    records = context.applicable_records or context.selected_records
    has_one = len(records) == 1

    analyze = ui.add_button(
        "Analyze row",
        lambda: _analyze(api, ui, records),
        zone=ZONE_RECORD_PANEL,
        enabled=has_one,
    )
    if has_one:
        analyze.set_label(f"Analyze #{records[0].id}")

    ui.add_button(
        "Help",
        lambda: ui.show_message("Help", "Select one row, then Analyze."),
        zone=ZONE_PLUGIN_PANEL,
    )


def _analyze(api: PluginApi, ui: PluginUi, records: list[PluginRecord]) -> None:
    """Show a read-only message with the configured attributes of the first record."""
    if not records:
        return
    record = records[0]
    fields = api.get_fields(record, ATTRIBUTE_KEYS)
    lines = [f"#{record.id} {record.display_label}"]
    for key, value in fields.items():
        lines.append(f"{key}: {value!r}")
    ui.show_message("Analysis", "\n".join(lines))
