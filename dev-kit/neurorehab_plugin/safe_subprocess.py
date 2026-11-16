"""Safe subprocess helpers for plugin workers.

The NeuroRehab plugin worker speaks a JSON line protocol on **its own**
``stdin`` / ``stdout`` with the desktop host. Any child process that inherits
that stdin can steal or block protocol traffic and hang for a long time
(often looking like a "slow" analysis). Standalone scripts do not hit this
because their stdin is a normal console.

This module:

- patches ``subprocess.Popen`` inside the worker so omitted / ``None`` stdin
  becomes ``DEVNULL`` (``PIPE`` / file objects are unchanged);
- exposes :func:`popen` / :func:`run` for plugin authors who want an explicit
  safe API.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any

_GUARD_INSTALLED = False
_ORIGINAL_POPEN: type[subprocess.Popen] | None = None

# subprocess.Popen positional layout after ``args``:
#   bufsize, executable, stdin, stdout, stderr, ...
_POPEN_STDIN_POSITIONAL_INDEX = 3


def _coerce_stdin(value: Any) -> Any:
    """Replace inherited-stdin (``None``) with ``DEVNULL``; keep explicit streams."""
    if value is None:
        return subprocess.DEVNULL
    return value


def _guarded_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
    """``subprocess.Popen`` wrapper that never inherits the worker IPC stdin."""
    original = _ORIGINAL_POPEN or subprocess.Popen
    if len(args) > _POPEN_STDIN_POSITIONAL_INDEX:
        positional = list(args)
        positional[_POPEN_STDIN_POSITIONAL_INDEX] = _coerce_stdin(
            positional[_POPEN_STDIN_POSITIONAL_INDEX]
        )
        return original(*positional, **kwargs)
    kwargs["stdin"] = _coerce_stdin(kwargs.get("stdin"))
    return original(*args, **kwargs)


def install_worker_subprocess_stdin_guard() -> bool:
    """Install the worker-wide ``Popen`` stdin guard (idempotent).

    Called once from :func:`neurorehab_plugin.worker_main.main` before plugin
    code runs. Returns ``True`` when this call performed the install.
    """
    global _GUARD_INSTALLED, _ORIGINAL_POPEN
    if _GUARD_INSTALLED:
        return False
    _ORIGINAL_POPEN = subprocess.Popen
    subprocess.Popen = _guarded_popen  # type: ignore[misc, assignment]
    _GUARD_INSTALLED = True
    return True


def uninstall_worker_subprocess_stdin_guard() -> None:
    """Restore the original ``subprocess.Popen`` (tests only)."""
    global _GUARD_INSTALLED, _ORIGINAL_POPEN
    if not _GUARD_INSTALLED:
        return
    if _ORIGINAL_POPEN is not None:
        subprocess.Popen = _ORIGINAL_POPEN  # type: ignore[misc]
    _ORIGINAL_POPEN = None
    _GUARD_INSTALLED = False


def popen(
    args: str | Sequence[str],
    **kwargs: Any,
) -> subprocess.Popen[Any]:
    """Like :class:`subprocess.Popen`, but never inherits the worker IPC stdin.

    Prefer this (or plain ``subprocess.Popen`` after the worker guard is
    installed) when launching analysis CLIs, helpers, or tools from a plugin.
    Pass ``stdin=subprocess.PIPE`` explicitly when you need to write to the
    child.
    """
    kwargs["stdin"] = _coerce_stdin(kwargs.get("stdin"))
    return subprocess.Popen(args, **kwargs)


def run(
    args: str | Sequence[str],
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Like :func:`subprocess.run`, but never inherits the worker IPC stdin."""
    kwargs["stdin"] = _coerce_stdin(kwargs.get("stdin"))
    return subprocess.run(args, **kwargs)
