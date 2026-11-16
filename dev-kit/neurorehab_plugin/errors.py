"""Plugin SDK exceptions."""

from __future__ import annotations


class PluginApiError(RuntimeError):
    """Base error for failures returned by the plugin API/transport layer.

    Raised for any non-2xx HTTP response from the ``/api/v1/plugin/*``
    server routes (see :meth:`~neurorehab_plugin.transport.PluginTransport.request`).
    """

    pass


class PluginWriteForbiddenError(PluginApiError):
    """Raised when a plugin attempts a disallowed write or restricted operation.

    This is the exception used to enforce the SDK's core security
    constraints:

    - Blocking operation names that look like writes (see
      :meth:`~neurorehab_plugin.api.PluginApi._assert_readonly_op`).
    - Blocking access to team/account lookup operations that plugins may
      never call.
    - Blocking any HTTP request outside the ``/api/v1/plugin/*`` route
      prefix (see :meth:`~neurorehab_plugin.transport.PluginTransport.request`).
    """

    pass
