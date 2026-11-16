"""HTTP transport limited to ``/api/v1/plugin/*`` routes.

This module implements the low-level HTTP client used by
:class:`~neurorehab_plugin.api.PluginApi`. Its most important security
property is enforced in :meth:`PluginTransport.request`: every outgoing
request path is validated to start with ``/api/v1/plugin/``, so a plugin
(or a bug in plugin code) can never reach unrelated server endpoints
through this transport, regardless of the operation name passed to the
higher-level API layer.
"""

from __future__ import annotations

import http.client
import json
import posixpath
import ssl
import threading
import urllib.parse
from typing import Any

from neurorehab_plugin.errors import PluginApiError, PluginWriteForbiddenError
from neurorehab_plugin.local_files import pump_gui_events

_TRANSIENT_HTTP_ERRORS = (
    ConnectionError,
    ConnectionAbortedError,
    ConnectionResetError,
    BrokenPipeError,
    http.client.CannotSendRequest,
    http.client.RemoteDisconnected,
    OSError,
)


class PluginTransport:
    """HTTP client scoped to ``/api/v1/plugin/*`` with keep-alive and one reconnect retry.

    Security constraint: :meth:`request` refuses (raises
    :class:`~neurorehab_plugin.errors.PluginWriteForbiddenError`) any request
    whose path is not under ``/api/v1/plugin/``, regardless of HTTP method.
    This confines the plugin SDK's network surface to plugin-specific,
    read-only server routes.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        plugin_id: str = "",
    ) -> None:
        """Create a transport bound to a host session.

        Args:
            base_url: Base URL of the NeuroRehab server (scheme + host + port).
            access_token: Bearer token sent as ``Authorization`` header on
                every request.
            plugin_id: Optional plugin identifier sent as the
                ``X-NR-Plugin-Id`` header, used by the server for auditing
                and scoping.
        """
        self.base_url = (base_url or "").strip().rstrip("/")
        self.access_token = (access_token or "").strip()
        self.plugin_id = str(plugin_id or "").strip()
        parsed = urllib.parse.urlparse(self.base_url)
        self._scheme = parsed.scheme or "http"
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or (443 if self._scheme == "https" else 80)
        self._conn: http.client.HTTPConnection | http.client.HTTPSConnection | None = None
        self._lock = threading.RLock()

    def close(self) -> None:
        """Close the underlying keep-alive HTTP connection, if any (idempotent)."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def _open_connection(self) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        """Create a new HTTP(S) connection based on the parsed base URL scheme."""
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._host,
                self._port,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(self._host, self._port)

    def _get_connection(self) -> http.client.HTTPConnection | http.client.HTTPSConnection:
        """Return the cached connection, opening a new one if needed."""
        if self._conn is None:
            self._conn = self._open_connection()
        return self._conn

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: int = 600,
    ) -> bytes:
        """Send an HTTP request restricted to plugin routes and return the raw body.

        Security constraint: only paths starting with ``/api/v1/plugin/``
        are allowed; anything else raises
        :class:`~neurorehab_plugin.errors.PluginWriteForbiddenError` before
        any network I/O happens.

        On a transient connection error (e.g. dropped keep-alive), the
        connection is closed and the request is retried once with a fresh
        connection.

        Args:
            method: HTTP method (e.g. ``"GET"``, ``"POST"``).
            path: Request path; must start with ``/api/v1/plugin/``.
            json_body: Optional JSON-serializable request body.
            timeout: Socket timeout in seconds.

        Returns:
            Raw response body bytes.

        Raises:
            PluginWriteForbiddenError: If ``path`` is outside the allowed
                ``/api/v1/plugin/`` prefix.
            PluginApiError: If the server responds with an HTTP status >= 400.
        """
        if not posixpath.normpath(path).startswith("/api/v1/plugin/"):
            raise PluginWriteForbiddenError(
                "Plugin SDK can only access /api/v1/plugin/* routes."
            )
        url_path = path if path.startswith("/") else f"/{path}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "NeuroRehab-database-PluginSDK/1.0",
            "Connection": "keep-alive",
            "Authorization": f"Bearer {self.access_token}",
        }
        if self.plugin_id:
            headers["X-NR-Plugin-Id"] = self.plugin_id
        payload = None
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        with self._lock:
            for attempt in range(2):
                conn = self._get_connection()
                try:
                    conn.timeout = timeout
                    conn.request(method, url_path, body=payload, headers=headers)
                    response = conn.getresponse()
                    data = response.read()
                    pump_gui_events()
                    if response.status >= 400:
                        detail = data.decode("utf-8", errors="replace")
                        try:
                            parsed = json.loads(detail)
                            message = parsed.get("detail") or parsed.get("message") or detail
                        except (TypeError, ValueError):
                            message = detail or response.reason
                        raise PluginApiError(f"API {response.status}: {message}")
                    return data
                except PluginApiError:
                    raise
                except _TRANSIENT_HTTP_ERRORS as exc:
                    last_error = exc
                    self.close()
                    if attempt == 0:
                        continue
                    break
        if last_error is not None:
            raise last_error
        raise RuntimeError("Plugin HTTP request failed.")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: int = 600,
    ) -> Any:
        """Like :meth:`request`, but parses the response body as JSON.

        Args:
            method: HTTP method.
            path: Request path; must start with ``/api/v1/plugin/``.
            json_body: Optional JSON-serializable request body.
            timeout: Socket timeout in seconds.

        Returns:
            The parsed JSON value, or ``None`` if the response body is empty.
        """
        body = self.request(method, path, json_body=json_body, timeout=timeout)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def download_bytes(self, logical_key: str) -> bytes:
        """Download raw file bytes from plugin storage by logical key.

        Args:
            logical_key: Storage-relative path (backslashes normalized to
                forward slashes, leading/trailing slashes stripped, then
                URL-encoded) identifying the file to download.

        Returns:
            Raw file content as bytes.
        """
        encoded = urllib.parse.quote(
            logical_key.replace("\\", "/").strip("/"), safe="/"
        )
        return self.request("GET", f"/api/v1/plugin/storage/{encoded}")
