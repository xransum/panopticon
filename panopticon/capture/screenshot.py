"""
screenshot.py - Cross-platform window screenshot capture.

Uses mss for the pixel grab (fast, cross-platform) and platform-specific
APIs to locate the window rect each frame so it follows the window if it moves.

On Windows, falls back to PrintWindow (win32gui) for capturing windows that
are minimized or occluded by other windows.
"""

from __future__ import annotations

import sys
import numpy as np
from typing import Optional, Tuple

from panopticon.utils.platform import WindowInfo, get_window_geometry


class ScreenshotCapture:
    """
    Captures screenshots of a target window.

    Usage:
        cap = ScreenshotCapture(window)
        frame = cap.grab()   # returns np.ndarray (H, W, 3) BGR or None
    """

    def __init__(self, window: WindowInfo):
        self.window = window
        self._last_geometry: Optional[dict] = window.geometry
        self._init_backend()

    def _init_backend(self):
        import mss

        self._mss = mss.mss()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def grab(self) -> Optional[np.ndarray]:
        """
        Capture the current frame of the tracked window.
        Returns a BGR numpy array (H, W, 3), or None on failure.
        """
        geom = self._refresh_geometry()
        if geom is None:
            return None

        if sys.platform == "win32" and self.window.handle is not None:
            frame = self._grab_win32_printwindow(geom)
            if frame is not None:
                return frame

        return self._grab_mss(geom)

    def update_window(self, window: WindowInfo):
        """Swap the target window (e.g. user re-selects)."""
        self.window = window
        self._last_geometry = window.geometry

    def close(self):
        try:
            self._mss.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _refresh_geometry(self) -> Optional[dict]:
        """Get the latest window geometry, falling back to the last known."""
        geom = get_window_geometry(self.window)
        if geom and geom["width"] > 0 and geom["height"] > 0:
            self._last_geometry = geom
        return self._last_geometry

    # ------------------------------------------------------------------
    # mss capture (universal fallback)
    # ------------------------------------------------------------------

    def _grab_mss(self, geom: dict) -> Optional[np.ndarray]:
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
            return None

    # ------------------------------------------------------------------
    # Windows: PrintWindow (captures minimized / occluded windows)
    # ------------------------------------------------------------------

    def _grab_win32_printwindow(self, geom: dict) -> Optional[np.ndarray]:
        """
        Use Win32 PrintWindow to render the window into a DC.
        Works even when the window is minimized or behind other windows.
        """
        try:
            import win32gui
            import win32ui
            import win32con

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
            return None


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------


def capture_window(window: WindowInfo) -> Optional[np.ndarray]:
    """One-shot capture of a window. Creates and destroys a ScreenshotCapture."""
    cap = ScreenshotCapture(window)
    try:
        return cap.grab()
    finally:
        cap.close()
