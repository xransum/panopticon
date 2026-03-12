# Panopticon

GPU-accelerated AI window observer. Select any window or process and Panopticon
will continuously capture it and run real-time object detection (people, things)
using YOLOv8 on your GPU.

---

## Features

- **Window picker** — searchable list of all open windows with application name, title, PID, and dimensions
- **Live preview** — annotated feed with bounding boxes drawn over each frame
- **Detection log** — timestamped log panel showing class, confidence, and bounding-box coordinates; capped at 500 lines to keep memory usage flat
- **Follows the window** — tracks position changes each frame; capture continues even if the window moves or is occluded
- **GPU inference** — runs YOLOv8n on CUDA by default; falls back to CPU automatically if CUDA is unavailable
- **Configurable interval** — default 100 ms (~10 FPS); adjustable via toolbar spinner (10 – 5000 ms)
- **Session log files** — each run writes a timestamped log to `etc/logs/<YYYYMMDD_HHMMSS>.log` for post-session debugging

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
├── etc/
│   └── logs/                      # Per-session log files (auto-created, gitignored)
└── panopticon/
    ├── app.py                     # QApplication bootstrap + dark theme
    ├── logging_setup.py           # Root logger configuration (file + console)
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

The default model is `yolov8n.pt` (YOLOv8 nano) — fastest inference, smallest
memory footprint. You can swap it for a larger model in `app.py`:

```python
detector = Detector(model_name="yolov8s.pt")   # small
detector = Detector(model_name="yolov8m.pt")   # medium
detector = Detector(model_name="/path/to/custom.pt")
```

Models are downloaded automatically by Ultralytics on first run.

---

## Platform Support

| Platform | Window enumeration | Capture method | Status |
|---|---|---|---|
| Linux (X11) | `python-xlib` | `mss` | Supported |
| Linux (KDE Wayland) | KWin D-Bus | `spectacle` full-screen crop | Supported |
| Windows | `pywin32` | `PrintWindow` + `mss` fallback | Supported |
| macOS | `pyobjc-framework-Quartz` | `mss` | Supported |

### Known limitations

- **Wayland (non-KDE):** GNOME, Sway, Hyprland, and other Wayland compositors are not supported. Window enumeration and screen capture on non-KDE Wayland requires compositor-specific portals that are not yet implemented.
- **Wayland (KDE):** Capture requires `spectacle` (ships with KDE Plasma) to be installed and available on `$PATH`. Each frame triggers a full-screen grab that is then cropped, which is slower than the X11/mss path.
- **Minimized windows (Windows):** `PrintWindow` is used to capture windows that are minimized or behind other windows. Some applications that render via DirectX/Vulkan may return a blank frame.
- **macOS:** Capture requires screen recording permission granted to the terminal or application in **System Settings → Privacy & Security → Screen Recording**.
- **GPU requirement:** CUDA inference requires an NVIDIA GPU with a compatible CUDA toolkit. AMD and Apple Silicon GPUs are not currently supported for GPU-accelerated inference; those platforms fall back to CPU automatically.
- **Model classes:** The default `yolov8n.pt` detects the 80 COCO object classes. It does not detect application-specific UI elements or custom objects without a fine-tuned model.
- **Occluded/off-screen windows:** If the target window is fully off-screen or its geometry cannot be resolved, capture silently produces no frames until the window is repositioned.

---

## License

MIT
