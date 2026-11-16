"""UI interface provided by the host application (implemented on the client).

These ``Protocol`` classes define the *shape* of the UI object a plugin
receives in its ``build_ui(api, context, ui)`` / ``run(api, context, ui)``
callbacks. Plugin code always runs in an isolated worker subprocess. The
host only accepts button/clear events for pre-approved zones; dialogs,
tables, busy indicators, and floating windows are worker-owned Qt widgets.
Plugins never receive the host application's Qt widget tree.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

# Authorized locations in the host UI (no direct Qt access).
ZONE_ENTITY_TOOLBAR = "entity_toolbar"
"""Toolbar area shown above a table (entity) view."""
ZONE_RECORD_PANEL = "record_panel"
"""Panel area shown alongside a single record's detail view."""
ZONE_RELATED_PANEL = "related_panel"
"""Panel area shown alongside a record's related/linked records."""
ZONE_PLUGIN_PANEL = "plugin_panel"
"""Dedicated panel area reserved for plugin-contributed content."""
ZONE_HOME = "home"
"""Home tab area below session content (retention and other permission-gated widgets)."""

PLUGIN_UI_ZONES: frozenset[str] = frozenset(
    {
        ZONE_ENTITY_TOOLBAR,
        ZONE_RECORD_PANEL,
        ZONE_RELATED_PANEL,
        ZONE_PLUGIN_PANEL,
        ZONE_HOME,
    }
)
"""Complete set of valid zone identifiers accepted by :meth:`PluginUi.add_button`."""


class PluginButton(Protocol):
    """Handle to a button created in a zone (dynamic enable / label)."""

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the button."""
        ...

    def is_enabled(self) -> bool:
        """Return whether the button is currently enabled."""
        ...

    def set_label(self, label: str) -> None:
        """Change the button's visible text label."""
        ...


class PluginUiScope(Protocol):
    """Floating window scope returned by ``open_window()`` in the worker.

    In the worker subprocess, the returned object also exposes ``_layout`` and
    ``_parent`` (Qt layout and parent widget) so you can add custom widgets
    (images, labels, etc.) when PySide6/PyQt5 is declared in ``requirements.txt``.
    """

    def add_button(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        enabled: bool = True,
    ) -> PluginButton:
        """Add a button inside this floating window's layout.

        Args:
            label: Visible text of the button.
            callback: Zero-argument function invoked when clicked.
            enabled: Initial enabled state of the button.

        Returns:
            A :class:`PluginButton` handle for later enabling/labeling.
        """
        ...


class PluginUi(Protocol):
    """Restricted UI surface exposed to a plugin's ``build_ui()``/``run()`` callbacks.

    Implemented by :class:`~neurorehab_plugin.worker_main.WorkerUiBridge` in
    the worker subprocess. Host chrome mutations are limited to buttons in
    :data:`PLUGIN_UI_ZONES` (and clearing those). Dialogs, tables, busy
    indicators, and :meth:`open_window` are worker-local. ``set_status_banner``
    / ``highlight_records`` are retained for API compatibility but do not
    affect the host.

    **Host responsiveness:** NeuroRehab stays interactive during plugin IPC
    (including launching other plugins). Keep ``build_ui()`` tiny and fast
    (worker configure/ready ~45 s; run/``build_ui`` waits are unlimited —
    use Stop). Put long work in button callbacks with :meth:`run_task` or
    :meth:`open_window` — never expect the desktop client to freeze until
    you return.
    """

    def show_message(self, title: str, text: str) -> None:
        """Show a modal message dialog (worker-local)."""
        ...

    def show_info(self, text: str) -> None:
        """Show a lightweight informational message (worker-local dialog)."""
        ...

    def show_table(self, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        """Display tabular data in a worker-local modal dialog.

        Args:
            title: Title of the table view.
            columns: Column header labels.
            rows: Table rows, each a list of cell values aligned with ``columns``.
        """
        ...

    def export_csv(self, path: str, columns: list[str], rows: list[list[Any]]) -> str:
        """Write tabular data to a CSV file.

        Args:
            path: Destination file path.
            columns: Column header labels, written as the first CSV row.
            rows: Table rows, each a list of cell values.

        Returns:
            The path the CSV was written to.
        """
        ...

    def add_button(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        zone: str = ZONE_ENTITY_TOOLBAR,
        enabled: bool = True,
        new_row: bool | None = None,
    ) -> PluginButton:
        """Add a button to one of the host application's pre-approved UI zones.

        Args:
            label: Visible text of the button.
            callback: Zero-argument function invoked when clicked.
            zone: Target zone; must be one of :data:`PLUGIN_UI_ZONES`.
            enabled: Initial enabled state of the button.
            new_row: Layout in the plugin's group box. ``None`` keeps the
                zone default (side by side on the toolbar and Home; stacked
                elsewhere). ``False`` places the button on the current row;
                ``True`` starts a new row below.

        Returns:
            A :class:`PluginButton` handle for later enabling/labeling.
            If the zone is valid but not present on the current tab
            (for example :data:`ZONE_HOME` on a table tab), the host
            skips the button and the handle is a no-op.
        """
        ...

    def clear_zone(self, zone: str) -> None:
        """Remove all plugin-added widgets from a given zone."""
        ...

    def clear(self) -> None:
        """Remove all plugin-added widgets from every zone."""
        ...

    def open_window(
        self,
        title: str,
        *,
        width: int = 720,
        height: int = 480,
    ) -> PluginUiScope:
        """Open a dedicated floating window owned by the plugin (worker-local).

        Args:
            title: Window title.
            width: Initial window width in pixels.
            height: Initial window height in pixels.

        Returns:
            A :class:`PluginUiScope` used to populate the window.
        """
        ...

    def set_status_banner(self, text: str) -> None:
        """No-op for host chrome; kept for API compatibility."""
        ...

    def highlight_records(self, record_ids: list[int], color: str = "#2f6fed33") -> None:
        """No-op for host chrome; kept for API compatibility.

        Host implementations highlight by table-local id (``#N``).
        """
        ...

    def clear_highlights(self) -> None:
        """No-op for host chrome; kept for API compatibility."""
        ...

    def run_task(self, title: str, worker: Callable[[], Any]) -> Any:
        """Run a callable for long CPU/network work (worker-local progress).

        Use this from **button callbacks** / ``run()``, never from
        ``build_ui()``. The NeuroRehab host stays interactive; only the
        worker process shows progress. ``worker`` must not call ``ui.*``.

        Args:
            title: Progress dialog title.
            worker: Zero-argument callable that performs the work.

        Returns:
            The value returned by ``worker``.
        """
        ...


def window_builder_is_alive(builder: Any) -> bool:
    """Return False if an ``open_window()`` scope was closed (C++ object deleted)."""
    if builder is None:
        return False
    if getattr(builder, "_alive", True) is False:
        return False
    try:
        from shiboken6 import isValid

        parent = getattr(builder, "_parent", None)
        return parent is not None and isValid(parent)
    except RuntimeError:
        return False
    except ImportError:
        try:
            parent = getattr(builder, "_parent", None)
            if parent is None:
                return False
            parent.objectName()
            return True
        except RuntimeError:
            return False
