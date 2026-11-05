"""Plain geometry types shared by every part of glancefocus.

All coordinates are in the platform's *global desktop* space: the same space the
window manager uses to report window positions (logical pixels on Wayland
compositors and macOS, physical pixels on X11 and per-monitor-DPI-aware Windows).
Calibration maps gaze straight into this space, so no backend ever has to convert.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def inset(self, margin: float) -> Rect:
        """Shrink by `margin` on every side (never below zero size)."""
        m = min(margin, self.w / 2, self.h / 2)
        return Rect(self.x + m, self.y + m, self.w - 2 * m, self.h - 2 * m)

    def union(self, other: Rect) -> Rect:
        x, y = min(self.x, other.x), min(self.y, other.y)
        return Rect(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)


@dataclass(frozen=True)
class Monitor:
    name: str
    rect: Rect


@dataclass(frozen=True)
class Window:
    id: str
    title: str
    app: str
    rect: Rect
    monitor: str | None
    focused: bool = False
    # Lower is "more on top / more recently used". Backends sort floating windows and
    # windows higher in the stacking order first, then by focus history.
    z: int = 0
    floating: bool = False


def monitor_at(monitors: list[Monitor], px: float, py: float) -> Monitor | None:
    for m in monitors:
        if m.rect.contains(px, py):
            return m
    return None


def assign_monitor(rect: Rect, monitors: list[Monitor]) -> str | None:
    """Name of the monitor containing the rect's centre (or overlapping it most)."""
    cx, cy = rect.center
    m = monitor_at(monitors, cx, cy)
    if m:
        return m.name
    best, best_area = None, 0.0
    for mon in monitors:
        ix = max(0.0, min(rect.right, mon.rect.right) - max(rect.x, mon.rect.x))
        iy = max(0.0, min(rect.bottom, mon.rect.bottom) - max(rect.y, mon.rect.y))
        if ix * iy > best_area:
            best, best_area = mon.name, ix * iy
    return best
