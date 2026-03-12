"""
platform.py - OS-specific window enumeration helpers.

Provides a unified WindowInfo dataclass and a list_windows() function
that works across Linux (X11), Windows, and macOS.
"""

from __future__ import annotations

import dataclasses
import sys


def _process_name(pid: int) -> str:
    """Return the executable name for *pid*, or '' on any failure."""
    if not pid:
        return ""
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        pass
    # Fallback: read /proc/<pid>/comm on Linux without psutil
    if sys.platform.startswith("linux"):
        try:
            with open(f"/proc/{pid}/comm") as fh:
                return fh.read().strip()
        except Exception:
            pass
    return ""


@dataclasses.dataclass
class WindowInfo:
    """Represents a single open window / process."""

    title: str
    pid: int
    # Application (process) name derived from the owning process
    application: str = ""
    # Geometry: left, top, width, height (may be None if unavailable)
    left: int | None = None
    top: int | None = None
    width: int | None = None
    height: int | None = None
    # Platform-specific handle (HWND on Windows, XID on Linux, CGWindowID on macOS)
    handle: int | None = None

    @property
    def is_valid_geometry(self) -> bool:
        return all(v is not None for v in (self.left, self.top, self.width, self.height))

    @property
    def geometry(self) -> dict | None:
        if not self.is_valid_geometry:
            return None
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    def __str__(self) -> str:
        return f"[{self.pid}] {self.title or '(untitled)'}"


# ---------------------------------------------------------------------------
# Platform dispatch
# ---------------------------------------------------------------------------


def list_windows() -> list[WindowInfo]:
    """Return a list of all visible windows on the current platform."""
    if sys.platform.startswith("linux"):
        return _list_windows_linux()
    elif sys.platform == "win32":
        return _list_windows_windows()
    elif sys.platform == "darwin":
        return _list_windows_macos()
    else:
        raise NotImplementedError(f"Unsupported platform: {sys.platform}")


def get_window_geometry(window: WindowInfo) -> dict | None:
    """
    Refresh and return the current geometry for a window.
    Returns None if the window no longer exists or geometry is unavailable.
    """
    if sys.platform.startswith("linux"):
        return _get_geometry_linux(window)
    elif sys.platform == "win32":
        return _get_geometry_windows(window)
    elif sys.platform == "darwin":
        return _get_geometry_macos(window)
    return None


# ---------------------------------------------------------------------------
# Linux (X11)
# ---------------------------------------------------------------------------


def _list_windows_linux() -> list[WindowInfo]:
    try:
        from Xlib import X
        from Xlib import display as xdisplay
    except ImportError as exc:
        raise ImportError(
            "python-xlib is required on Linux. Install with: pip install python-xlib"
        ) from exc

    d = xdisplay.Display()
    root = d.screen().root
    NET_CLIENT_LIST = d.intern_atom("_NET_CLIENT_LIST")
    NET_WM_NAME = d.intern_atom("_NET_WM_NAME")
    WM_NAME = d.intern_atom("WM_NAME")
    NET_WM_PID = d.intern_atom("_NET_WM_PID")

    client_list = root.get_full_property(NET_CLIENT_LIST, X.AnyPropertyType)
    if not client_list:
        return []

    windows: list[WindowInfo] = []
    for wid in client_list.value:
        try:
            win = d.create_resource_object("window", wid)

            # Title
            name_prop = win.get_full_property(NET_WM_NAME, 0)
            if name_prop and name_prop.value:
                title = name_prop.value.decode("utf-8", errors="replace")
            else:
                name_prop = win.get_full_property(WM_NAME, X.AnyPropertyType)
                if name_prop and name_prop.value:
                    val = name_prop.value
                    title = (
                        val.decode("latin-1", errors="replace")
                        if isinstance(val, bytes)
                        else str(val)
                    )
                else:
                    title = ""

            # PID
            pid_prop = win.get_full_property(NET_WM_PID, X.AnyPropertyType)
            pid = int(pid_prop.value[0]) if pid_prop and pid_prop.value else 0

            # Geometry
            geom = win.get_geometry()
            # Translate to root coordinates
            translated = win.translate_coords(root, 0, 0)
            left = translated.x
            top = translated.y
            width = geom.width
            height = geom.height

            if title and width > 1 and height > 1:
                windows.append(
                    WindowInfo(
                        title=title,
                        pid=pid,
                        application=_process_name(pid),
                        left=left,
                        top=top,
                        width=width,
                        height=height,
                        handle=wid,
                    )
                )
        except Exception:
            continue

    d.close()
    return windows


def _get_geometry_linux(window: WindowInfo) -> dict | None:
    if window.handle is None:
        return None
    try:
        from Xlib import display as xdisplay

        d = xdisplay.Display()
        root = d.screen().root
        win = d.create_resource_object("window", window.handle)
        geom = win.get_geometry()
        translated = win.translate_coords(root, 0, 0)
        d.close()
        return {
            "left": translated.x,
            "top": translated.y,
            "width": geom.width,
            "height": geom.height,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Windows (Win32)
# ---------------------------------------------------------------------------


def _list_windows_windows() -> list[WindowInfo]:
    try:
        import win32gui
        import win32process
    except ImportError as exc:
        raise ImportError(
            "pywin32 is required on Windows. Install with: pip install pywin32"
        ) from exc

    windows: list[WindowInfo] = []

    def _enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            if width > 0 and height > 0:
                windows.append(
                    WindowInfo(
                        title=title,
                        pid=pid,
                        application=_process_name(pid),
                        left=left,
                        top=top,
                        width=width,
                        height=height,
                        handle=hwnd,
                    )
                )
        except Exception:
            pass

    win32gui.EnumWindows(_enum_handler, None)
    return windows


def _get_geometry_windows(window: WindowInfo) -> dict | None:
    if window.handle is None:
        return None
    try:
        import win32gui

        rect = win32gui.GetWindowRect(window.handle)
        left, top, right, bottom = rect
        return {"left": left, "top": top, "width": right - left, "height": bottom - top}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# macOS (Quartz)
# ---------------------------------------------------------------------------


def _list_windows_macos() -> list[WindowInfo]:
    try:
        import Quartz
    except ImportError as exc:
        raise ImportError(
            "pyobjc-framework-Quartz is required on macOS. "
            "Install with: pip install pyobjc-framework-Quartz"
        ) from exc

    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )

    windows: list[WindowInfo] = []
    for w in window_list:
        app_name = w.get("kCGWindowOwnerName", "") or ""
        title = w.get("kCGWindowName", "") or app_name
        pid = w.get("kCGWindowOwnerPID", 0)
        wid = w.get("kCGWindowNumber", None)
        bounds = w.get("kCGWindowBounds")
        if bounds:
            left = int(bounds.get("X", 0))
            top = int(bounds.get("Y", 0))
            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
        else:
            left = top = width = height = 0

        if title and width > 0 and height > 0:
            windows.append(
                WindowInfo(
                    title=title,
                    pid=pid,
                    application=app_name,
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                    handle=wid,
                )
            )

    return windows


def _get_geometry_macos(window: WindowInfo) -> dict | None:
    if window.handle is None:
        return None
    try:
        import Quartz

        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionIncludingWindow,
            window.handle,
        )
        for w in window_list:
            bounds = w.get("kCGWindowBounds")
            if bounds:
                return {
                    "left": int(bounds.get("X", 0)),
                    "top": int(bounds.get("Y", 0)),
                    "width": int(bounds.get("Width", 0)),
                    "height": int(bounds.get("Height", 0)),
                }
    except Exception:
        pass
    return None
