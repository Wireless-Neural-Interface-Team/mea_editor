"""Open The Useless Web in a dedicated plugin window."""

from __future__ import annotations

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import PluginUi


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Launch the embedded browser window for https://theuselessweb.com."""
    del context
    try:
        api.launch_script("useless_web.py", detached=False)
    except Exception as exc:
        ui.show_message("Useless Website", str(exc))
