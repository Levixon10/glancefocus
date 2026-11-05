# glancefocus

**Focus follows your eyes.** Look at a window, start typing, and it's already focused.

[![CI](https://github.com/Levixon10/glancefocus/actions/workflows/ci.yml/badge.svg)](https://github.com/Levixon10/glancefocus/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

With a laptop plus an external monitor, and several windows open on each, it's easy to look at
one window and type into another because focus was still somewhere else. glancefocus watches
where you're looking through an ordinary webcam and moves keyboard focus to that window, after you
rest your eyes on it for a moment and only when you aren't typing.

- **Any setup.** Any number of monitors, any sizes, any arrangement, any camera position.
  Calibration learns your layout.
- **Per window, not just per monitor.** It picks the window you're looking at among tiled or
  floating windows. When windows are too small for the measured accuracy, it falls back to
  focusing that monitor.
- **Doesn't fight you.** Dwell time, edge margins, a typing lock, a mouse lock and a cooldown
  mean it only moves focus when you clearly mean it.
- **Private.** Everything runs locally. No frames are saved or sent anywhere.

> **Status: alpha.** It's used daily on Hyprland. The Sway/i3, X11, Windows and macOS backends
> are implemented but still need testers. Please [open an issue](https://github.com/Levixon10/glancefocus/issues)
> with the output of `glancefocus doctor` if something doesn't work on your setup.

## How it works

```
webcam ──► MediaPipe Face Landmarker ──► gaze features ──► calibration model ──► point on desktop
              (iris, eyelids, head pose,     (22 numbers)      (per-user ridge        │
               eyeLook* blendshapes)                             regression)           ▼
                                                                         ┌──── focus policy ────┐
 window manager ◄── focus window ◄── dwell ✓  typing lock ✓  mouse lock ✓ │ which window is that? │
                                                                         └───────────────────────┘
```

1. **Gaze features.** Each camera frame gives the iris position within each eye, how open the
   eyes are, MediaPipe's learned `eyeLook*` estimates, and where your head points and sits.
2. **Calibration.** Dots appear on every monitor in turn, and a small regression model learns
   how *your* features map to points on *your* desktop. Physical sizes, gaps between screens
   and camera placement all get absorbed by this, so there's nothing to configure. The fit is
   scored on dots it didn't train on, which gives an honest error estimate per monitor.
3. **Focus policy.** The smoothed gaze point is matched against the visible windows. Focus moves
   only after your gaze rests on a window for about 0.45 s, and not within 0.9 s of a key press
   or 0.7 s of mouse movement.

## Accuracy: what to expect

A regular webcam is not a dedicated eye tracker. With good, even lighting and a calibration
done in your normal sitting position, typical errors are **3–6 cm on screen**. In practice:

| Setup | Works? |
|---|---|
| Switching between monitors | Reliable |
| 2–5 tiled windows on a 24–32" monitor | Good |
| 2–3 windows on a 13–14" laptop screen | Borderline. Looking down at a laptop half-closes your eyes. glancefocus measures this and falls back to monitor-level focus if needed |
| Picking one of many small windows | No |

`glancefocus calibrate` prints the measured error for each monitor, and `glancefocus run --debug`
shows it as a circle around the gaze point.

## Platform support

| Platform | Backend | Status |
|---|---|---|
| Linux: Hyprland | `hyprctl` (Lua and classic dispatchers) | **tested** |
| Linux: Sway, i3 | `swaymsg` / `i3-msg` | experimental |
| Linux: X11, any EWMH window manager (GNOME/KDE/Xfce on X11, Openbox, …) | python-xlib | experimental |
| Windows 10/11 | Win32 via ctypes | experimental |
| macOS | Quartz + Accessibility API | experimental |
| Linux: GNOME / KDE on **Wayland** | — | not yet ([why](#gnome-or-kde-on-wayland)) |

## Install

Requires Python 3.11+ and a webcam.

```bash
# Linux (Wayland or X11): the extra lets the typing lock read keyboard activity
pipx install "glancefocus[linux] @ git+https://github.com/Levixon10/glancefocus"
# X11 desktops also need python-xlib:
pipx install "glancefocus[x11] @ git+https://github.com/Levixon10/glancefocus"
# Windows
pipx install "glancefocus[windows] @ git+https://github.com/Levixon10/glancefocus"
# macOS
pipx install "glancefocus[macos] @ git+https://github.com/Levixon10/glancefocus"
```

`pip install` inside a virtualenv works too. The face model (about 3.7 MB) downloads and is
checksum-verified on first run.

**Linux typing lock.** Wayland doesn't let apps see global key presses, so glancefocus reads
key-press *timing* from `/dev/input`. That requires membership of the `input` group:

```bash
sudo usermod -aG input $USER   # then log out and back in
```

Only the time of the last key press is kept. Key codes are discarded immediately. Without this,
glancefocus still works, but it may move focus while you're typing.

## Quick start

```bash
glancefocus doctor                 # checks camera, window manager, keyboard access
glancefocus calibrate              # ~40 s: follow the dots on each monitor
glancefocus run --debug --dry-run  # watch your gaze point on a live map, no focus changes
glancefocus run                    # the real thing
```

Tips for a good calibration:
- Sit the way you normally work, at your normal distance.
- Light your face from the front. A window behind you hurts accuracy.
- Re-run `calibrate` after moving your monitor, laptop or camera, or if accuracy drifts.

### Start automatically and toggle with a key

**Hyprland.** In `hyprland.conf`:

```ini
exec-once = glancefocus run
bind = SUPER, G, exec, glancefocus toggle
```

With a Lua config (newer Hyprland, Omarchy):

```lua
hl.on("hyprland.start", function()
  hl.exec_cmd("glancefocus run")
end)
hl.bind("SUPER + G", hl.dsp.exec_cmd("glancefocus toggle"))
```

**systemd user service (any Linux desktop).** See [`contrib/glancefocus.service`](contrib/glancefocus.service).

`glancefocus toggle` pauses or resumes a running instance, and shows a desktop notification if
`notify-send` is available.

## Commands

| Command | What it does |
|---|---|
| `glancefocus doctor` | Diagnose camera, window manager, keyboard lock and calibration |
| `glancefocus calibrate [--points 5\|9\|13] [--monitor NAME]` | Train the gaze model (9 points per monitor by default) |
| `glancefocus run [--debug] [--dry-run]` | Run. `--debug` shows the live map, `--dry-run` never changes focus |
| `glancefocus windows` | Show monitors and windows as the backend sees them |
| `glancefocus toggle` | Pause or resume the running instance (Linux, macOS) |
| `glancefocus init-config` | Write a config file listing every setting |

Global options: `--camera 1` or `--camera /dev/video2`, `--platform hyprland|sway|i3|x11|windows|macos`, `-v`.

## Configuration

`glancefocus init-config` writes `~/.config/glancefocus/config.toml` (or `%APPDATA%\glancefocus`, or
`~/Library/Application Support/glancefocus`). The most useful settings:

| Setting | Default | Meaning |
|---|---|---|
| `camera` | `"0"` | Camera index or device path |
| `dwell_ms` | `450` | How long to look at a window before it gets focus |
| `typing_lock_ms` | `900` | No switching for this long after a key press |
| `mouse_lock_ms` | `700` | No switching for this long after the mouse moves |
| `cooldown_ms` | `600` | Minimum time between switches |
| `margin_frac` / `margin_min_px` | `0.08` / `20` | Ignore gaze near window edges |
| `small_window_factor` | `2.0` | Windows smaller than this × measured error are picked per monitor instead |
| `smoothing_min_cutoff` | `0.6` | Lower is steadier but laggier |

## Troubleshooting

**`doctor` says "no face detected" or shows low fps.** Webcams lower their frame rate in dim
light. Add light in front of you. If you have several cameras, try `--camera 1`.

**The keyboard lock is OFF.** Install with the `[linux]` extra and join the `input` group (see
above). On macOS, give your terminal *Input Monitoring* permission.

**Calibration dots appear on the wrong monitor.** Run `glancefocus windows` and check that the
monitors are listed with sensible positions, then open an issue with that output.

**Lines like `W0000 … face_landmarker_graph.cc` or `Created TensorFlow Lite XNNPACK delegate`
appear on startup.** These are harmless messages from MediaPipe's C++ code.

**The gaze point is offset or drifts.** Recalibrate in your usual posture. Calibration is
specific to where you sit relative to the camera.

### GNOME or KDE on Wayland

Wayland deliberately has no standard way for one program to list or focus another program's
windows, so each compositor needs its own integration: a GNOME Shell extension, or a KWin
script over D-Bus. Both are planned, and contributions are very welcome (see
[CONTRIBUTING.md](CONTRIBUTING.md)). Until then you can use an X11 session, where the X11
backend applies.

## Privacy

- Camera frames are processed in memory and dropped. Nothing is recorded or uploaded.
- `calibration.json` contains only regression coefficients and your monitor layout.
- The keyboard lock stores one number: when you last pressed a key.

## Roadmap

- Quick 3-point recalibration to correct drift
- GNOME Shell and KWin backends
- Optional Tobii / dedicated eye-tracker input
- Per-window dwell tuning and app allow/deny lists

## Contributing

Bug reports with `glancefocus doctor` output are the most useful thing right now, especially from
the experimental platforms. To add a window-manager backend, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
