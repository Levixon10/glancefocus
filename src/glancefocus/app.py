"""The main loop: gaze → smoothed desktop point → policy → focus."""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import shutil
import signal
import subprocess
import time

from glancefocus import paths
from glancefocus.activity import create_keyboard_activity
from glancefocus.calibration import Calibration
from glancefocus.config import Settings
from glancefocus.gaze.webcam import WebcamTracker
from glancefocus.geometry import Window
from glancefocus.platforms.base import Platform, PlatformError
from glancefocus.policy import FocusPolicy, PolicyConfig
from glancefocus.smoothing import OneEuro2D

log = logging.getLogger(__name__)

OWN_WINDOW_PREFIX = "glancefocus"
WINDOW_REFRESH_S = 0.15
MONITOR_REFRESH_S = 3.0


def notify(message: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "glancefocus", "-t", "1500", "glancefocus", message], check=False)


class Runner:
    def __init__(self, settings: Settings, platform: Platform, calibration: Calibration,
                 dry_run: bool = False, debug: bool = False):
        self.settings, self.platform, self.calibration = settings, platform, calibration
        self.dry_run, self.debug = dry_run, debug
        self.paused = False
        self.running = True

    # ---- signals / pidfile ---------------------------------------------------
    def _install_signals(self) -> None:
        def stop(*_):
            self.running = False

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        if hasattr(signal, "SIGUSR1"):
            def toggle(*_):
                self.paused = not self.paused
                log.info("paused" if self.paused else "resumed")
                notify("paused" if self.paused else "resumed")

            signal.signal(signal.SIGUSR1, toggle)

    def _write_pid(self) -> None:
        try:
            paths.runtime_dir().mkdir(parents=True, exist_ok=True)
            paths.pid_file().write_text(str(os.getpid()))
        except OSError as e:
            log.debug("pidfile: %s", e)

    def _remove_pid(self) -> None:
        try:
            if paths.pid_file().read_text().strip() == str(os.getpid()):
                paths.pid_file().unlink()
        except OSError:
            pass

    # ---- main loop -------------------------------------------------------------
    def run(self) -> int:
        s = self.settings
        monitors = self.platform.monitors()
        if not self.calibration.layout_matches(monitors):
            log.warning("your monitor layout changed since calibration; results will be off until you re-run "
                        "`glancefocus calibrate`")

        policy = FocusPolicy(PolicyConfig.from_settings(s), self.calibration.per_monitor_px or self.calibration.accuracy_px)
        smoother = OneEuro2D(s.smoothing_min_cutoff, s.smoothing_beta)
        tracker = WebcamTracker(s.camera, s.camera_width, s.camera_height, s.camera_fps, keep_frame=self.debug)
        keyboard = create_keyboard_activity()
        log.info("platform: %s · keyboard lock: %s · accuracy: %s", self.platform.name, keyboard.description,
                 ", ".join(f"{k} ≈{v:.0f}px" for k, v in self.calibration.per_monitor_px.items()))
        if not keyboard.available:
            log.warning("typing lock is OFF, so focus may move while you type (%s)", keyboard.description)

        view = None
        if self.debug:
            from glancefocus.debugview import DebugView
            from glancefocus.overlay import prepare_qt

            prepare_qt()
            view = DebugView()

        self._install_signals()
        try:
            tracker.start()
        except Exception:
            keyboard.stop()
            if view is not None:
                view.close()
            raise
        self._write_pid()  # only once we really own the camera
        try:
            windows: list[Window] = []
            next_windows = next_monitors = 0.0
            last_sample_t = None
            last_face = -math.inf
            point = raw = None
            last_cursor = None
            last_mouse = -math.inf
            switches = 0
            next_trace = 0.0
            trace = log.isEnabledFor(logging.DEBUG)
            period = 1.0 / max(s.poll_hz, 1.0)

            while self.running:
                loop_start = time.monotonic()
                now = loop_start
                try:
                    if now >= next_monitors:
                        monitors = self.platform.monitors()
                        next_monitors = now + MONITOR_REFRESH_S
                    if now >= next_windows:
                        windows = [w for w in self.platform.windows() if not w.title.startswith(OWN_WINDOW_PREFIX)]
                        next_windows = now + WINDOW_REFRESH_S
                except PlatformError as e:
                    log.warning("window manager query failed: %s", e)
                    next_windows = now + 1.0

                sample = tracker.latest()
                if sample is not None and sample.t != last_sample_t:
                    last_sample_t = sample.t
                    if sample.usable:
                        raw = self.calibration.predict(sample.observation.features)
                        point = smoother(raw, sample.t)
                        last_face = sample.t
                if now - last_face > s.face_timeout_ms / 1000:
                    point = raw = None
                    smoother.reset()

                cursor = self.platform.cursor_pos()
                if cursor is not None:
                    if last_cursor is not None and math.dist(cursor, last_cursor) > 2:
                        last_mouse = now
                    last_cursor = cursor

                decision = None
                if not self.paused:
                    decision = policy.update(now, point, windows, monitors, keyboard.last_key, last_mouse)
                if trace and now >= next_trace:
                    next_trace = now + 1.0
                    obs = sample.observation if sample is not None else None
                    res = policy.last_resolution
                    where = f"({point[0]:.0f},{point[1]:.0f}) on {res.monitor.name if res.monitor else 'no monitor'}" \
                        if point else "none"
                    log.debug("gaze %s · face %s · cam %.0f fps · target %s%s · blocked %s",
                              where, "blink" if obs and obs.blink else ("yes" if obs else "NO"), tracker.fps,
                              res.kind, f" {(res.window.app or res.window.title)[:24]}" if res.window else "",
                              policy.blocked_by or "-")

                if decision is not None:
                    w = decision.window
                    log.info("focus → %s · %s%s", w.app or "?", w.title[:60], " (dry run)" if self.dry_run else "")
                    if not self.dry_run:
                        try:
                            self.platform.focus_window(w)
                            switches += 1
                        except PlatformError as e:
                            log.warning("focus failed: %s", e)
                    # Reflect the change locally until the next refresh.
                    windows = [dataclasses.replace(x, focused=(x.id == w.id)) for x in windows]

                if view is not None:
                    obs = sample.observation if sample is not None else None
                    res = policy.last_resolution
                    status = [
                        f"camera {tracker.fps:4.1f} fps   face: {'yes' if obs else 'no'}{'  (blink)' if obs and obs.blink else ''}",
                        f"target: {res.kind}" + (f" -> {(res.window.app or res.window.title)[:30]}" if res.window else ""),
                        f"blocked: {policy.blocked_by or '-'}   switches: {switches}",
                        f"keyboard lock: {'on' if keyboard.available else 'OFF'}   "
                        f"{'PAUSED' if self.paused else ('DRY RUN' if self.dry_run else 'LIVE')}",
                        "keys (in this window):  p pause   d dry-run   q/Esc quit",
                    ]
                    key = view.draw(monitors, windows, point, raw, policy, tracker.latest_frame(),
                                    obs.eye_points if obs else None, status)
                    if key in (ord("q"), 27):
                        break
                    if key == ord("p"):
                        self.paused = not self.paused
                    if key == ord("d"):
                        self.dry_run = not self.dry_run

                time.sleep(max(0.0, period - (time.monotonic() - loop_start)))
        finally:
            tracker.stop()
            keyboard.stop()
            if view is not None:
                view.close()
            self._remove_pid()
        return 0
