# Panopticon

GPU-accelerated AI window observer. Select any window or process, and Panopticon
will continuously capture it and run real-time object detection (people, things)
using YOLOv8 on your GPU.

---

## Features

- **Window picker** - searchable list of all open windows by title and PID
- **Live preview** - annotated feed with bounding boxes drawn over each frame
- **Detection log** - timestamped log panel showing class, confidence, and box coords
- **Follows the window** - tracks position changes each frame; capture continues
  even if the window moves or is occluded
- **GPU inference** - runs YOLOv8n on CUDA by default; falls back to CPU if
  CUDA is unavailable
- **Configurable interval** - default 100 ms (~10 FPS); adjustable via spinner
- **Cross-platform** - Linux (X11), Windows, macOS

---

## Requirements

- Python 3.10+
- An NVIDIA GPU with CUDA support (recommended; CPU fallback is supported)
- [uv](https://docs.astral.sh/uv/) (recommended) **or** pip

---

## Installation

### With uv (recommended)

```bash
# 1. Clone
git clone https://github.com/xransum/panopticon.git
cd panopticon

# 2. Sync the environment (uv creates .venv automatically)
#    For NVIDIA CUDA 12.1 GPU:
uv sync --extra cuda121

#    CPU-only fallback:
uv sync --extra cpu

# 3. Run
uv run python main.py
# or use the installed script:
uv run panopticon
```

> **Note:** `torch` and `torchvision` are pulled from the PyTorch CUDA 12.1
> index automatically for Linux/Windows when using `--extra cuda121`.
> macOS always uses the default PyPI index (CPU only).

### With pip

```bash
# 1. Clone
git clone https://github.com/xransum/panopticon.git
cd panopticon

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install PyTorch with CUDA (example for CUDA 12.1)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 4. Install remaining dependencies
pip install -r requirements.txt
```

---

## Usage

```bash
python main.py
```

1. Click **Select Window** in the toolbar.
2. Find and double-click the window you want to monitor.
3. Click **Start** to begin capture and detection.
4. The live preview shows bounding boxes; the right panel logs each detection.
5. Click **Unfocus** to release the target window at any time.

---

## Project Structure

```
panopticon/
├── main.py                        # Entry point
├── pyproject.toml                 # Project metadata + uv/pip config
├── uv.lock                        # Locked dependency graph
├── requirements.txt               # pip-compatible requirements
└── panopticon/
    ├── app.py                     # QApplication bootstrap + dark theme
    ├── ui/
    │   ├── main_window.py         # Main window (preview + log)
    │   └── window_selector.py     # Window/process picker dialog
    ├── capture/
    │   ├── manager.py             # QThread capture loop
    │   └── screenshot.py          # Cross-platform screenshot
    ├── detection/
    │   └── detector.py            # YOLOv8 inference wrapper
    └── utils/
        └── platform.py            # OS-specific window enumeration
```

---

## Model

The default model is `yolov8n.pt` (YOLOv8 nano) - fastest inference, smallest
memory footprint. You can swap it for a larger model in `app.py`:

```python
detector = Detector(model_name="yolov8s.pt")   # small
detector = Detector(model_name="yolov8m.pt")   # medium
detector = Detector(model_name="/path/to/custom.pt")
```

Models are downloaded automatically by Ultralytics on first run.

---

## Platform Notes

| Platform | Window enumeration | Capture method |
|---|---|---|
| Linux (X11) | `python-xlib` | `mss` |
| Windows | `pywin32` | `PrintWindow` (captures minimized windows) + `mss` fallback |
| macOS | `pyobjc-framework-Quartz` | `mss` |

> **Wayland (Linux):** X11 window enumeration via `python-xlib` requires an
> XWayland session.  Native Wayland window listing is not currently supported.

---

## License

MIT
