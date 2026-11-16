"""Access outgoing references (single or multi-reference), e.g. MEA linked from an Experience row."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import ZONE_RECORD_PANEL, PluginUi

REFERENCED_ATTRS = ["mapping", "manufacturer_ref"]
REFERENCED_FILES = ["mapping"]


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """List outgoing references of the first selected record as buttons."""
    records = context.applicable_records or context.selected_records
    if not records:
        ui.clear()
        return

    record = records[0]
    refs = api.list_outgoing_reference_records(record.id)
    if not refs:
        ui.add_button(
            "No reference",
            lambda: None,
            zone=ZONE_RECORD_PANEL,
            enabled=False,
        )
        return

    for table_label, field_label, target in refs:
        ui.add_button(
            f"{field_label} → {target.get('display_label') or table_label}",
            lambda t=target, fl=field_label: _show(api, ui, t, fl),
            zone=ZONE_RECORD_PANEL,
        )


def _show(api: PluginApi, ui: PluginUi, target: dict, field_label: str) -> None:
    """Show a read-only message about a referenced target record and its files."""
    target_id = int(target.get("id") or 0)
    target_entity_id = int(target.get("entity_id") or 0)
    lines = [
        f"Attribute: {field_label}",
        f"Target: {target.get('display_label') or target.get('id')} (#{target_id})",
        "",
    ]
    for key, value in api.get_fields(target, REFERENCED_ATTRS).items():
        lines.append(f"{key}: {value!r}")

    def _files() -> list[dict]:
        out: list[dict] = []
        for key in REFERENCED_FILES:
            out.extend(
                api.list_files(target_id, key, entity_id=target_entity_id or None)
            )
        return out

    files = ui.run_task("Loading…", _files)
    lines.append(f"Files: {len(files)}")
    ui.show_message("Referenced item", "\n".join(lines))
    if files:
        api.open_files(files)
