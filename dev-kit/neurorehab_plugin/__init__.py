"""NeuroRehab database plugin development kit (read-only).

Public package exposing the SDK surface that plugin authors import when
writing a plugin's entry-point module: :class:`PluginApi` for read-only
data access, :class:`PluginContext` / :class:`PluginRecord` describing the
current selection, :class:`PluginUi` UI zone helpers, button styling
utilities, and the SDK's exception types.

Security model summary (see individual modules for details):

- All server communication goes through
  :class:`~neurorehab_plugin.transport.PluginTransport`, restricted to
  ``/api/v1/plugin/*`` routes.
- :class:`PluginApi` blocks any operation whose name looks like a write,
  and automatically scopes every call to ``allowed_record_ids`` derived
  from the host-provided :class:`PluginContext`.
- Plugin UI code never touches the host's Qt objects directly; it goes
  through the :class:`PluginUi` protocol. Host chrome mutations are limited
  to buttons in named zones; dialogs and floating windows are worker-local.
"""

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.button_style import (
    PUSHBUTTON_STYLESHEET,
    WORKER_DIALOG_STYLESHEET,
    configure_push_button,
    push_button_preferred_height,
    update_push_button_cursor,
)
from neurorehab_plugin.context import PluginContext, PluginRecord
from neurorehab_plugin.errors import PluginApiError, PluginWriteForbiddenError
from neurorehab_plugin.safe_subprocess import popen as plugin_popen
from neurorehab_plugin.safe_subprocess import run as plugin_run
from neurorehab_plugin.ui import (
    PLUGIN_UI_ZONES,
    ZONE_ENTITY_TOOLBAR,
    ZONE_HOME,
    ZONE_PLUGIN_PANEL,
    ZONE_RECORD_PANEL,
    ZONE_RELATED_PANEL,
    PluginButton,
    PluginUi,
    window_builder_is_alive,
)

__all__ = [
    "PLUGIN_UI_ZONES",
    "ZONE_ENTITY_TOOLBAR",
    "ZONE_HOME",
    "ZONE_PLUGIN_PANEL",
    "ZONE_RECORD_PANEL",
    "ZONE_RELATED_PANEL",
    "PluginApi",
    "PluginButton",
    "PluginApiError",
    "PluginContext",
    "PluginRecord",
    "PluginUi",
    "PluginWriteForbiddenError",
    "PUSHBUTTON_STYLESHEET",
    "WORKER_DIALOG_STYLESHEET",
    "configure_push_button",
    "plugin_popen",
    "plugin_run",
    "push_button_preferred_height",
    "update_push_button_cursor",
    "window_builder_is_alive",
]

PLUGIN_API_VERSION = 1
"""Current SDK API version, compared against a plugin manifest's ``api_version``."""
