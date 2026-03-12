"""
manager.py - QThread-based capture + detection loop.

CaptureManager runs in a background QThread.  Each tick it:
  1. Grabs a screenshot of the target window via ScreenshotCapture.
  2. Passes the raw frame through the Detector.
  3. Emits `frame_ready` with the annotated BGR numpy array and
     a list of DetectionResult objects for the log panel.

Signals are the only communication path back to the main thread -
no direct UI calls are made here.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QMutex, QMutexLocker, QThread, pyqtSignal

from panopticon.capture.screenshot import ScreenshotCapture
from panopticon.detection.detector import Detector
from panopticon.utils.platform import WindowInfo

log = logging.getLogger(__name__)


class CaptureWorker(QThread):
    """
    Background thread that continuously captures and analyses frames.

    Signals:
        frame_ready(np.ndarray, list[DetectionResult])
            Emitted after each successful capture + inference pass.
            The ndarray is the annotated BGR frame; safe to convert to QImage
            on the receiving side.
        error(str)
            Emitted when a non-fatal error occurs (e.g. window disappeared).
        status(str)
            Emitted for informational status messages.
    """

    # Signals must be class-level attributes
    frame_ready = pyqtSignal(object, object)  # (np.ndarray, List[DetectionResult])
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(
        self,
        window: WindowInfo,
        detector: Detector,
        interval_ms: int = 100,
        parent=None,
    ):
        super().__init__(parent)
        self._window = window
        self._detector = detector
        self._interval_ms = interval_ms

        self._mutex = QMutex()
        self._running = False
        self._paused = False

        self._capture: ScreenshotCapture | None = None

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_interval(self, ms: int):
        with QMutexLocker(self._mutex):
            self._interval_ms = max(10, ms)

    def set_window(self, window: WindowInfo):
        with QMutexLocker(self._mutex):
            self._window = window
            if self._capture is not None:
                self._capture.update_window(window)

    def pause(self):
        with QMutexLocker(self._mutex):
            self._paused = True

    def resume(self):
        with QMutexLocker(self._mutex):
            self._paused = False

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self):
        with QMutexLocker(self._mutex):
            self._running = True
            window = self._window

        self._capture = ScreenshotCapture(window)
        self.status.emit(f"Capturing: {window}")
        log.info("Capture started for window: %s", window)

        consecutive_failures = 0
        MAX_FAILURES = 20  # ~2 s at 100 ms intervals before emitting error

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
                paused = self._paused
                interval = self._interval_ms

            if paused:
                time.sleep(0.1)
                continue

            t_start = time.monotonic()

            frame = self._capture.grab()

            if frame is None:
                consecutive_failures += 1
                if consecutive_failures >= MAX_FAILURES:
                    log.warning(
                        "Window lost — no frame received after %d attempts", consecutive_failures
                    )
                    self.error.emit("Window lost - no frame received.")
                    consecutive_failures = 0
                time.sleep(interval / 1000.0)
                continue

            consecutive_failures = 0

            # Run inference
            try:
                annotated, detections = self._detector.detect(frame)
            except Exception as exc:
                log.exception("Detection error: %s", exc)
                self.error.emit(f"Detection error: {exc}")
                annotated = frame
                detections = []

            self.frame_ready.emit(annotated, detections)

            # Throttle to maintain the requested interval
            elapsed_ms = (time.monotonic() - t_start) * 1000
            sleep_ms = interval - elapsed_ms
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

        if self._capture:
            self._capture.close()
        log.info("Capture stopped for window: %s", window)
        self.status.emit("Capture stopped.")


class CaptureManager:
    """
    High-level manager that owns the CaptureWorker thread.

    Handles starting, stopping, and swapping the target window.
    The caller connects to the worker's signals directly:

        manager.worker.frame_ready.connect(my_slot)
        manager.worker.error.connect(my_error_slot)
    """

    def __init__(self, detector: Detector, interval_ms: int = 100):
        self._detector = detector
        self._interval_ms = interval_ms
        self.worker: CaptureWorker | None = None

    @property
    def is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start(self, window: WindowInfo):
        """Start (or restart) capture on the given window."""
        self.stop()
        self.worker = CaptureWorker(window, self._detector, self._interval_ms)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)  # wait up to 3 s
        self.worker = None

    def set_window(self, window: WindowInfo):
        if self.worker:
            self.worker.set_window(window)

    def set_interval(self, ms: int):
        self._interval_ms = ms
        if self.worker:
            self.worker.set_interval(ms)

    def pause(self):
        if self.worker:
            self.worker.pause()

    def resume(self):
        if self.worker:
            self.worker.resume()
