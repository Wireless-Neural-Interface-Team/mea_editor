"""Persistent buttons on the Home tab via build_ui()."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import ZONE_HOME, PluginUi


def build_ui(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Register a persistent button below Home session content."""
    del api, context
    ui.add_button(
        "Home demo",
        lambda: ui.show_message(
            "Home plugin",
            "This button lives on the Home tab, below session content.",
        ),
        zone=ZONE_HOME,
    )
