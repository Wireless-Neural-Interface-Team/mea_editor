"""Launch the MEA editor from the NeuroRehab plugin.

View mapping opens a window with the two maps and an Edit button. Edit starts
the full editor on that same local JSON. Save stays on disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REQUEST_NAME = ".mea_editor_open.json"
SESSION_NAME = ".mea_editor_session.json"
COMMAND_NAME = ".mea_editor_command.json"
VIEWER_SESSION_NAME = ".mea_editor_viewer_session.json"
VIEWER_COMMAND_NAME = ".mea_editor_viewer_command.json"


def _prepare_import_path() -> None:
    """Find the mea_editor package beside this script or in the parent repo."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent):
        if (candidate / "mea_editor" / "__init__.py").is_file():
            folder = str(candidate)
            if folder not in sys.path:
                sys.path.insert(0, folder)
            return
    raise SystemExit(
        "mea_editor package was not found next to the plugin or in the parent folder."
    )


def _requested_launch() -> tuple[str | None, str | None, bool]:
    """Read and clear the one-shot launch note written by the plugin button.

    A path on the command line is the full editor (the viewer's Edit button)
    and must not consume a viewer request still waiting to be read.
    """
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1], None, False
    path: str | None = None
    token: str | None = None
    view_only = False
    request = Path(__file__).resolve().parent / REQUEST_NAME
    if not request.is_file():
        return None, None, False
    try:
        payload = json.loads(request.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    finally:
        try:
            request.unlink()
        except OSError:
            pass
    if isinstance(payload, dict):
        if payload.get("path"):
            path = str(payload["path"])
        if payload.get("token"):
            token = str(payload["token"])
        view_only = bool(payload.get("view_only"))
    return path, token, view_only


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _write_command(command: Path, token: str, path: str) -> None:
    seq = 1
    try:
        current = json.loads(command.read_text(encoding="utf-8"))
        if isinstance(current, dict):
            seq = int(current.get("seq") or 0) + 1
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        seq = 1
    command.write_text(
        json.dumps({"token": token, "seq": seq, "path": path}),
        encoding="utf-8",
    )


def _open_full_editor(path: str) -> None:
    """Open the full MEA editor on ``path``, reusing one that is already running."""
    root = Path(__file__).resolve().parent
    session_path = root / SESSION_NAME
    try:
        session = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        session = None
    if isinstance(session, dict):
        pid = session.get("pid")
        token = session.get("token")
        if isinstance(pid, int) and token and _pid_alive(pid):
            _write_command(root / COMMAND_NAME, str(token), path)
            return
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), path],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
    )


def _install_command_watcher(
    win,
    command_dir: Path,
    token: str,
    *,
    session_name: str,
    command_name: str,
) -> None:
    """Load JSON paths posted for this window."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    session = command_dir / session_name
    session.write_text(
        json.dumps({"pid": os.getpid(), "token": token}),
        encoding="utf-8",
    )
    seen: dict[str, object] = {"seq": None}

    def cleanup() -> None:
        try:
            current = json.loads(session.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if int(current.get("pid") or 0) != os.getpid():
            return
        try:
            session.unlink()
        except OSError:
            pass

    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(cleanup)

    def poll() -> None:
        command = command_dir / command_name
        try:
            payload = json.loads(command.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or str(payload.get("token") or "") != token:
            return
        seq = payload.get("seq")
        if seq == seen["seq"]:
            return
        seen["seq"] = seq
        error = str(payload.get("error") or "").strip()
        if error:
            win._set_loading_visible(False)
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(win, "Open JSON mapping", error)
            return
        file_path = payload.get("path")
        if not file_path:
            return
        if win.is_dirty and not win._view_only and not win._confirm_before_replace("open an array"):
            return
        win.load_local_file(str(file_path))
        win.raise_()
        win.activateWindow()

    timer = QTimer(win)
    timer.setInterval(50)
    timer.timeout.connect(poll)
    timer.start()
    QTimer.singleShot(0, poll)


def main() -> None:
    command_dir = Path(__file__).resolve().parent
    path, token, view_only = _requested_launch()
    _prepare_import_path()
    from mea_editor.electrode_array_editor_qt import run_app

    def on_ready(win) -> None:
        if view_only:
            win.set_edit_launcher(_open_full_editor)
        if token:
            _install_command_watcher(
                win,
                command_dir,
                token,
                session_name=VIEWER_SESSION_NAME if view_only else SESSION_NAME,
                command_name=VIEWER_COMMAND_NAME if view_only else COMMAND_NAME,
            )
        if path:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, lambda: win.load_local_file(path))

    run_app(on_ready=on_ready, view_only=view_only, skip_startup=bool(path))


if __name__ == "__main__":
    main()
