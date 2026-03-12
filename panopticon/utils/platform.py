"""
platform.py - OS-specific window enumeration helpers.

Provides a unified WindowInfo dataclass and a list_windows() function
that works across Linux (X11 and KDE Wayland), Windows, and macOS.

Linux detection order:
  1. KDE Wayland  – KWin D-Bus scripting (no python-xlib needed)
  2. X11 / XWayland – python-xlib (classic EWMH window list)
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
    # Platform-specific handle: HWND (int) on Windows, XID (int) on Linux X11,
    # CGWindowID (int) on macOS, or KWin UUID string on KDE Wayland.
    handle: int | str | None = None

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
# Linux – backend detection
# ---------------------------------------------------------------------------


def _is_kde_wayland() -> bool:
    """True when running inside a KDE Plasma Wayland session."""
    import os

    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        and os.environ.get("XDG_CURRENT_DESKTOP", "").upper() == "KDE"
    )


def _list_windows_linux() -> list[WindowInfo]:
    if _is_kde_wayland():
        try:
            return _list_windows_kwin()
        except Exception:
            pass  # fall through to X11
    return _list_windows_x11()


def _get_geometry_linux(window: WindowInfo) -> dict | None:
    # KWin windows store their UUID as a string handle
    if isinstance(window.handle, str):
        return _get_geometry_kwin(window)
    return _get_geometry_x11(window)


# ---------------------------------------------------------------------------
# Linux – KDE Wayland via KWin D-Bus
# ---------------------------------------------------------------------------

# KWin JS snippet that prints one pipe-delimited line per non-taskbar-skipped window:
#   caption|pid|x|y|width|height|internalId
_KWIN_ENUM_SCRIPT = """\
var clients = workspace.clientList();
for (var i = 0; i < clients.length; i++) {
    var c = clients[i];
    if (!c.skipTaskbar && c.width > 1 && c.height > 1 && c.caption) {
        print(c.caption + "|" + c.pid + "|" + c.x + "|" + c.y + "|" + c.width + "|" + c.height + "|" + c.internalId);
    }
}
"""


def _kwin_run_script(js: str) -> list[str]:
    """
    Load a KWin JS snippet, run it, harvest its print() output from the
    systemd journal, then unload the script.  Returns a list of output lines.
    """
    import os
    import subprocess
    import tempfile
    import time

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(js)
        script_path = fh.name

    try:
        # Record timestamp before running so we only read fresh journal lines
        before = time.time()

        r = subprocess.run(
            [
                "qdbus",
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.loadScript",
                script_path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        script_id = r.stdout.strip()
        if not script_id.isdigit():
            return []

        subprocess.run(
            ["qdbus", "org.kde.KWin", f"/{script_id}", "org.kde.kwin.Script.run"],
            capture_output=True,
            timeout=5,
        )
        time.sleep(0.15)  # give the script a moment to finish and journal to flush

        # Collect output lines written by print() inside the script
        journal = subprocess.run(
            [
                "journalctl",
                "--user",
                "-u",
                "plasma-kwin_wayland",
                "--since",
                f"@{before:.6f}",
                "--no-pager",
                "-o",
                "cat",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        # Unload the script to avoid accumulation
        subprocess.run(
            ["qdbus", "org.kde.KWin", f"/{script_id}", "org.kde.kwin.Script.stop"],
            capture_output=True,
            timeout=3,
        )

        lines = []
        for line in journal.stdout.splitlines():
            # journal lines from KWin scripts are prefixed with "js: "
            if line.startswith("js: "):
                lines.append(line[4:])
        return lines
    finally:
        os.unlink(script_path)


def _list_windows_kwin() -> list[WindowInfo]:
    lines = _kwin_run_script(_KWIN_ENUM_SCRIPT)
    windows: list[WindowInfo] = []
    for line in lines:
        parts = line.split("|")
        if len(parts) != 7:
            continue
        caption, pid_s, x_s, y_s, w_s, h_s, uuid = parts
        try:
            pid = int(pid_s)
            left = int(x_s)
            top = int(y_s)
            width = int(w_s)
            height = int(h_s)
        except ValueError:
            continue
        windows.append(
            WindowInfo(
                title=caption,
                pid=pid,
                application=_process_name(pid),
                left=left,
                top=top,
                width=width,
                height=height,
                handle=uuid,  # store UUID string as handle
            )
        )
    return windows


def _get_geometry_kwin(window: WindowInfo) -> dict | None:
    """Refresh geometry for a KWin window using its UUID via getWindowInfo."""
    import subprocess

    try:
        r = subprocess.run(
            ["qdbus", "org.kde.KWin", "/KWin", "org.kde.KWin.getWindowInfo", str(window.handle)],
            capture_output=True,
            text=True,
            timeout=3,
        )
        info: dict[str, str] = {}
        for line in r.stdout.splitlines():
            if ": " in line:
                k, _, v = line.partition(": ")
                info[k.strip()] = v.strip()
        x = int(info["x"])
        y = int(info["y"])
        w = int(info["width"])
        h = int(info["height"])
        if w > 0 and h > 0:
            return {"left": x, "top": y, "width": w, "height": h}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Linux – X11 / XWayland
# ---------------------------------------------------------------------------


def _list_windows_x11() -> list[WindowInfo]:
    try:
        from Xlib import X
        from Xlib import display as xdisplay
    except ImportError as exc:
        raise ImportError(
            "python-xlib is required on Linux (X11). Install with: pip install python-xlib"
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


def _get_geometry_x11(window: WindowInfo) -> dict | None:
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
