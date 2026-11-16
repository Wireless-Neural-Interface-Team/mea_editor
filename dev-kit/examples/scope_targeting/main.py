"""Plugin visible only when targeting rules match (see plugin.toml)."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import PluginUi


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Show a summary of the records matching this plugin's targeting rules."""
    records = context.applicable_records
    if not records:
        ui.show_message("Scope", "No applicable row in the current selection.")
        return
    lines = [
        f"{len(records)} applicable row(s) on {context.entity_key}",
        f"Primary sub-type: {context.primary_variant_key or '—'}",
    ]
    for record in records[:10]:
        lines.append(f"  #{record.id} {record.display_label}")
    ui.show_message("Scoped selection", "\n".join(lines))
