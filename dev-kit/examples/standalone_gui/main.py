"""Launch mon_gui.py in the plugin venv (no row selection)."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import PluginUi


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Launch the standalone ``mon_gui.py`` window via the plugin's own venv."""
    del context
    try:
        api.launch_script("mon_gui.py", detached=False)
    except Exception as exc:
        ui.show_message("GUI error", str(exc))
