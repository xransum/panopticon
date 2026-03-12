"""
app.py - PyQt6 application bootstrap.

Handles:
  - QApplication creation and dark-theme stylesheet
  - Detector initialisation (with a splash/loading indicator)
  - Main window creation and show
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen

from panopticon.detection.detector import Detector
from panopticon.logging_setup import setup_logging
from panopticon.ui.main_window import MainWindow

log = logging.getLogger(__name__)

_DARK_STYLESHEET = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
}
QToolBar {
    background-color: #252526;
    border-bottom: 1px solid #3c3c3c;
    spacing: 4px;
    padding: 2px 4px;
}
QPushButton {
    background-color: #3a3d41;
    color: #d4d4d4;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 3px 10px;
}
QPushButton:hover {
    background-color: #4a4d51;
}
QPushButton:pressed {
    background-color: #2a2d31;
}
QPushButton:disabled {
    color: #666;
    background-color: #2a2a2a;
    border-color: #3a3a3a;
}
QSpinBox {
    background-color: #3a3d41;
    color: #d4d4d4;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 2px 4px;
}
QLineEdit {
    background-color: #3a3d41;
    color: #d4d4d4;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 3px 6px;
}
QTreeView {
    background-color: #252526;
    alternate-background-color: #2d2d2d;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
}
QTreeView::item:selected {
    background-color: #094771;
}
QHeaderView::section {
    background-color: #333;
    color: #ccc;
    border: none;
    border-right: 1px solid #444;
    padding: 3px 6px;
}
QStatusBar {
    background-color: #007acc;
    color: #fff;
}
QStatusBar QLabel {
    color: #fff;
}
QScrollBar:vertical {
    background: #1e1e1e;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #555;
    border-radius: 4px;
}
QSplitter::handle {
    background: #3c3c3c;
}
QDialogButtonBox QPushButton {
    min-width: 72px;
}
"""


def _make_splash() -> QSplashScreen:
    """Create a minimal text splash screen."""
    pm = QPixmap(400, 120)
    pm.fill(QColor("#1e1e1e"))
    painter = QPainter(pm)
    painter.setPen(QColor("#d4d4d4"))
    font = QFont("Sans Serif", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "Panopticon")
    painter.setPen(QColor("#888"))
    small = QFont("Sans Serif", 10)
    painter.setFont(small)
    painter.drawText(
        pm.rect().adjusted(0, 50, 0, 0),
        Qt.AlignmentFlag.AlignCenter,
        "Loading AI model…",
    )
    painter.end()
    return QSplashScreen(pm, Qt.WindowType.WindowStaysOnTopHint)


def run(argv=None):
    """Create the QApplication and run the event loop."""
    if argv is None:
        argv = sys.argv

    log_file = setup_logging()
    log.info("Panopticon starting — log file: %s", log_file)

    app = QApplication(argv)
    app.setApplicationName("Panopticon")
    app.setOrganizationName("panopticon")
    app.setStyleSheet(_DARK_STYLESHEET)

    # Show splash while the model loads
    splash = _make_splash()
    splash.show()
    app.processEvents()

    detector = Detector(
        model_name="yolov8n.pt",
        confidence_threshold=0.4,
    )

    try:
        detector.load()
        log.info("Model loaded successfully on %s", detector.device_label)
    except Exception as exc:
        log.exception("Failed to load model: %s", exc)
        splash.hide()
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.critical(
            None,
            "Model Load Error",
            f"Failed to load YOLOv8 model:\n\n{exc}\n\n"
            "Make sure `ultralytics` is installed:\n  pip install ultralytics",
        )
        return 1

    window = MainWindow(detector)
    window.show()
    splash.finish(window)
    log.info("Main window shown")

    return app.exec()
