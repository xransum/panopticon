"""
logging_setup.py - Application-wide logging configuration.

Call ``setup_logging()`` once, as early as possible in the entry point,
before any other module imports so every logger inherits the handlers.

Log files are written to ``<project_root>/etc/logs/<timestamp>.log``
where *project root* is the directory that contains ``main.py``, resolved
relative to this file so the location is stable regardless of the working
directory the user launches the app from.

Handlers
--------
- FileHandler  — DEBUG and above → etc/logs/<timestamp>.log
- StreamHandler — WARNING and above → stderr (avoids console spam)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

# Project root = panopticon/ package parent
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PROJECT_ROOT / "etc" / "logs"


def setup_logging() -> Path:
    """
    Configure the root logger with a timestamped file handler and a
    console (stderr) handler.

    Returns the path to the log file that was opened.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = _LOG_DIR / f"{timestamp}.log"

    fmt = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # File handler — full DEBUG log kept on disk
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — WARNING and above only to avoid spamming the terminal
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # Silence chatty third-party loggers that flood at DEBUG level
    for noisy in ("ultralytics", "torch", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).debug("Logging initialised — writing to %s", log_file)
    return log_file
