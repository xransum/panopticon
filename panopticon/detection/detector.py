"""
detector.py - YOLOv8 inference wrapper.

Loads an Ultralytics YOLO model once at startup, runs it on each BGR
numpy frame, and returns both an annotated frame and structured results.

GPU selection:
  - CUDA (NVIDIA) is preferred.
  - Falls back to CPU if CUDA is unavailable or torch is not installed
    with CUDA support.

Model size:
  Default is yolov8n.pt (nano - fastest).  The caller can pass any
  Ultralytics-compatible model path or name (e.g. yolov8s.pt, yolov8m.pt,
  a custom .pt file, or a .onnx path).
"""

from __future__ import annotations

import dataclasses
import logging

import numpy as np

log = logging.getLogger(__name__)


@dataclasses.dataclass
class DetectionResult:
    """A single object detection from one frame."""

    label: str  # class name, e.g. "person"
    confidence: float  # 0.0 – 1.0
    # Bounding box in pixel coordinates (x1, y1, x2, y2)
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def __str__(self) -> str:
        return f"{self.label} ({self.confidence:.0%})"


class Detector:
    """
    Wraps an Ultralytics YOLO model for single-frame inference.

    Parameters
    ----------
    model_name : str
        Ultralytics model identifier or path. Defaults to "yolov8n.pt".
    confidence_threshold : float
        Minimum confidence to include a detection. Default 0.4.
    classes : list[int] | None
        COCO class IDs to filter to.  None = all classes.
        Use [0] to detect only people.
    device : str | None
        Torch device string ("cuda", "cuda:0", "cpu", etc.).
        None = auto-select (CUDA if available, else CPU).
    """

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        confidence_threshold: float = 0.4,
        classes: list[int] | None = None,
        device: str | None = None,
    ):
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.classes = classes
        self.device = device or self._auto_device()
        self._model = None  # lazy-loaded on first call

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self):
        """
        Explicitly load the model into GPU/CPU memory.
        Called once at startup so the first frame isn't slow.
        """
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "ultralytics is required. Install with: pip install ultralytics"
            ) from exc
        self._model = YOLO(self.model_name)
        log.info("Loaded model '%s' on device '%s'", self.model_name, self.device)
        # Warm up: run a blank frame so CUDA kernels are compiled
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        self._model.predict(
            dummy,
            device=self.device,
            verbose=False,
            conf=self.confidence_threshold,
        )

    def detect(self, frame: np.ndarray) -> tuple[np.ndarray, list[DetectionResult]]:
        """
        Run detection on a BGR numpy frame.

        Returns
        -------
        annotated_frame : np.ndarray
            BGR frame with bounding boxes and labels drawn by Ultralytics.
        detections : list[DetectionResult]
            Structured detection results.
        """
        if self._model is None:
            self.load()

        results = self._model.predict(
            frame,
            device=self.device,
            conf=self.confidence_threshold,
            classes=self.classes,
            verbose=False,
        )

        result = results[0]

        # Annotated frame (Ultralytics draws boxes + labels automatically)
        annotated: np.ndarray = result.plot()  # returns BGR ndarray

        # Parse structured results
        detections: list[DetectionResult] = []
        if result.boxes is not None:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                label = result.names.get(cls_id, str(cls_id))
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(
                    DetectionResult(
                        label=label,
                        confidence=conf,
                        x1=int(x1),
                        y1=int(y1),
                        x2=int(x2),
                        y2=int(y2),
                    )
                )

        return annotated, detections

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def device_label(self) -> str:
        """Human-readable device string for the status bar."""
        if self.device.startswith("cuda"):
            try:
                import torch

                name = torch.cuda.get_device_name(0)
                return f"GPU: {name}"
            except Exception:
                return "GPU: CUDA"
        return "CPU"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _auto_device() -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"
