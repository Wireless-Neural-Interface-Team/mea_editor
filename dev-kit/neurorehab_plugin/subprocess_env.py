"""Strip secrets from the environment inherited by plugin subprocesses.

Plugin workers and launched plugin scripts copy the host process environment
by default. If the desktop client was started from a shell that also holds
server secrets (``NR_PG_PASSWORD``, ``NR_JWT_SECRET``, ``PGPASSWORD``, …), a
malicious plugin could read them and write to PostgreSQL outside the
read-only plugin API. This module drops those keys before ``Popen``.
"""

from __future__ import annotations

import os

# Substrings matched against the upper-cased variable name.
_SECRET_SUBSTRINGS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "API_KEY",
)

# Exact names that do not contain the substrings above (libpq / DSNs).
_SECRET_EXACT = frozenset(
    {
        "PGPASSWORD",
        "PGPASSFILE",
        "DATABASE_URL",
        "NR_DATABASE_URL",
    }
)


def is_secret_env_key(key: str) -> bool:
    """Return whether ``key`` looks like a credential or signing secret."""
    upper = str(key or "").strip().upper()
    if not upper:
        return False
    if upper in _SECRET_EXACT:
        return True
    # ``MYSQL_PWD`` / ``*_PWD`` — but never ``PWD`` (working directory).
    if upper.endswith("_PWD"):
        return True
    return any(token in upper for token in _SECRET_SUBSTRINGS)


def sanitize_plugin_subprocess_env(
    source: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a copy of ``source`` (default: ``os.environ``) without secrets.

    Keeps ``PATH``, ``HOME``, ``PYTHONPATH``, Qt/Windows variables, and
    ``NR_PLUGIN_*`` identity keys so the worker GUI still starts.
    """
    env = dict(os.environ if source is None else source)
    return {key: value for key, value in env.items() if not is_secret_env_key(key)}
