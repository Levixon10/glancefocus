"""A fullscreen OpenCV window on one monitor, used for calibration."""

from __future__ import annotations

import logging
import os
import sys
import time

import numpy as np

from glancefocus.geometry import Monitor
from glancefocus.platforms.base import Platform, PlatformError

log = logging.getLogger(__name__)

TITLE = "glancefocus-calibration"
BG = (24, 20, 18)


def prepare_qt() -> None:
    """The pip build of OpenCV ships Qt with only the X11 (xcb) plugin; on Wayland that runs via XWayland."""
    if sys.platform.startswith("linux"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        os.environ.setdefault("QT_LOGGING_RULES", "default.warning=false;qt.qpa.*=false")


class Overlay:
    """Draws onto a canvas with the monitor's aspect ratio, stretched to fill the window.

    Targets are placed at *fractions* of the monitor, so the result is correct even
    when the toolkit's pixel size differs from the desktop's (fractional scaling,
    XWayland, HiDPI): fraction (fx, fy) maps to desktop point
    (monitor.x + fx * monitor.w, monitor.y + fy * monitor.h).
    """

    def __init__(self, platform: Platform, monitor: Monitor, title: str = TITLE, max_width: int = 1920):
        self.platform, self.monitor, self.title = platform, monitor, title
        scale = min(1.0, max_width / max(monitor.rect.w, 1))
        self.w = max(int(monitor.rect.w * scale), 64)
        self.h = max(int(monitor.rect.h * scale), 64)
        self.unit = self.w / 1600  # for sizing text and dots

    def __enter__(self) -> Overlay:
        import cv2

        prepare_qt()
        try:
            self.platform.overlay_prepare(self.monitor)
        except PlatformError as e:
            log.warning("overlay: %s", e)
        cv2.namedWindow(self.title, cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO)
        blank = self.canvas()
        self.show(blank, 30)

        generic = False
        deadline = time.monotonic() + 4.0
        while True:
            try:
                placed = self.platform.overlay_place(self.title, self.monitor)
            except PlatformError as e:
                log.warning("overlay: %s", e)
                placed = None
            if placed is None:
                generic = True
                break
            if placed:
                break
            if time.monotonic() > deadline:
                log.warning("could not make the calibration window fullscreen on %s", self.monitor.name)
                break
            self.show(blank, 60)
        if generic:
            cv2.moveWindow(self.title, int(self.monitor.rect.x), int(self.monitor.rect.y))
            cv2.setWindowProperty(self.title, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        for _ in range(8):  # let the window manager settle
            self.show(blank, 25)
        return self

    def __exit__(self, *exc) -> None:
        import cv2

        cv2.destroyWindow(self.title)
        cv2.waitKey(1)

    def canvas(self) -> np.ndarray:
        img = np.empty((self.h, self.w, 3), np.uint8)
        img[:] = BG
        return img

    def px(self, fx: float, fy: float) -> tuple[int, int]:
        return int(round(fx * self.w)), int(round(fy * self.h))

    def to_desktop(self, fx: float, fy: float) -> tuple[float, float]:
        r = self.monitor.rect
        return r.x + fx * r.w, r.y + fy * r.h

    def text(self, img, s: str, fy: float, scale: float = 1.0, color=(235, 235, 235), thickness: int = 2) -> None:
        import cv2

        fs = 0.9 * scale * self.unit * 1.6
        th = max(1, int(thickness * self.unit * 1.4))
        (tw, _), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        cv2.putText(img, s, ((self.w - tw) // 2, int(fy * self.h)), cv2.FONT_HERSHEY_SIMPLEX, fs, color, th, cv2.LINE_AA)

    def show(self, img: np.ndarray, wait_ms: int = 1) -> int:
        import cv2

        cv2.imshow(self.title, img)
        return cv2.waitKey(wait_ms) & 0xFF
