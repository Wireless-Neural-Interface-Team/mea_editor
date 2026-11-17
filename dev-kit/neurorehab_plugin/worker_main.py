"""Plugin worker process entrypoint (runs in the plugin venv Python).

This module implements the subprocess that actually executes a plugin's
Python code, isolated from the host application's own process and Python
environment. The host communicates with this worker over the child's
stdin/stdout using a simple line-delimited JSON protocol (see
:mod:`neurorehab_plugin.worker_protocol` for the (de)serialization helpers
and :func:`main` below for the message loop).

Each incoming request carries a fresh ``base_url``/``token``/``context``
triple, from which a scoped :class:`~neurorehab_plugin.api.PluginApi`
session is created for the duration of that single callback invocation
(see :class:`PluginWorkerRuntime._set_session_api`); this ensures the
read-only and ``allowed_record_ids`` security constraints described in
:mod:`neurorehab_plugin.api` are enforced per-call, using the exact
context the host sent for that call.
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.local_files import pump_gui_events
from neurorehab_plugin.ui import ZONE_ENTITY_TOOLBAR
from neurorehab_plugin.worker_protocol import deserialize_context, json_ready


def _send(message: dict[str, Any]) -> None:
    """Serialize ``message`` to JSON and write it as one line to stdout.

    Args:
        message: JSON-serializable dict to send to the host process.
    """
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _read() -> dict[str, Any]:
    """Block until a line is available on stdin and parse it as JSON.

    Returns:
        The parsed message dict.

    Raises:
        EOFError: If stdin is closed (host process disconnected).
    """
    line = sys.stdin.readline()
    if not line:
        raise EOFError("plugin worker stdin closed")
    return json.loads(line)


def _ensure_import_paths() -> None:
    """Insert the plugin's root and any SDK/host-provided paths into ``sys.path``.

    Reads ``NR_PLUGIN_ROOT`` (the plugin's own code) and ``NR_SDK_ROOT`` /
    ``NR_HOST_PYSIDE_PATH`` (host-provided Python packages, e.g. a bundled
    PySide6 install) from the environment, so the plugin entry module and
    its optional Qt dependency can be imported.
    """
    plugin_root = os.environ.get("NR_PLUGIN_ROOT", "").strip()
    if plugin_root:
        root = str(Path(plugin_root).resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
    for key in ("NR_SDK_ROOT", "NR_HOST_PYSIDE_PATH"):
        extra = os.environ.get(key, "").strip()
        if extra and extra not in sys.path:
            sys.path.insert(0, extra)


def _normalize_on_file_chosen_result(raw: Any) -> dict[str, Any]:
    """Normalize ``on_file_chosen`` return value to ``{suggested_values: {...}}``.

    Accepts ``None``, a bare ``dict`` of field values, or a dict that already
    contains ``suggested_values``. Non-dict values become an empty mapping.
    """
    if raw is None:
        return {"suggested_values": {}}
    if not isinstance(raw, dict):
        return {"suggested_values": {}}
    if "suggested_values" in raw:
        values = raw.get("suggested_values")
        if not isinstance(values, dict):
            return {"suggested_values": {}}
        return {"suggested_values": dict(values)}
    return {"suggested_values": dict(raw)}


def _ensure_qt_app() -> None:
    """Create a ``QApplication`` if PySide6 is available and none exists yet.

    No-op if PySide6 is not installed in the plugin's venv (plugins without
    a GUI dependency don't need one). Configured to not quit when its last
    window closes, since the worker process itself should keep running to
    serve further host requests.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)


class _LocalButton:
    """Handle for a QPushButton inside a worker-local window.

    Implements the :class:`~neurorehab_plugin.ui.PluginButton` protocol for
    buttons created via :meth:`_LocalWindowBuilder.add_button`, i.e. buttons
    that live in a Qt window owned directly by this worker process.
    """

    def __init__(self, button: Any) -> None:
        self._button = button

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable the underlying ``QPushButton`` and refresh its cursor."""
        self._button.setEnabled(bool(enabled))
        from neurorehab_plugin.button_style import update_push_button_cursor

        update_push_button_cursor(self._button)

    def is_enabled(self) -> bool:
        """Return whether the underlying ``QPushButton`` is enabled."""
        return bool(self._button.isEnabled())

    def set_label(self, label: str) -> None:
        """Change the underlying ``QPushButton``'s visible text."""
        self._button.setText(str(label))


class _RemoteButton:
    """Handle for a button rendered by the host application in one of its UI zones.

    Implements the :class:`~neurorehab_plugin.ui.PluginButton` protocol by
    forwarding state changes to the host over the worker/host JSON protocol
    (via :meth:`WorkerUiBridge._emit`), since the actual widget lives in the
    host process, not this worker.
    """

    def __init__(self, ui: "WorkerUiBridge", button_id: str) -> None:
        self._ui = ui
        self._button_id = button_id

    def set_enabled(self, enabled: bool) -> None:
        """Ask the host to enable/disable this button."""
        self._ui._emit(
            "button_set_enabled",
            {"button_id": self._button_id, "enabled": bool(enabled)},
        )

    def is_enabled(self) -> bool:
        """Return the last known enabled state tracked locally for this button."""
        return bool(self._ui._button_states.get(self._button_id, True))

    def set_label(self, label: str) -> None:
        """Ask the host to change this button's visible label."""
        self._ui._emit("button_set_label", {"button_id": self._button_id, "label": str(label)})


class _LocalWindowBuilder:
    """Floating Qt window in the worker (custom widgets via _layout / _parent).

    Implements the :class:`~neurorehab_plugin.ui.PluginUiScope` protocol
    returned by :meth:`WorkerUiBridge.open_window`. Unlike host UI zones,
    this window is a real ``QDialog`` created and owned by the worker
    process itself, exposing its ``_layout``/``_parent`` so plugin code can
    add custom PySide6/PyQt5 widgets directly (when a Qt binding is
    declared in the plugin's ``requirements.txt``).
    """

    def __init__(
        self,
        ui: "WorkerUiBridge",
        title: str,
        *,
        width: int,
        height: int,
    ) -> None:
        """Create and register the floating dialog (shown after it is populated).

        Args:
            ui: The owning :class:`WorkerUiBridge`, used to track the
                window's lifetime.
            title: Window title.
            width: Initial window width (minimum enforced at 320px).
            height: Initial window height (minimum enforced at 240px).
        """
        _ensure_qt_app()
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        from neurorehab_plugin.button_style import WORKER_DIALOG_STYLESHEET

        self._alive = True
        self._parent = QDialog()
        self._parent.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._parent.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._parent.setAutoFillBackground(True)
        self._parent.setWindowTitle(title)
        self._parent.setStyleSheet(WORKER_DIALOG_STYLESHEET)
        try:
            from PySide6.QtGui import QColor, QPalette

            palette = self._parent.palette()
            background = QColor("#181c22")
            palette.setColor(QPalette.ColorRole.Window, background)
            palette.setColor(QPalette.ColorRole.Base, background)
            self._parent.setPalette(palette)
        except Exception:
            pass
        self._layout = QVBoxLayout(self._parent)
        self._parent.resize(max(320, int(width)), max(240, int(height)))
        self._parent.destroyed.connect(lambda *_: setattr(self, "_alive", False))
        ui._register_local_window(self._parent)

    def add_button(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        enabled: bool = True,
    ) -> _LocalButton:
        """Add a styled ``QPushButton`` to this window's layout.

        Args:
            label: Visible text of the button.
            callback: Zero-argument function invoked (synchronously, in the
                worker process) when the button is clicked.
            enabled: Initial enabled state of the button.

        Returns:
            A :class:`_LocalButton` handle for later enabling/labeling.
        """
        from PySide6.QtWidgets import QPushButton

        from neurorehab_plugin.button_style import configure_push_button

        def _run() -> None:
            callback()
            pump_gui_events()

        button = configure_push_button(QPushButton(label, self._parent))
        button.setEnabled(bool(enabled))
        button.clicked.connect(_run)
        self._layout.addWidget(button)
        return _LocalButton(button)


class WorkerUiBridge:
    """UI proxy implementing :class:`~neurorehab_plugin.ui.PluginUi` in the worker process.

    Splits UI operations into two families:

    - Host zone buttons / clear are forwarded as ``"ui"`` events over the
      worker/host JSON protocol via :meth:`_emit` (the only host chrome
      mutations plugins may request).
    - Dialogs, tables, busy indicators, and custom floating windows
      (:meth:`open_window`) are real Qt dialogs created and owned directly
      by this worker process.
    """

    def __init__(self) -> None:
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback_id = 1
        self._button_states: dict[str, bool] = {}
        self._host_emit_enabled = False
        self._local_windows: list[Any] = []
        self._session_windows: list[Any] = []

    def _register_local_window(self, dialog: Any) -> None:
        """Track a worker-owned dialog so it can be shown after this click.

        Args:
            dialog: The ``QDialog`` instance to track.
        """
        self._local_windows.append(dialog)
        self._session_windows.append(dialog)

        def _forget(_obj: Any | None = None) -> None:
            try:
                self._local_windows.remove(dialog)
            except ValueError:
                pass
            try:
                self._session_windows.remove(dialog)
            except ValueError:
                pass

        dialog.destroyed.connect(_forget)

    def close_tracked_windows(self) -> None:
        """Close every worker-owned plugin window (used when the plugin reloads)."""
        for dialog in list(self._local_windows):
            try:
                dialog.close()
            except RuntimeError:
                pass
        self._local_windows.clear()
        self._session_windows.clear()

    def present_local_windows(self) -> dict[str, list[int]]:
        """Show windows and scripts opened by the current click, not older ones.

        The host process (which received the user click) must actually steal
        the Windows foreground; this method returns native handles / launched
        PIDs so the host can raise the window that belongs to this click.
        """
        from neurorehab_plugin.local_files import present_worker_windows
        from neurorehab_plugin.script_launcher import take_launched_script_pids

        windows = list(self._session_windows)
        self._session_windows.clear()
        hwnds = present_worker_windows(windows)
        return {
            "window_hwnds": hwnds,
            "launched_pids": take_launched_script_pids(),
        }

    def set_host_emit_enabled(self, enabled: bool) -> None:
        """Enable or disable forwarding of UI events to the host process.

        Events are only emitted while a plugin callback (``build_ui``/
        ``run``/button click) is actively executing; this flag is toggled
        around those invocations by :class:`PluginWorkerRuntime`.
        """
        self._host_emit_enabled = bool(enabled)

    def _register_callback(self, callback: Callable[[], None]) -> int:
        """Store ``callback`` under a fresh integer ID for later invocation by the host.

        Args:
            callback: Zero-argument function to register.

        Returns:
            The newly assigned callback ID.
        """
        callback_id = self._next_callback_id
        self._next_callback_id += 1
        self._callbacks[callback_id] = callback
        return callback_id

    def _emit(self, method: str, params: dict[str, Any]) -> None:
        """Send a ``"ui"`` event to the host process, if emission is currently enabled.

        Args:
            method: Name of the UI operation the host should perform.
            params: JSON-serializable parameters for the operation.
        """
        if not self._host_emit_enabled:
            return
        _send({"event": "ui", "method": method, "params": json_ready(params)})

    def add_button(
        self,
        label: str,
        callback: Callable[[], None],
        *,
        zone: str = ZONE_ENTITY_TOOLBAR,
        enabled: bool = True,
        new_row: bool | None = None,
    ) -> _RemoteButton:
        """Register a callback and ask the host to render a button in one of its zones.

        Args:
            label: Visible text of the button.
            callback: Zero-argument function invoked (via the worker
                message loop) when the host reports a click.
            zone: Target host UI zone (see
                :data:`~neurorehab_plugin.ui.PLUGIN_UI_ZONES`).
            enabled: Initial enabled state of the button.
            new_row: Layout in the plugin's group box. ``None`` keeps the
                zone default (side by side on the toolbar and Home; stacked
                elsewhere). ``False`` places the button on the current row;
                ``True`` starts a new row below.

        Returns:
            A :class:`_RemoteButton` handle for later enabling/labeling.
        """
        callback_id = self._register_callback(callback)
        button_id = f"host:{callback_id}"
        self._button_states[button_id] = bool(enabled)
        params: dict[str, Any] = {
            "button_id": button_id,
            "callback_id": callback_id,
            "label": str(label),
            "zone": str(zone),
            "enabled": bool(enabled),
        }
        if new_row is not None:
            params["new_row"] = bool(new_row)
        self._emit("add_button", params)
        return _RemoteButton(self, button_id)

    def show_message(self, title: str, text: str) -> None:
        """Show a modal message dialog in the worker process (not the host)."""
        _ensure_qt_app()
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QMessageBox
        except ImportError:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(str(title))
        box.setText(str(text))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setWindowModality(Qt.WindowModality.ApplicationModal)
        box.exec()
        pump_gui_events()

    def show_info(self, text: str) -> None:
        """Show a lightweight informational message in a worker-local dialog."""
        self.show_message("Info", str(text))

    def show_table(self, title: str, columns: list[str], rows: list[list[Any]]) -> None:
        """Display tabular data in a worker-local modal dialog."""
        _ensure_qt_app()
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import (
                QDialog,
                QPushButton,
                QTableWidget,
                QTableWidgetItem,
                QVBoxLayout,
            )
        except ImportError:
            return
        from neurorehab_plugin.button_style import configure_push_button

        dialog = QDialog()
        dialog.setWindowTitle(str(title))
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(rows), len(columns), dialog)
        table.setHorizontalHeaderLabels([str(column) for column in columns])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        close_btn = configure_push_button(QPushButton("Close", dialog))
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.resize(720, 480)
        dialog.exec()
        pump_gui_events()

    def export_csv(self, path: str, columns: list[str], rows: list[list[Any]]) -> str:
        """Write tabular data to a local CSV file (performed directly in the worker).

        Args:
            path: Destination file path.
            columns: Column header labels, written as the first CSV row.
            rows: Table rows, each a list of cell values.

        Returns:
            The path the CSV was written to.
        """
        import csv

        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for row in rows:
                writer.writerow(row)
        return path

    def clear_zone(self, zone: str) -> None:
        """Ask the host to remove all plugin-added widgets from a given zone."""
        self._emit("clear_zone", {"zone": str(zone)})

    def clear(self) -> None:
        """Ask the host to remove all plugin-added widgets from every zone."""
        self._emit("clear", {})

    def open_window(
        self,
        title: str,
        *,
        width: int = 720,
        height: int = 480,
    ) -> _LocalWindowBuilder:
        """Open a worker-owned floating Qt window (see :class:`_LocalWindowBuilder`)."""
        return _LocalWindowBuilder(self, title, width=width, height=height)

    def set_status_banner(self, text: str) -> None:
        """No-op: plugins cannot mutate the host entity-tab status banner."""
        del text

    def highlight_records(self, record_ids: list[int], color: str = "#2f6fed33") -> None:
        """No-op: plugins cannot highlight rows in the host table view."""
        del record_ids, color

    def clear_highlights(self) -> None:
        """No-op: plugins cannot clear host table highlighting."""
        return

    def run_task(self, title: str, worker: Callable[[], Any]) -> Any:
        """Run ``worker`` without a throwaway busy window.

        A short-lived ``Running…`` dialog was flashing in front of the
        real plugin window. Long work should report progress inside that
        window instead.

        Args:
            title: Unused (kept for API compatibility).
            worker: Zero-argument callable executed synchronously.

        Returns:
            Whatever ``worker()`` returns.
        """
        del title
        try:
            return worker()
        finally:
            pump_gui_events()

    def invoke_callback(self, callback_id: int) -> None:
        """Look up and invoke a previously registered callback by ID.

        Called when the host reports that the user clicked a button added
        via :meth:`add_button`.

        Args:
            callback_id: ID returned by :meth:`_register_callback` when the
                button was created.

        Raises:
            RuntimeError: If no callback is registered under ``callback_id``.
        """
        callback = self._callbacks.get(int(callback_id))
        if callback is None:
            raise RuntimeError(f"Unknown plugin callback id: {callback_id}")
        callback()
        pump_gui_events()


class _SessionPluginApi:
    """Stable API handle for plugin code; delegates to the active worker session.

    Plugin entry modules are loaded once and may keep a long-lived
    reference to the ``api`` object passed into ``build_ui``/``run``. Since
    the actual :class:`PluginApi` (with its context and
    ``allowed_record_ids``) is re-created for every single invocation (see
    :meth:`PluginWorkerRuntime._set_session_api`), this proxy forwards all
    attribute access to whichever :class:`PluginApi` is currently active,
    so plugin code always talks to the correct, freshly scoped session
    without needing to be re-handed a new object each time.
    """

    __slots__ = ("_runtime",)

    def __init__(self, runtime: "PluginWorkerRuntime") -> None:
        self._runtime = runtime

    def _api(self) -> PluginApi:
        """Return the currently active :class:`PluginApi` session.

        Raises:
            RuntimeError: If no session is currently active (i.e. called
                outside of a request being handled).
        """
        api = self._runtime._session_api
        if api is None:
            raise RuntimeError("Plugin API session is not active.")
        return api

    @property
    def context(self) -> PluginContext:
        """Return the active session's :class:`PluginContext`."""
        return self._api().context

    def close(self) -> None:
        """No-op: session lifecycle is managed by :class:`PluginWorkerRuntime`."""
        return None

    def __getattr__(self, name: str) -> Any:
        """Forward any other attribute access to the currently active :class:`PluginApi`."""
        return getattr(self._api(), name)


class PluginWorkerRuntime:
    """Owns the loaded plugin module and dispatches host request messages to it.

    Each request that needs to call into the database
    (``callback``/``build_ui``/``run``) carries its own
    ``base_url``/``token``/``context``; :meth:`_set_session_api` builds a
    fresh, correctly-scoped :class:`~neurorehab_plugin.api.PluginApi` for
    that single request and tears it down afterwards
    (:meth:`_clear_session_api`), so the read-only and
    ``allowed_record_ids`` constraints always reflect the context of the
    specific call being handled.
    """

    def __init__(self) -> None:
        self._module: ModuleType | None = None
        self._ui = WorkerUiBridge()
        self._session_api: PluginApi | None = None
        self._session_api_proxy = _SessionPluginApi(self)

    def configure(self, *, plugin_id: str, entry_path: Path) -> None:
        """Load the plugin's entry-point module, ready to receive callbacks.

        Args:
            plugin_id: Identifier of the plugin, used to name the loaded module.
            entry_path: Path to the plugin's entry-point Python file.
        """
        self._module = self._load_module(entry_path.resolve(), plugin_id)
        self._ui.close_tracked_windows()
        self._ui = WorkerUiBridge()

    @staticmethod
    def _load_module(entry_path: Path, plugin_id: str) -> ModuleType:
        """Import a plugin's entry-point file as a uniquely named module.

        Args:
            entry_path: Resolved path to the entry-point Python file.
            plugin_id: Identifier of the plugin, used to build a unique
                module name (avoiding collisions in ``sys.modules``).

        Returns:
            The executed module object.

        Raises:
            RuntimeError: If the module spec/loader cannot be created.
        """
        module_name = f"neurorehab_user_plugin_{plugin_id}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load plugin entry: {entry_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _api(self, base_url: str, token: str, context_payload: dict[str, Any]) -> PluginApi:
        """Build a new :class:`PluginApi` from a serialized context payload.

        Args:
            base_url: Base URL of the NeuroRehab server.
            token: Bearer token for the current host session.
            context_payload: Serialized :class:`PluginContext` (as produced
                by :func:`~neurorehab_plugin.worker_protocol.serialize_context`).

        Returns:
            A new :class:`PluginApi` scoped to the deserialized context.
        """
        context = deserialize_context(context_payload)
        return PluginApi(base_url, token, context)

    def _set_session_api(
        self,
        base_url: str,
        token: str,
        context_payload: dict[str, Any],
    ) -> PluginApi:
        """Close any previous session API and start a new one for the current request.

        Args:
            base_url: Base URL of the NeuroRehab server.
            token: Bearer token for the current host session.
            context_payload: Serialized :class:`PluginContext` for this request.

        Returns:
            The newly created, active :class:`PluginApi`.
        """
        if self._session_api is not None:
            self._session_api.close()
        api = self._api(base_url, token, context_payload)
        api.set_transfer_progress_callback(self._emit_transfer_progress)
        self._session_api = api
        return self._session_api

    def _emit_transfer_progress(
        self,
        current: int,
        total: int | None,
        label: str,
    ) -> None:
        """Forward a streamed download's byte counts to the host activity card."""
        self._ui._emit(
            "transfer_progress",
            {
                "current": int(current),
                "total": None if total is None else int(total),
                "label": str(label or ""),
            },
        )

    def _clear_session_api(self) -> None:
        """Close and clear the currently active session API, if any."""
        if self._session_api is not None:
            self._session_api.close()
            self._session_api = None

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single host request message and return the reply payload.

        Supported ``op`` values: ``"ping"``, ``"present_local_windows"``,
        ``"configure"`` (load the plugin module), ``"callback"`` (invoke a
        previously registered UI callback), ``"build_ui"`` (call the
        plugin's ``build_ui()``), ``"run"`` (call the plugin's ``run()``),
        and ``"on_file_chosen"`` (optional form-assist hook that returns
        ``suggested_values`` for an open Add/Edit dialog; host UI emit is
        disabled). Each of the latter (except ``configure``) establishes a
        request-scoped :class:`PluginApi` session via
        :meth:`_set_session_api` before invoking plugin code, and always
        tears it down afterwards via :meth:`_clear_session_api`.

        Args:
            message: Decoded request dict, including an ``"op"`` key and
                an ``"id"`` used to correlate the reply.

        Returns:
            A reply dict with ``id``, ``ok``, and either ``result`` (on
            success) or ``error``/``traceback`` (on failure). This method
            never raises; all exceptions are caught and reported in the
            returned dict.
        """
        request_id = message.get("id")
        op = str(message.get("op") or "")
        try:
            if op == "ping":
                return {"id": request_id, "ok": True, "result": "pong"}
            if op == "present_local_windows":
                return {
                    "id": request_id,
                    "ok": True,
                    "result": self._ui.present_local_windows(),
                }
            if op == "configure":
                entry = Path(str(message["entry_path"]))
                self.configure(plugin_id=str(message["plugin_id"]), entry_path=entry)
                _ensure_qt_app()
                return {"id": request_id, "ok": True, "result": None}
            if op == "callback":
                if self._module is None:
                    raise RuntimeError("Plugin worker is not configured.")
                self._set_session_api(
                    str(message["base_url"]),
                    str(message["token"]),
                    dict(message["context"]),
                )
                self._ui.set_host_emit_enabled(True)
                try:
                    self._ui.invoke_callback(int(message["callback_id"]))
                finally:
                    self._ui.set_host_emit_enabled(False)
                    self._clear_session_api()
                return {"id": request_id, "ok": True, "result": None}
            if self._module is None:
                raise RuntimeError("Plugin worker is not configured.")

            base_url = str(message["base_url"])
            token = str(message["token"])
            context_payload = dict(message["context"])
            self._set_session_api(base_url, token, context_payload)
            api_proxy = self._session_api_proxy
            result: Any = None
            try:
                # Keep the same WorkerUiBridge across build_ui/run/callback.
                # Replacing it dropped the only Python refs to already-open
                # QDialogs, so a selection change (which re-runs build_ui)
                # garbage-collected every plugin window.
                if op == "build_ui":
                    builder = getattr(self._module, "build_ui", None)
                    if builder is None:
                        raise RuntimeError("Plugin has no build_ui().")
                    self._ui.set_host_emit_enabled(True)
                    builder(api_proxy, api_proxy.context, self._ui)
                elif op == "run":
                    runner = getattr(self._module, "run", None)
                    if runner is None:
                        raise RuntimeError("Plugin has no run().")
                    self._ui.set_host_emit_enabled(True)
                    runner(api_proxy, api_proxy.context, self._ui)
                elif op == "on_file_chosen":
                    # Draft-form assist only: never mutate host chrome, never
                    # write to the database. The host applies suggested_values
                    # to open form widgets after validating field types/keys.
                    handler = getattr(self._module, "on_file_chosen", None)
                    if handler is None:
                        result = {"suggested_values": {}}
                    else:
                        self._ui.set_host_emit_enabled(False)
                        raw_variant = message.get("variant_id")
                        variant_id = (
                            int(raw_variant) if raw_variant is not None else None
                        )
                        raw = handler(
                            api_proxy,
                            api_proxy.context,
                            self._ui,
                            field_key=str(message.get("field_key") or ""),
                            local_path=str(message.get("local_path") or ""),
                            draft=dict(message.get("draft") or {}),
                            variant_id=variant_id,
                            form_mode=str(message.get("form_mode") or "add"),
                        )
                        result = _normalize_on_file_chosen_result(raw)
                else:
                    raise RuntimeError(f"Unknown worker operation: {op}")
            finally:
                self._clear_session_api()
                self._ui.set_host_emit_enabled(False)
            return {"id": request_id, "ok": True, "result": json_ready(result)}
        except Exception as exc:
            self._ui.set_host_emit_enabled(False)
            return {
                "id": request_id,
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }


def main() -> int:
    """Run the plugin worker's main message loop.

    Starts a background thread reading newline-delimited JSON messages
    from stdin into a queue, sends a ``{"event": "ready"}`` announcement,
    then repeatedly pumps GUI events and processes queued messages via
    :class:`PluginWorkerRuntime`, writing each response back to stdout.
    Terminates on stdin EOF (returns ``1``) or an explicit ``"shutdown"``
    op (returns ``0``).

    Returns:
        Process exit code: ``0`` on graceful shutdown, ``1`` if stdin
        closed unexpectedly.
    """
    # Before any plugin code: children must not inherit this process's stdin
    # (host IPC). Omitting stdin= on Popen used to hang analysis CLIs for
    # many minutes while the same command finished quickly outside the worker.
    from neurorehab_plugin.safe_subprocess import (
        install_worker_subprocess_stdin_guard,
    )

    install_worker_subprocess_stdin_guard()
    _ensure_import_paths()
    _ensure_qt_app()
    runtime = PluginWorkerRuntime()
    messages: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def _stdin_reader() -> None:
        """Continuously read JSON messages from stdin into ``messages``, until EOF."""
        while True:
            try:
                messages.put(_read())
            except EOFError:
                messages.put(None)
                return

    threading.Thread(target=_stdin_reader, daemon=True).start()
    _send({"event": "ready"})
    while True:
        pump_gui_events()
        try:
            message = messages.get(timeout=0.03)
        except queue.Empty:
            continue
        if message is None:
            return 1
        if str(message.get("op") or "") == "shutdown":
            _send({"event": "shutdown", "ok": True})
            return 0
        response = runtime.handle(message)
        _send(response)
        if response.get("ok") is False:
            details = str(response.get("traceback") or response.get("error") or "")
            if details:
                sys.stderr.write(details + "\n")
                sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
