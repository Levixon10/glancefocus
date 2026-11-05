"""The interface every window-manager / OS backend implements.

A backend needs to do three things: list monitors, list the windows that are
currently *visible* (with their positions in global desktop coordinates), and
focus one of them. Everything else is optional. See CONTRIBUTING.md for a guide
to adding a backend.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod

from glancefocus.geometry import Monitor, Window


class PlatformError(RuntimeError):
    pass


class Platform(ABC):
    name = "base"
    #: Shown by `glancefocus doctor`. "tested" backends are used daily by maintainers.
    status = "experimental"

    @abstractmethod
    def monitors(self) -> list[Monitor]:
        """All active monitors."""

    @abstractmethod
    def windows(self) -> list[Window]:
        """Windows a user could currently be looking at.

        Only windows on visible workspaces, not minimised/hidden. `z` must order
        them so that a lower value is on top (floating, higher in the stack) or,
        for non-overlapping tiled windows, more recently focused. `monitor` is the
        name of the Monitor the window is on.
        """

    @abstractmethod
    def focus_window(self, window: Window) -> None:
        """Give keyboard focus to `window`. Raise PlatformError on failure."""

    def focus_monitor(self, monitor: Monitor) -> None:
        windows = [w for w in self.windows() if w.monitor == monitor.name]
        if windows:
            self.focus_window(min(windows, key=lambda w: w.z))

    def cursor_pos(self) -> tuple[float, float] | None:
        """Mouse position in desktop coordinates, or None if unavailable."""
        return None

    # ---- calibration overlay hooks -----------------------------------------
    def overlay_prepare(self, monitor: Monitor) -> None:
        """Called before the calibration window for `monitor` is created."""
        return None

    def overlay_place(self, title: str, monitor: Monitor) -> bool | None:
        """Make the window titled `title` fullscreen on `monitor`.

        Called repeatedly (once per frame) after the window is shown. Return True
        when done, False to be called again, or None if this backend has no special
        handling, in which case the generic OpenCV move + fullscreen is used.
        """
        return None


def run_command(args: list[str], timeout: float = 2.0) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as e:
        raise PlatformError(f"{args[0]} not found") from e
    except subprocess.TimeoutExpired as e:
        raise PlatformError(f"{args[0]} timed out") from e
    if proc.returncode != 0:
        raise PlatformError(f"{' '.join(args[:3])}… failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout
