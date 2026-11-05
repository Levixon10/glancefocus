"""Decides *when* to move focus. Pure logic: no camera, no window manager, fully testable.

Rules, in order:

1. Gaze off every monitor, or no face           → forget the current candidate.
2. Gaze in a gap, on the desktop, or in a window's
   edge margin                                    → hold (keep the dwell timer running).
3. Gaze on a window too small for the measured
   accuracy on that monitor                       → candidate = that monitor's last-used window.
4. Otherwise                                      → candidate = the window under the gaze.

A candidate gets focus only when gaze has rested on it for `dwell`, and only if
you haven't typed (`typing_lock`) or moved the mouse (`mouse_lock`) recently, and
the previous automatic switch was more than `cooldown` ago.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from glancefocus.config import Settings
from glancefocus.geometry import Monitor, Window, monitor_at


@dataclass(frozen=True)
class PolicyConfig:
    dwell_s: float = 0.45
    margin_frac: float = 0.08
    margin_min_px: float = 20.0
    typing_lock_s: float = 0.9
    mouse_lock_s: float = 0.7
    cooldown_s: float = 0.6
    small_window_factor: float = 2.0

    @classmethod
    def from_settings(cls, s: Settings) -> PolicyConfig:
        return cls(
            dwell_s=s.dwell_ms / 1000,
            margin_frac=s.margin_frac,
            margin_min_px=s.margin_min_px,
            typing_lock_s=s.typing_lock_ms / 1000,
            mouse_lock_s=s.mouse_lock_ms / 1000,
            cooldown_s=s.cooldown_ms / 1000,
            small_window_factor=s.small_window_factor,
        )


@dataclass(frozen=True)
class Decision:
    window: Window
    reason: str  # "window" or "monitor"


@dataclass(frozen=True)
class Resolution:
    kind: str  # "none" | "hold" | "window" | "monitor"
    window: Window | None = None
    monitor: Monitor | None = None


class FocusPolicy:
    def __init__(self, config: PolicyConfig, accuracy_px: dict[str, float] | float):
        self.config = config
        self.accuracy_px = accuracy_px
        self._candidate: str | None = None
        self._since = 0.0
        self._last_switch = -math.inf
        # Exposed for the debug view.
        self.last_resolution = Resolution("none")
        self.blocked_by: str | None = None
        self.dwell_progress = 0.0

    def accuracy_for(self, monitor: str) -> float:
        if isinstance(self.accuracy_px, dict):
            if monitor in self.accuracy_px:
                return self.accuracy_px[monitor]
            return max(self.accuracy_px.values(), default=100.0)
        return float(self.accuracy_px)

    def margin_for(self, window: Window) -> float:
        return max(self.config.margin_min_px, self.config.margin_frac * min(window.rect.w, window.rect.h))

    def resolve(self, point: tuple[float, float] | None, windows: list[Window], monitors: list[Monitor]) -> Resolution:
        if point is None:
            return Resolution("none")
        mon = monitor_at(monitors, *point)
        if mon is None:
            return Resolution("none")
        on_monitor = sorted((w for w in windows if w.monitor == mon.name), key=lambda w: w.z)
        if not on_monitor:
            return Resolution("none", monitor=mon)
        hit = next((w for w in on_monitor if w.rect.contains(*point)), None)
        if hit is None:
            return Resolution("hold", monitor=mon)
        if min(hit.rect.w, hit.rect.h) < self.config.small_window_factor * self.accuracy_for(mon.name):
            focused_here = next((w for w in on_monitor if w.focused), None)
            return Resolution("monitor", focused_here or on_monitor[0], mon)
        if not hit.rect.inset(self.margin_for(hit)).contains(*point):
            return Resolution("hold", monitor=mon)
        return Resolution("window", hit, mon)

    def update(
        self,
        now: float,
        point: tuple[float, float] | None,
        windows: list[Window],
        monitors: list[Monitor],
        last_key: float = -math.inf,
        last_mouse: float = -math.inf,
    ) -> Decision | None:
        res = self.resolve(point, windows, monitors)
        self.last_resolution = res
        self.blocked_by = None

        if res.kind == "none":
            self._candidate = None
            self.dwell_progress = 0.0
            return None
        if res.kind == "hold" or res.window is None:
            return None

        win = res.window
        if win.id != self._candidate:
            self._candidate = win.id
            self._since = now
        self.dwell_progress = min(1.0, (now - self._since) / self.config.dwell_s) if self.config.dwell_s > 0 else 1.0

        if win.focused:
            return None
        if now - self._since < self.config.dwell_s:
            return None
        if now - last_key < self.config.typing_lock_s:
            self.blocked_by = "typing"
            return None
        if now - last_mouse < self.config.mouse_lock_s:
            self.blocked_by = "mouse"
            return None
        if now - self._last_switch < self.config.cooldown_s:
            self.blocked_by = "cooldown"
            return None
        self._last_switch = now
        return Decision(win, res.kind)
