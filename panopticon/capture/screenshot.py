"""
screenshot.py - Cross-platform window screenshot capture.

Uses mss for the pixel grab (fast, cross-platform) and platform-specific
APIs to locate the window rect each frame so it follows the window if it moves.

On Windows, falls back to PrintWindow (win32gui) for capturing windows that
are minimized or occluded by other windows.

On KDE Wayland, uses spectacle (ships with KDE Plasma) for a full-screen
grab then crops to the window region, since XGetImage is unavailable.
"""

from __future__ import annotations

import logging
import sys

import numpy as np

from panopticon.utils.platform import WindowInfo, get_window_geometry

log = logging.getLogger(__name__)


def _is_kde_wayland() -> bool:
    import os

    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        and os.environ.get("XDG_CURRENT_DESKTOP", "").upper() == "KDE"
    )


def _win32_printwindow_available() -> bool:
    """
    Check once at startup whether win32gui.PrintWindow exists.
    Some pywin32 builds omit it; calling it per-frame and swallowing
    AttributeError would spam the log on every capture tick.
    """
    try:
        import win32gui

        return hasattr(win32gui, "PrintWindow")
    except ImportError:
        return False


_WIN32_PRINTWINDOW_AVAILABLE = _win32_printwindow_available()
if sys.platform == "win32" and not _WIN32_PRINTWINDOW_AVAILABLE:
    log.warning("win32gui.PrintWindow not available — falling back to mss for all captures")


class ScreenshotCapture:
    """
    Captures screenshots of a target window.

    Usage:
        cap = ScreenshotCapture(window)
        frame = cap.grab()   # returns np.ndarray (H, W, 3) BGR or None
    """

    def __init__(self, window: WindowInfo):
        self.window = window
        self._last_geometry: dict | None = window.geometry
        self._kde_wayland = _is_kde_wayland()
        if not self._kde_wayland:
            self._init_mss()

    def _init_mss(self):
        import mss

        self._mss = mss.mss()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def grab(self) -> np.ndarray | None:
        """
        Capture the current frame of the tracked window.
        Returns a BGR numpy array (H, W, 3), or None on failure.
        """
        geom = self._refresh_geometry()
        if geom is None:
            return None

        if (
            sys.platform == "win32"
            and _WIN32_PRINTWINDOW_AVAILABLE
            and self.window.handle is not None
        ):
            frame = self._grab_win32_printwindow(geom)
            if frame is not None:
                return frame

        if self._kde_wayland:
            return self._grab_spectacle(geom)

        return self._grab_mss(geom)

    def update_window(self, window: WindowInfo):
        """Swap the target window (e.g. user re-selects)."""
        self.window = window
        self._last_geometry = window.geometry

    def close(self):
        import contextlib

        if not self._kde_wayland:
            with contextlib.suppress(Exception):
                self._mss.close()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _refresh_geometry(self) -> dict | None:
        """Get the latest window geometry, falling back to the last known."""
        geom = get_window_geometry(self.window)
        if geom and geom["width"] > 0 and geom["height"] > 0:
            self._last_geometry = geom
        return self._last_geometry

    # ------------------------------------------------------------------
    # KDE Wayland: spectacle fullscreen grab + crop
    # ------------------------------------------------------------------

    def _grab_spectacle(self, geom: dict) -> np.ndarray | None:
        """
        Capture the full screen via spectacle then crop to the window region.

        spectacle ships with KDE Plasma and is authorised by KWin to capture
        the compositor surface, which bypasses the XGetImage restriction.
        """
        import subprocess
        import tempfile

        import cv2

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                outfile = fh.name

            result = subprocess.run(
                ["spectacle", "-b", "-f", "-n", "-o", outfile],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                log.warning("spectacle exited with code %d", result.returncode)
                return None

            full = cv2.imread(outfile)
            if full is None:
                return None

            x = max(0, geom["left"])
            y = max(0, geom["top"])
            w = geom["width"]
            h = geom["height"]
            fh_img, fw_img = full.shape[:2]
            x2 = min(x + w, fw_img)
            y2 = min(y + h, fh_img)

            if x2 <= x or y2 <= y:
                return None

            return full[y:y2, x:x2]
        except Exception:
            log.debug("spectacle grab failed", exc_info=True)
            return None
        finally:
            import contextlib
            import os

            with contextlib.suppress(Exception):
                os.unlink(outfile)

    # ------------------------------------------------------------------
    # mss capture (Linux X11, macOS, Windows fallback)
    # ------------------------------------------------------------------

    def _grab_mss(self, geom: dict) -> np.ndarray | None:
        try:
            monitor = {
                "left": geom["left"],
                "top": geom["top"],
                "width": geom["width"],
                "height": geom["height"],
            }
            sct_img = self._mss.grab(monitor)
            # mss returns BGRA; drop alpha channel -> BGR
            frame = np.frombuffer(sct_img.raw, dtype=np.uint8)
            frame = frame.reshape((sct_img.height, sct_img.width, 4))
            return frame[:, :, :3]  # BGR
        except Exception:
            log.debug("mss grab failed", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Windows: PrintWindow (captures minimized / occluded windows)
    # ------------------------------------------------------------------

    def _grab_win32_printwindow(self, geom: dict) -> np.ndarray | None:
        """
        Use Win32 PrintWindow to render the window into a DC.
        Works even when the window is minimized or behind other windows.
        """
        try:
            import win32gui
            import win32ui

            hwnd = self.window.handle
            width = geom["width"]
            height = geom["height"]

            if width <= 0 or height <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # PW_RENDERFULLCONTENT = 0x00000002 (captures DWM-composited content)
            result = win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

            if result:
                bmp_info = bitmap.GetInfo()
                bmp_str = bitmap.GetBitmapBits(True)
                img = np.frombuffer(bmp_str, dtype=np.uint8)
                img = img.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
                frame = img[:, :, :3]  # drop alpha, keep BGR
            else:
                frame = None

            # Cleanup
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            win32ui.DeleteObject(bitmap.GetHandle())

            return frame
        except Exception:
            log.debug("win32 PrintWindow grab failed", exc_info=True)
            return None


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------


def capture_window(window: WindowInfo) -> np.ndarray | None:
    """One-shot capture of a window. Creates and destroys a ScreenshotCapture."""
    cap = ScreenshotCapture(window)
    try:
        return cap.grab()
    finally:
        cap.close()
