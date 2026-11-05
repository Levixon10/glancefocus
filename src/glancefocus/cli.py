"""Command-line interface: `glancefocus {doctor,calibrate,run,windows,toggle,init-config}`."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

from glancefocus import __version__, paths
from glancefocus.config import Settings, load_settings, render_default_config
from glancefocus.platforms import BACKENDS, PlatformError, get_platform

log = logging.getLogger("glancefocus")

OK, BAD, WARN = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m!\033[0m"


def _plain_marks() -> None:
    global OK, BAD, WARN
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        OK, BAD, WARN = "[ok]", "[!!]", "[--]"


# ---- commands -------------------------------------------------------------------

def cmd_windows(args, settings: Settings) -> int:
    platform = get_platform(args.platform)
    print(f"platform: {platform.name} ({platform.status})\n\nmonitors:")
    for m in platform.monitors():
        r = m.rect
        print(f"  {m.name:<14} {r.w:>7.0f} x {r.h:<7.0f} at ({r.x:.0f}, {r.y:.0f})")
    print("\nvisible windows (top first):")
    for w in sorted(platform.windows(), key=lambda w: w.z):
        r = w.rect
        mark = "*" if w.focused else " "
        print(f" {mark}{w.z:>3}  {w.monitor or '?':<10} {r.w:>5.0f}x{r.h:<5.0f} @({r.x:>5.0f},{r.y:>5.0f})  "
              f"{(w.app or '')[:20]:<20} {w.title[:50]}")
    return 0


def cmd_doctor(args, settings: Settings) -> int:
    problems = warnings = 0
    print(f"glancefocus {__version__} · Python {sys.version.split()[0]} · {sys.platform}\n")

    try:
        platform = get_platform(args.platform)
        monitors = platform.monitors()
        windows = platform.windows()
        print(f"{OK} window manager: {platform.name} ({platform.status}), {len(monitors)} monitor(s), "
              f"{len(windows)} visible window(s)")
    except PlatformError as e:
        print(f"{BAD} window manager: {e}")
        platform, monitors, problems = None, [], problems + 1

    try:
        from glancefocus.gaze.model import ensure_model

        print(f"{OK} face model: {ensure_model()}")
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} face model: {e}")
        problems += 1

    try:
        from glancefocus.gaze.webcam import WebcamTracker

        with WebcamTracker(settings.camera, settings.camera_width, settings.camera_height, settings.camera_fps) as tracker:
            seen = faces = 0
            last = None
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and seen < 30:
                s = tracker.latest()
                if s is not None and s.t != last:
                    last, seen, faces = s.t, seen + 1, faces + s.face
                time.sleep(0.01)
            fps = tracker.fps
        mark = OK if faces >= seen * 0.6 and seen else WARN
        warnings += mark != OK
        print(f"{mark} camera {settings.camera}: {seen} frames ({fps:.0f} fps), face found in {faces}")
        if mark != OK:
            print("    look at the screen with your face lit from the front; if this persists, try another `camera`")
        if fps and fps < 12:
            print(f"    {WARN} low frame rate; more light usually helps (webcams lower fps in the dark)")
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} camera {settings.camera}: {e}")
        problems += 1

    from glancefocus.activity import create_keyboard_activity

    kb = create_keyboard_activity()
    print(f"{OK if kb.available else WARN} keyboard lock: {kb.description}")
    warnings += not kb.available
    if not kb.available and sys.platform.startswith("linux"):
        print('    to enable: pip install "glancefocus[linux]" and `sudo usermod -aG input $USER` (then log out and in)')
    kb.stop()

    cal_path = paths.calibration_file()
    if cal_path.exists():
        from glancefocus.calibration import Calibration

        try:
            cal = Calibration.load(cal_path)
            acc = ", ".join(f"{k} ≈{v:.0f}px" for k, v in cal.per_monitor_px.items())
            same = (not monitors) or cal.layout_matches(monitors)
            warnings += not same
            print(f"{OK if same else WARN} calibration: {cal.created}, error {acc}"
                  + ("" if same else " — monitor layout changed, recalibrate"))
        except Exception as e:  # noqa: BLE001
            print(f"{BAD} calibration: {e}")
            problems += 1
    else:
        warnings += 1
        print(f"{WARN} calibration: none yet — run `glancefocus calibrate`")

    if problems:
        print(f"\n{problems} problem(s), {warnings} warning(s)")
    else:
        print("\nall good" if not warnings else f"\nready, with {warnings} warning(s)")
    return 1 if problems else 0


def cmd_calibrate(args, settings: Settings) -> int:
    from glancefocus.calibration import CalibrationAborted, collect, fit
    from glancefocus.gaze.webcam import WebcamTracker

    platform = get_platform(args.platform)
    monitors = platform.monitors()
    if args.monitor:
        monitors = [m for m in monitors if m.name in args.monitor]
        if not monitors:
            print("no monitor matches --monitor", file=sys.stderr)
            return 2
    print(f"Calibrating {len(monitors)} monitor(s): {', '.join(m.name for m in monitors)} "
          f"· {args.points} points each · about {len(monitors) * args.points * 2 + 5} s")

    try:
        with WebcamTracker(settings.camera, settings.camera_width, settings.camera_height, settings.camera_fps) as tracker:
            data = collect(platform, tracker, monitors, points=args.points)
    except CalibrationAborted:
        print("calibration cancelled")
        return 1

    if args.save_samples:
        import numpy as np

        np.savez(args.save_samples, features=np.array(data.features), targets=np.array(data.targets),
                 groups=np.array(data.groups), monitors=np.array(data.monitors))
        print(f"raw samples saved to {args.save_samples}")

    cal, report = fit(data, platform.monitors() if args.monitor else monitors, platform.name)
    if args.monitor:
        print("note: --monitor calibrations only cover the chosen monitors")
    path = paths.calibration_file()
    cal.save(path)
    print(f"\nSaved {path}  ({cal.samples} samples, ridge λ={report.lam:g})")
    print("Estimated error (held-out points):")
    for name, err in cal.per_monitor_px.items():
        mon = next((m for m in monitors if m.name == name), None)
        rel = f" ≈ {100 * err / mon.rect.w:.0f}% of its width" if mon else ""
        print(f"  {name:<14} {err:6.0f} px{rel}")
    print("\nNext: `glancefocus run --debug --dry-run` to watch the gaze point without moving focus.")
    return 0


def cmd_run(args, settings: Settings) -> int:
    from glancefocus.app import Runner
    from glancefocus.calibration import Calibration

    path = paths.calibration_file()
    if not path.exists():
        print("No calibration yet. Run `glancefocus calibrate` first.", file=sys.stderr)
        return 2
    calibration = Calibration.load(path)
    platform = get_platform(args.platform)
    return Runner(settings, platform, calibration, dry_run=args.dry_run, debug=args.debug).run()


def cmd_toggle(args, settings: Settings) -> int:
    if not hasattr(signal, "SIGUSR1"):
        print("toggle is not supported on this OS", file=sys.stderr)
        return 2
    try:
        pid = int(paths.pid_file().read_text().strip())
        os.kill(pid, signal.SIGUSR1)
    except (OSError, ValueError):
        print("glancefocus is not running", file=sys.stderr)
        return 1
    return 0


def cmd_init_config(args, settings: Settings) -> int:
    path = Path(args.config) if args.config else paths.config_file()
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_default_config())
    print(f"wrote {path}")
    return 0


# ---- entry point ----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="glancefocus", description="Focus follows your eyes.")
    p.add_argument("--version", action="version", version=f"glancefocus {__version__}")
    p.add_argument("--config", help=f"config file (default: {paths.config_file()})")
    p.add_argument("--platform", choices=BACKENDS, help="override window manager detection")
    p.add_argument("--camera", help="camera index or device path (overrides config)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check camera, window manager, keyboard access and calibration")
    c = sub.add_parser("calibrate", help="look at dots on each monitor to train the gaze model")
    c.add_argument("--points", type=int, choices=(5, 9, 13), default=9, help="dots per monitor (default 9)")
    c.add_argument("--monitor", action="append", help="only calibrate this monitor (repeatable)")
    c.add_argument("--save-samples", metavar="FILE.npz", help="also save raw samples (for tuning/bug reports)")
    r = sub.add_parser("run", help="start moving focus to where you look")
    r.add_argument("--debug", action="store_true", help="show a live map of windows and your gaze point")
    r.add_argument("--dry-run", action="store_true", help="decide but don't actually change focus")
    sub.add_parser("windows", help="list monitors and visible windows as the backend sees them")
    sub.add_parser("toggle", help="pause/resume a running instance (bind this to a key)")
    i = sub.add_parser("init-config", help="write a config file with all settings and defaults")
    i.add_argument("--force", action="store_true")
    return p


COMMANDS = {
    "doctor": cmd_doctor, "calibrate": cmd_calibrate, "run": cmd_run,
    "windows": cmd_windows, "toggle": cmd_toggle, "init-config": cmd_init_config,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s",
        datefmt="%H:%M:%S",
    )
    _plain_marks()
    settings = load_settings(Path(args.config) if args.config else None)
    if args.camera:
        settings.camera = args.camera
    try:
        return COMMANDS[args.command](args, settings)
    except PlatformError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
