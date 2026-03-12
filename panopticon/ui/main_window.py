"""
main_window.py - Main application window.

Layout
------
┌─────────────────────────────────────────────────────┐
│  Toolbar: [Select Window] [Unfocus] [▶/⏸] interval │
├───────────────────────────┬─────────────────────────┤
│                           │  Detection Log          │
│   Live Preview            │  ─────────────────────  │
│   (annotated frame)       │  [timestamp] label conf │
│                           │  ...                    │
├───────────────────────────┴─────────────────────────┤
│  Status bar: window name | device | FPS             │
└─────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime

import numpy as np
from PyQt6.QtCore import QSize, Qt, pyqtSlot
from PyQt6.QtGui import QFont, QImage, QPainter
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from panopticon.capture.manager import CaptureManager
from panopticon.detection.detector import DetectionResult, Detector
from panopticon.ui.window_selector import WindowSelectorDialog
from panopticon.utils.platform import WindowInfo


class PreviewWidget(QWidget):
    """
    Live-frame preview widget.

    Accepts a QImage via set_frame() and draws it scaled to fit via
    paintEvent/QPainter.drawImage().  This avoids creating a QPixmap
    (and therefore a Win32 HBITMAP GDI object) on every frame, which
    was the cause of GDI handle exhaustion after extended runtime.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #1a1a1a; border: 1px solid #333;")
        self.setMinimumSize(320, 240)
        self._image: QImage | None = None

    def set_frame(self, image: QImage):
        self._image = image
        self.update()  # schedule a repaint; does not block

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        if self._image is not None:
            # drawImage scales the source to fit the destination rect while
            # letting Qt handle aspect-ratio alignment internally via the
            # painter transform.  No QPixmap / HBITMAP is created.
            scaled = self._image.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        painter.end()


class DetectionLogWidget(QPlainTextEdit):
    """Read-only auto-scrolling log of detection events."""

    MAX_LINES = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Qt trims oldest blocks automatically when the document exceeds this
        # limit, with no manual cursor loop required.
        self.setMaximumBlockCount(self.MAX_LINES)
        font = QFont("Monospace", 9)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(font)
        self.setStyleSheet("background: #0d0d0d; color: #e0e0e0; border: 1px solid #333;")

    def append_detections(self, detections: list[DetectionResult]):
        if not detections:
            return
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        # Build all lines for this frame and append in one call to avoid
        # triggering a layout/repaint for every individual detection.
        lines = "\n".join(
            f"[{ts}] {d.label:<15} {d.confidence:5.1%}  box=({d.x1},{d.y1},{d.x2},{d.y2})"
            for d in detections
        )
        self.appendPlainText(lines)
        # appendPlainText already scrolls to the bottom; the scrollbar update
        # below keeps the view pinned when the user has not manually scrolled.
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def clear_log(self):
        self.clear()


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, detector: Detector, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Panopticon")
        self.setMinimumSize(960, 600)

        self._detector = detector
        self._manager = CaptureManager(detector, interval_ms=100)
        self._current_window: WindowInfo | None = None

        # FPS tracking — keep at most 1 s worth of timestamps.
        # deque with maxlen avoids rebuilding the list on every frame.
        self._frame_times: deque[float] = deque()

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: live preview
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._preview = PreviewWidget()
        left_layout.addWidget(self._preview)
        self._no_target_label = QLabel('No window selected.\nUse "Select Window" to begin.')
        self._no_target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_target_label.setStyleSheet("color: #888; font-size: 14px;")
        self._no_target_label.setVisible(True)
        self._preview.setVisible(False)
        left_layout.addWidget(self._no_target_label)
        splitter.addWidget(left)

        # Right: detection log
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)

        log_header = QLabel("Detection Log")
        log_header.setStyleSheet("font-weight: bold; padding: 2px 4px;")
        right_layout.addWidget(log_header)

        self._log = DetectionLogWidget()
        right_layout.addWidget(self._log)

        clear_btn = QPushButton("Clear Log")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._log.clear_log)
        right_layout.addWidget(clear_btn)

        splitter.addWidget(right)
        splitter.setSizes([640, 320])
        layout.addWidget(splitter)

    def _build_toolbar(self):
        tb = QToolBar("Controls")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        self._select_btn = QPushButton("Select Window")
        self._select_btn.setFixedHeight(28)
        self._select_btn.clicked.connect(self._on_select_window)
        tb.addWidget(self._select_btn)

        self._unfocus_btn = QPushButton("Unfocus")
        self._unfocus_btn.setFixedHeight(28)
        self._unfocus_btn.setEnabled(False)
        self._unfocus_btn.clicked.connect(self._on_unfocus)
        tb.addWidget(self._unfocus_btn)

        tb.addSeparator()

        self._toggle_btn = QPushButton("Start")
        self._toggle_btn.setFixedHeight(28)
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.clicked.connect(self._on_toggle_capture)
        tb.addWidget(self._toggle_btn)

        tb.addSeparator()

        interval_label = QLabel(" Interval (ms): ")
        tb.addWidget(interval_label)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(10, 5000)
        self._interval_spin.setValue(100)
        self._interval_spin.setSingleStep(50)
        self._interval_spin.setFixedWidth(80)
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        tb.addWidget(self._interval_spin)

    def _build_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._status_window = QLabel("No target")
        self._status_device = QLabel(self._detector.device_label)
        self._status_fps = QLabel("-- FPS")

        for lbl in (self._status_window, self._status_device, self._status_fps):
            lbl.setStyleSheet("padding: 0 8px;")
            self._statusbar.addPermanentWidget(lbl)

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _on_select_window(self):
        dlg = WindowSelectorDialog(self)
        if dlg.exec() == WindowSelectorDialog.DialogCode.Accepted and dlg.selected_window:
            win = dlg.selected_window
            self._current_window = win
            self._status_window.setText(str(win))
            self._toggle_btn.setEnabled(True)
            self._unfocus_btn.setEnabled(True)
            self._no_target_label.setVisible(False)
            self._preview.setVisible(True)

            # If already running, swap the target
            if self._manager.is_running:
                self._manager.set_window(win)
            else:
                self._toggle_btn.setText("Start")

    def _on_unfocus(self):
        self._manager.stop()
        self._current_window = None
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.setText("Start")
        self._unfocus_btn.setEnabled(False)
        self._preview.setVisible(False)
        self._no_target_label.setVisible(True)
        self._status_window.setText("No target")
        self._frame_times.clear()
        self._status_fps.setText("-- FPS")

    def _on_toggle_capture(self):
        if self._manager.is_running:
            self._manager.stop()
            self._toggle_btn.setText("Start")
        else:
            if self._current_window is None:
                return
            self._start_capture(self._current_window)
            self._toggle_btn.setText("Stop")

    def _on_interval_changed(self, value: int):
        self._manager.set_interval(value)

    # ------------------------------------------------------------------
    # Capture helpers
    # ------------------------------------------------------------------

    def _start_capture(self, window: WindowInfo):
        self._manager.start(window)
        worker = self._manager.worker
        worker.frame_ready.connect(self._on_frame_ready)
        worker.error.connect(self._on_capture_error)
        worker.status.connect(self._on_capture_status)

    @pyqtSlot(object, object)
    def _on_frame_ready(self, frame: np.ndarray, detections: list[DetectionResult]):
        # Track FPS — drop timestamps older than 1 second from the left.
        now = time.monotonic()
        self._frame_times.append(now)
        cutoff = now - 1.0
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.popleft()
        fps = len(self._frame_times)
        self._status_fps.setText(f"{fps} FPS")

        # Convert BGR ndarray -> QImage.
        # .copy() detaches the QImage from the numpy buffer so Qt owns the
        # memory and the array can be safely GC'd after this slot returns.
        # No QPixmap is created here — PreviewWidget draws the QImage directly
        # via QPainter.drawImage(), which avoids allocating a Win32 HBITMAP
        # (GDI object) on every frame and prevents GDI handle exhaustion.
        h, w, ch = frame.shape
        rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR -> RGB, ensure C-contiguous
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self._preview.set_frame(qimg)

        # Append to log
        self._log.append_detections(detections)

    @pyqtSlot(str)
    def _on_capture_error(self, msg: str):
        self._statusbar.showMessage(f"Error: {msg}", 4000)

    @pyqtSlot(str)
    def _on_capture_status(self, msg: str):
        self._statusbar.showMessage(msg, 2000)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._manager.stop()
        super().closeEvent(event)
