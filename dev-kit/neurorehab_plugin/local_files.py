"""Local helpers: temporary files and opening with the default application."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_CACHE_DIRNAME = "neurorehab-plugin-files"
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def pump_gui_events() -> None:
    """Process pending Qt events for the current application, if any.

    Best-effort: silently does nothing when PySide6 is not installed or
    there is no running :class:`QApplication`. Used after network/IO calls
    so worker Qt windows stay responsive during synchronous operations.
    """
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass


def _worker_window_is_valid(window: Any) -> bool:
    """Return True if ``window`` is a live (non-deleted) Qt widget.

    Prefers the Qt binding's ``shiboken6.isValid`` check; falls back to
    probing ``isVisible()`` and treating a ``RuntimeError`` (raised by Qt
    when the underlying C++ object was destroyed) as invalid.
    """
    if window is None:
        return False
    try:
        from shiboken6 import isValid

        return bool(isValid(window))
    except ImportError:
        pass
    try:
        window.isVisible()
        return True
    except RuntimeError:
        return False


_USER32 = None
_WNDENUMPROC = None


def _hwnd_as_int(hwnd: object) -> int:
    if hwnd is None:
        return 0
    value = getattr(hwnd, "value", hwnd)
    if value is None:
        return 0
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _user32():
    """user32 with 64-bit HWND prototypes. Unprototyped ctypes truncates handles."""
    global _USER32, _WNDENUMPROC
    if _USER32 is not None:
        return _USER32
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd_t = wintypes.HWND
    bool_t = wintypes.BOOL
    user32.GetForegroundWindow.restype = hwnd_t
    user32.GetForegroundWindow.argtypes = []
    user32.IsWindow.restype = bool_t
    user32.IsWindow.argtypes = [hwnd_t]
    user32.IsWindowVisible.restype = bool_t
    user32.IsWindowVisible.argtypes = [hwnd_t]
    user32.IsIconic.restype = bool_t
    user32.IsIconic.argtypes = [hwnd_t]
    user32.ShowWindow.restype = bool_t
    user32.ShowWindow.argtypes = [hwnd_t, ctypes.c_int]
    user32.BringWindowToTop.restype = bool_t
    user32.BringWindowToTop.argtypes = [hwnd_t]
    user32.SetForegroundWindow.restype = bool_t
    user32.SetForegroundWindow.argtypes = [hwnd_t]
    user32.SetWindowPos.restype = bool_t
    user32.SetWindowPos.argtypes = [
        hwnd_t,
        hwnd_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.GetWindow.restype = hwnd_t
    user32.GetWindow.argtypes = [hwnd_t, wintypes.UINT]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [
        hwnd_t,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _WNDENUMPROC = ctypes.WINFUNCTYPE(bool_t, hwnd_t, wintypes.LPARAM)
    user32.EnumWindows.restype = bool_t
    user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [hwnd_t, ctypes.c_int]
    else:
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.GetWindowLongW.argtypes = [hwnd_t, ctypes.c_int]
    _USER32 = user32
    return user32


def _as_hwnd(hwnd: int):
    from ctypes import wintypes

    return wintypes.HWND(int(hwnd))


def _window_exstyle(user32, hwnd) -> int:
    import ctypes

    gwl_exstyle = -20
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return int(user32.GetWindowLongPtrW(hwnd, gwl_exstyle) or 0)
    return int(user32.GetWindowLongW(hwnd, gwl_exstyle) or 0)


def _win32_force_hwnd_foreground(hwnd: int) -> None:
    """Put an existing Win32 window in the foreground (no hide/show cycle).

    Do not use ``AttachThreadInput``: joining NeuroRehab's Qt GUI thread to
    another process's thread (the plugin GUI) is a known access-violation
    crash on Windows.
    """
    if not hwnd or sys.platform != "win32":
        return
    try:
        from ctypes import wintypes

        user32 = _user32()
        handle = _as_hwnd(hwnd)
        if not user32.IsWindow(handle):
            return
        if _hwnd_as_int(user32.GetForegroundWindow()) == int(hwnd):
            return
        sw_restore = 9
        hwnd_topmost = wintypes.HWND(-1)
        hwnd_notopmost = wintypes.HWND(-2)
        swp_nomove = 0x0002
        swp_nosize = 0x0001
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, sw_restore)
        user32.BringWindowToTop(handle)
        user32.SetForegroundWindow(handle)
        if _hwnd_as_int(user32.GetForegroundWindow()) != int(hwnd):
            flags = swp_nomove | swp_nosize
            user32.SetWindowPos(handle, hwnd_topmost, 0, 0, 0, 0, flags)
            user32.SetWindowPos(handle, hwnd_notopmost, 0, 0, 0, 0, flags)
            user32.SetForegroundWindow(handle)
    except Exception:
        pass


def foreground_hwnd(hwnd: int | None) -> bool:
    """Bring an existing window handle to the front. True if a handle was given."""
    if not hwnd:
        return False
    _win32_force_hwnd_foreground(int(hwnd))
    return True


def _win32_set_foreground(window: Any) -> None:
    """Force a Qt widget to the foreground on Windows."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
    except Exception:
        return
    _win32_force_hwnd_foreground(hwnd)


def _win32_toplevel_hwnds_for_pid(pid: int) -> list[int]:
    """Visible top-level windows owned by ``pid`` (not tooltips/tool windows)."""
    if sys.platform != "win32" or not pid:
        return []
    hwnds: list[int] = []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = _user32()
        if _WNDENUMPROC is None:
            return []
        gw_owner = 4
        ws_ex_toolwindow = 0x00000080
        ws_ex_noactivate = 0x08000000

        def _enum(hwnd, _lparam) -> bool:
            try:
                proc_id = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
                if int(proc_id.value) != int(pid):
                    return True
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindow(hwnd, gw_owner):
                    return True
                exstyle = _window_exstyle(user32, hwnd)
                if exstyle & (ws_ex_toolwindow | ws_ex_noactivate):
                    return True
                value = _hwnd_as_int(hwnd)
                if value:
                    hwnds.append(value)
            except Exception:
                pass
            return True

        callback = _WNDENUMPROC(_enum)
        user32.EnumWindows(callback, 0)
    except Exception:
        return []
    return hwnds


def foreground_process_windows(pid: int | None) -> bool:
    """Bring a launched process's main window to the front. True if one was found."""
    if pid is None:
        return False
    hwnds = _win32_toplevel_hwnds_for_pid(int(pid))
    if not hwnds:
        return False
    _win32_force_hwnd_foreground(hwnds[-1])
    return True


def schedule_process_foreground(pid: int | None) -> None:
    """Raise ``pid``'s window once it exists (GUI may appear after imports)."""
    if pid is None or sys.platform != "win32":
        return
    state = {"done": False}

    def _try() -> None:
        if state["done"]:
            return
        try:
            if foreground_process_windows(pid):
                state["done"] = True
        except Exception:
            return

    _try()
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return
        for delay_ms in (100, 300, 700, 1500):
            QTimer.singleShot(delay_ms, _try)
    except ImportError:
        return


def present_worker_window(window: Any, *, activate: bool = True) -> int | None:
    """Show a worker window, optionally bringing it to the foreground.

    ``show()`` only happens if the window is hidden (avoids a hide/show blink).

    Returns:
        The native window handle if available, otherwise ``None``.
    """
    if not _worker_window_is_valid(window):
        return None
    if not window.isVisible():
        window.show()
    if activate:
        window.raise_()
        window.activateWindow()
        _win32_set_foreground(window)
    try:
        return int(window.winId())
    except Exception:
        return None


def present_worker_windows(windows: list[Any]) -> list[int]:
    """Show the given worker windows; only the last one is activated.

    Older plugin windows must not be raised just because another button
    was clicked. When several windows are created by the same click,
    only the last one takes the foreground so they do not cascade.

    Returns:
        Native handles of the windows that were shown, last one last.
    """
    hwnds: list[int] = []
    valid = [window for window in list(windows) if _worker_window_is_valid(window)]
    last_index = len(valid) - 1
    for index, window in enumerate(valid):
        hwnd = present_worker_window(window, activate=index == last_index)
        if hwnd:
            hwnds.append(hwnd)
    return hwnds


def normalize_storage_key(logical_key: str) -> str:
    """Normalize a logical storage key the same way downloads address it."""
    return str(logical_key or "").replace("\\", "/").strip("/")


def _plugin_file_cache_dir(logical_key: str) -> Path:
    digest = hashlib.sha256(normalize_storage_key(logical_key).encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / _CACHE_DIRNAME / digest


def safe_download_name(suggested_name: str) -> str:
    """Return a single path segment safe to use as a local file name."""
    name = os.path.basename(str(suggested_name or "").replace("\\", "/")).strip()
    name = _UNSAFE_NAME.sub("_", name).strip(". ")
    if name.endswith(".nr-partial"):
        name = name[: -len(".nr-partial")].strip(". ")
    return name or "file"


def allocate_plugin_download(logical_key: str, suggested_name: str) -> str:
    """Create a new empty file for one streamed download of ``logical_key``.

    Each call gets its own path. A previous download of the same storage key
    is not reused, and a copy the OS already has open is not overwritten.
    """
    directory = _plugin_file_cache_dir(logical_key)
    directory.mkdir(parents=True, exist_ok=True)
    name = safe_download_name(suggested_name)
    stem, suffix = os.path.splitext(name)
    handle, path = tempfile.mkstemp(
        prefix=f"{stem or 'file'}_",
        suffix=suffix,
        dir=directory,
    )
    os.close(handle)
    return path


def file_display_name(file_row: dict[str, Any]) -> str:
    """Compute a human-friendly display name for a file metadata row.

    Prefers ``original_name``; falls back to the basename of ``file_path``
    (normalizing backslashes), and finally to the literal string ``"file"``.

    Args:
        file_row: File metadata dict as returned by the plugin API.

    Returns:
        A non-empty display name for the file.
    """
    original = str(file_row.get("original_name") or "").strip()
    if original:
        return original
    logical = str(file_row.get("file_path") or "").replace("\\", "/")
    return os.path.basename(logical) or "file"


def open_local_path(path: str) -> None:
    """Open a local file path with the operating system's default application.

    Dispatches to ``os.startfile`` on Windows, ``open`` on macOS, and
    ``xdg-open`` on other (Linux/Unix) platforms, then pumps pending GUI
    events.

    Args:
        path: Local filesystem path to open.
    """
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
    pump_gui_events()
