# Contributing to glancefocus

Thanks for helping! The most valuable contributions right now are:

1. **Reports from real setups.** Include the output of `glancefocus doctor` and `glancefocus windows`,
   plus the error numbers that `glancefocus calibrate` prints.
2. **Testing the experimental backends** (Sway/i3, X11, Windows, macOS).
3. **New window-manager backends**, especially GNOME Shell and KDE KWin on Wayland.

## Development setup

```bash
git clone https://github.com/Levixon10/glancefocus && cd glancefocus
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,linux]"
pytest && ruff check src tests
```

The unit tests need only numpy: no camera, display or MediaPipe.

## Project layout

```
src/glancefocus/
  gaze/features.py   MediaPipe result → feature vector (numpy only)
  gaze/webcam.py     camera + Face Landmarker background thread
  mapping.py         ridge regression feature vector → desktop point
  calibration.py     on-screen calibration and calibration file
  policy.py          when to switch focus (pure logic, heavily tested)
  app.py             main loop
  platforms/         one module per window manager / OS
```

## Adding a backend

Subclass `glancefocus.platforms.base.Platform` and implement:

| Method | Must return / do |
|---|---|
| `monitors()` | Every active monitor as `Monitor(name, Rect)` in global desktop coordinates |
| `windows()` | Only windows **visible right now** (current workspaces, not minimised), each with `rect`, `monitor` (a monitor name), `focused`, and `z` (0 = topmost or most recently used) |
| `focus_window(w)` | Focus it, or raise `PlatformError` |

Optional: `cursor_pos()` (enables the mouse lock), `focus_monitor()`, and the two
`overlay_*` hooks if OpenCV's generic fullscreen doesn't land on the right monitor under your
window manager.

**Important:** window rects and monitor rects must use the *same* coordinate space. Calibration
maps gaze directly into it.

Then register the backend in `platforms/__init__.py` (`detect_name()` and `get_platform()`), and
add a test that feeds recorded IPC output through a fake runner, like `tests/test_hyprland.py` does.

## Style

- `ruff check` must pass. Line length is 110.
- Keep `policy.py`, `mapping.py` and `gaze/features.py` free of camera and GUI imports, so they
  stay testable everywhere.
