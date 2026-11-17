"""Launch Python scripts in the plugin venv (external GUI).

Provides :func:`launch_plugin_script`, used by
:meth:`~neurorehab_plugin.api.PluginApi.launch_script` to start a plugin's
own Python script as a separate, detached process running under the
plugin's dedicated virtual environment interpreter (rather than the host
application's interpreter). This is intended for launching auxiliary
external GUIs bundled with a plugin.

Security note: :func:`_resolve_script` restricts launchable scripts to
files located inside the plugin's own root directory, preventing a plugin
from launching arbitrary scripts elsewhere on disk.

Stdout/stderr of the child (plus a rich diagnostic header) are written to
``.plugin_script_launch.log`` inside the plugin root, overwritten on each
launch, so the last run can be inspected without a console. A timestamped
``launch-YYYYMMDD-HHMMSS.log`` copy is also kept (last 5 archives).

On Windows the child is started with ``pythonw.exe`` when present so no
console is allocated. ``STARTF_USESHOWWINDOW``/``SW_HIDE`` is not used:
Windows applies that flag to the process's first ``ShowWindow``, which
is the Qt GUI itself (hidden then shown = blink).
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from neurorehab_plugin.subprocess_env import sanitize_plugin_subprocess_env

LAUNCH_LOG_NAME = ".plugin_script_launch.log"
_LAUNCH_HISTORY_PREFIX = "launch-"
_LAUNCH_HISTORY_GLOB = "launch-*.log"
_LAUNCH_HISTORY_KEEP = 5

# PIDs of GUIs started by :func:`launch_plugin_script` during the current
# worker callback. The host consumes them (via :func:`take_launched_script_pids`)
# so it can raise those windows itself — only the process that received the
# click is allowed to steal the Windows foreground.
_LAUNCHED_PIDS: list[int] = []


def _rotate_launch_logs(root: Path, log_path: Path) -> None:
    """Keep ``.plugin_script_launch.log`` as latest and archive a timestamped copy.

    Caps archived ``launch-YYYYMMDD-HHMMSS.log`` files to the last
    ``_LAUNCH_HISTORY_KEEP`` entries (oldest deleted first).
    """
    if not log_path.is_file():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = root / f"{_LAUNCH_HISTORY_PREFIX}{stamp}.log"
    try:
        import shutil

        shutil.copy2(log_path, archive)
    except OSError:
        return
    try:
        archives = sorted(
            root.glob(_LAUNCH_HISTORY_GLOB),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError:
        return
    excess = len(archives) - _LAUNCH_HISTORY_KEEP
    for old in archives[: max(0, excess)]:
        try:
            old.unlink()
        except OSError:
            pass


def remember_launched_pid(pid: int | None) -> None:
    """Record a child PID so the host can bring its window to the front."""
    try:
        pid_int = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return
    if pid_int > 0:
        _LAUNCHED_PIDS.append(pid_int)


def take_launched_script_pids() -> list[int]:
    """Return and clear PIDs recorded since the last take."""
    pids = list(_LAUNCHED_PIDS)
    _LAUNCHED_PIDS.clear()
    return pids

# Windows process-creation flags (numeric fallbacks so tests can run off Windows).
_CREATE_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
_CREATE_NEW_PROCESS_GROUP = int(
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
)


def _is_windows() -> bool:
    return os.name == "nt"


def _gui_python(python_exe: Path) -> Path:
    """Interpreter for GUI scripts (``pythonw.exe`` on Windows when available)."""
    if _is_windows() and python_exe.name.lower() == "python.exe":
        gui = python_exe.with_name("pythonw.exe")
        if gui.is_file():
            return gui
    return python_exe


def _launch_process_kwargs(*, detached: bool, hide_console: bool) -> dict[str, object]:
    """Start the GUI child; optionally detach it.

    Do not pass ``STARTF_USESHOWWINDOW``/``SW_HIDE``: Windows uses that as
    the first ``ShowWindow`` of the process, which is the Qt window, so the
    GUI is created hidden and then shown (visible blink).

    ``CREATE_NO_WINDOW`` is only for a ``python.exe`` fallback (no
    ``pythonw.exe``). ``pythonw`` already has no console; the flag can
    interfere with the first GUI window.
    """
    if not _is_windows():
        if detached:
            return {"start_new_session": True}
        return {}
    kwargs: dict[str, object] = {"stdin": subprocess.DEVNULL}
    flags = 0
    if hide_console:
        flags |= _CREATE_NO_WINDOW
    if detached:
        flags |= _CREATE_NEW_PROCESS_GROUP
    if flags:
        kwargs["creationflags"] = flags
    return kwargs


def _allow_child_foreground(pid: int | None) -> None:
    """Let the launched GUI take focus without the host stealing it back."""
    if pid is None or sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except Exception:
        pass


def _resolve_python(
    plugin_root: Path,
    plugin_id: str,
    plugin_python: Path | None,
) -> Path:
    """Resolve the Python interpreter to use for launching a plugin script.

    Resolution order: an explicitly provided ``plugin_python`` path, then
    the ``NR_PLUGIN_PYTHON`` environment variable, then a venv located at
    ``$NR_PLUGINS_ROOT/venvs/<id>@<version>/`` (platform-appropriate
    ``Scripts/python.exe`` or ``bin/python``). The host passes the runtime
    instance key (``id@version``) as ``plugin_id`` when resolving the venv.

    Args:
        plugin_root: Resolved root directory of the plugin (unused for
            resolution but kept for symmetry/future use).
        plugin_id: Identifier of the plugin, used to locate its venv.
        plugin_python: Optional explicit interpreter path, checked first.

    Returns:
        Path to a Python interpreter executable.

    Raises:
        FileNotFoundError: If no valid interpreter can be resolved.
    """
    if plugin_python is not None and plugin_python.is_file():
        return plugin_python
    env_python = os.environ.get("NR_PLUGIN_PYTHON", "").strip()
    if env_python:
        path = Path(env_python)
        if path.is_file():
            return path
    plugins_root = os.environ.get("NR_PLUGINS_ROOT", "").strip()
    if plugins_root:
        venv_dir = Path(plugins_root) / "venvs" / plugin_id
        if os.name == "nt":
            candidate = venv_dir / "Scripts" / "python.exe"
        else:
            candidate = None
            for name in ("python", "python3"):
                path = venv_dir / "bin" / name
                if path.exists():
                    candidate = path
                    break
            if candidate is None:
                candidate = venv_dir / "bin" / "python"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Plugin Python interpreter not found.\n"
        f"- Plugin: {plugin_id}\n"
        f"- Expected venv under: plugins/venvs/{plugin_id}/\n"
        f"  (plugin_id is normally id@version for installed packages)\n"
        "Reinstall or reactivate the plugin to recreate the venv "
        "(requirements.txt)."
    )


def _resolve_script(plugin_root: Path, relative_path: str) -> Path:
    """Resolve and validate the script path requested for launch.

    Security constraint: the resolved script must be a file located inside
    ``plugin_root`` (checked via ``root in script.parents`` after both
    paths are resolved), preventing path-traversal outside the plugin's
    own directory.

    Args:
        plugin_root: Root directory of the plugin.
        relative_path: Path to the script, relative to ``plugin_root``.

    Returns:
        The resolved absolute path to the script.

    Raises:
        FileNotFoundError: If the resolved path is not a file.
        ValueError: If the resolved path escapes ``plugin_root``.
    """
    root = plugin_root.resolve()
    script = (root / relative_path).resolve()
    if not script.is_file():
        raise FileNotFoundError(f"Script not found: {relative_path}")
    if root not in script.parents:
        raise ValueError(f"Script must stay inside the plugin folder: {relative_path}")
    return script


def _safe_getcwd() -> str:
    try:
        return os.getcwd()
    except OSError as exc:
        return f"<unavailable: {exc}>"


def _filtered_env_lines(env: dict[str, str]) -> list[str]:
    keys = sorted(
        key
        for key in env
        if key.startswith("NR_")
        or key
        in {
            "PATH",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "PYTHONUNBUFFERED",
            "PYTHONIOENCODING",
            "PYTHONFAULTHANDLER",
            "PYTHONWARNINGS",
            "USERNAME",
            "USER",
        }
    )
    lines: list[str] = []
    for key in keys:
        value = env.get(key, "")
        if any(token in key.upper() for token in ("PASS", "SECRET", "TOKEN", "KEY", "PWD")):
            lines.append(f"#   {key}=<redacted>")
        elif key == "PATH":
            lines.append(f"#   {key}=<{len(value)} chars>")
        else:
            lines.append(f"#   {key}={value}")
    return lines or ["#   (none)"]


def _write_launch_log_header(
    log_file,
    *,
    plugin_id: str,
    plugin_root: Path,
    python_exe: Path,
    script: Path,
    env: dict[str, str],
    detached: bool,
    check_delay: float,
) -> None:
    """Write a diagnostic header so each overwritten log is self-describing."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    host_frozen = bool(getattr(sys, "frozen", False))
    meipass = getattr(sys, "_MEIPASS", None)
    lines = [
        "# --- NeuroRehab plugin script launch ---",
        f"# time: {stamp}",
        f"# plugin_id: {plugin_id}",
        f"# plugin_root: {plugin_root}",
        f"# script: {script}",
        f"# python: {python_exe}",
        f"# python_version: {sys.version.replace(chr(10), ' ')}",
        f"# command: {python_exe} -u {script}",
        f"# detached: {detached}",
        f"# check_delay_s: {check_delay}",
        f"# host_frozen: {host_frozen}",
        f"# host_executable: {sys.executable}",
        f"# host_argv: {sys.argv!r}",
        f"# host_cwd: {_safe_getcwd()}",
        f"# host_python: {sys.version.replace(chr(10), ' ')}",
        f"# platform: {platform.platform()}",
        f"# machine: {platform.machine()} processor={platform.processor()!r}",
        f"# host_pid: {os.getpid()}",
    ]
    if meipass:
        lines.append(f"# host_MEIPASS: {meipass}")
    lines.append("# child_env (filtered):")
    lines.extend(_filtered_env_lines(env))
    lines.append("# --- begin stdout+stderr (child process) ---")
    log_file.write("\n".join(lines) + "\n")
    log_file.flush()


def _raise_launch_error(
    *,
    returncode: int,
    script: Path,
    python_exe: Path,
    log_path: Path,
) -> None:
    """Raise a :class:`RuntimeError` describing why a launched script exited immediately.

    Args:
        returncode: Non-zero exit code returned by the subprocess.
        script: Path to the script that was launched.
        python_exe: Interpreter used to launch the script.
        log_path: Path to the captured stdout/stderr log file, if any.

    Raises:
        RuntimeError: Always; this function never returns normally.
    """
    details = ""
    if log_path.is_file():
        details = log_path.read_text(encoding="utf-8", errors="replace").strip()
    raise RuntimeError(
        f"The script exited immediately (code {returncode}).\n"
        f"Script: {script.name}\n"
        f"Python: {python_exe}\n"
        f"{details or 'No details in the log.'}"
    )


def launch_plugin_script(
    *,
    plugin_id: str,
    plugin_root: Path,
    relative_path: str,
    plugin_python: Path | None = None,
    detached: bool = True,
    check_delay: float = 0,
) -> int | None:
    """Launch a plugin Python script with the plugin venv interpreter.

    Starts ``relative_path`` (resolved and validated to stay inside
    ``plugin_root`` by :func:`_resolve_script`) as a subprocess using the
    plugin's dedicated Python interpreter (resolved by
    :func:`_resolve_python`). The child process inherits a **sanitized**
    copy of the current environment (passwords, JWT secrets, and similar
    keys are stripped — see
    :func:`~neurorehab_plugin.subprocess_env.sanitize_plugin_subprocess_env`)
    plus ``NR_PLUGIN_ID``, ``NR_PLUGIN_ROOT``,
    ``NR_PLUGIN_PYTHON``, and (if set) ``NR_PLUGINS_ROOT``. Stdout and
    stderr are captured to a ``.plugin_script_launch.log`` file inside the
    plugin root (overwritten on each launch) for diagnosing failures when
    the host has no console. The child also gets ``PYTHONFAULTHANDLER`` /
    ``PYTHONWARNINGS`` so crashes and warnings appear in that log. On Windows
    the GUI is launched with ``pythonw.exe`` when available (no console).
    ``SW_HIDE`` is not passed: it would hide-then-show the Qt window.

    Args:
        plugin_id: Identifier of the plugin, used to locate its venv and
            passed to the child process via environment variables.
        plugin_root: Root directory of the plugin; the script must reside
            within this directory.
        relative_path: Path to the script to launch, relative to
            ``plugin_root``.
        plugin_python: Optional explicit interpreter path (see
            :func:`_resolve_python` for the full resolution order).
        detached: If True, the child process is started in its own process
            group/session so it survives independently of the host process.
        check_delay: Seconds to wait and poll for an early (non-zero) exit
            before returning. Default 0 so the host is not pumping events
            while the GUI appears (that steal of focus made the window blink).

    Raises:
        FileNotFoundError: If no interpreter or script can be resolved.
        ValueError: If the script path escapes ``plugin_root``.
        RuntimeError: If the script exits with a non-zero code within
            ``check_delay`` seconds.

    Returns:
        PID of the child process, or ``None`` if it was not available.
    """
    root = plugin_root.resolve()
    python_exe = _resolve_python(root, plugin_id, plugin_python)
    launch_python = _gui_python(python_exe)
    script = _resolve_script(root, relative_path)
    log_path = root / LAUNCH_LOG_NAME

    env = sanitize_plugin_subprocess_env(os.environ)
    env["NR_PLUGIN_ID"] = plugin_id
    env["NR_PLUGIN_ROOT"] = str(root)
    env["NR_PLUGIN_PYTHON"] = str(python_exe)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Surface warnings and hard-crash traces into the captured stdout/stderr log.
    env.setdefault("PYTHONFAULTHANDLER", "1")
    env.setdefault("PYTHONWARNINGS", "default")
    plugins_root = os.environ.get("NR_PLUGINS_ROOT", "").strip()
    if plugins_root:
        env["NR_PLUGINS_ROOT"] = plugins_root

    popen_kwargs: dict[str, object] = {
        "cwd": str(root),
        "env": env,
        **_launch_process_kwargs(
            detached=detached,
            hide_console=launch_python.name.lower() != "pythonw.exe",
        ),
    }

    with open(log_path, "w", encoding="utf-8") as log_file:
        _write_launch_log_header(
            log_file,
            plugin_id=plugin_id,
            plugin_root=root,
            python_exe=launch_python,
            script=script,
            env=env,
            detached=detached,
            check_delay=check_delay,
        )
        popen_kwargs["stdout"] = log_file
        popen_kwargs["stderr"] = subprocess.STDOUT
        # -u: unbuffered stdio so lines appear in the log promptly.
        process = subprocess.Popen(
            [str(launch_python), "-u", str(script)],
            **popen_kwargs,
        )
        _allow_child_foreground(process.pid)
        remember_launched_pid(process.pid)

        timeout = max(0.0, float(check_delay))
        deadline = time.monotonic() + timeout
        while True:
            returncode = process.poll()
            if returncode is not None:
                if returncode != 0:
                    # Flush before raising so the archive captures the failure.
                    log_file.flush()
                    _rotate_launch_logs(root, log_path)
                    _raise_launch_error(
                        returncode=returncode,
                        script=script,
                        python_exe=launch_python,
                        log_path=log_path,
                    )
                break
            if timeout <= 0 or time.monotonic() >= deadline:
                break
            time.sleep(min(0.05, deadline - time.monotonic()))
    _rotate_launch_logs(root, log_path)
    try:
        return int(process.pid)
    except (TypeError, ValueError):
        return None
