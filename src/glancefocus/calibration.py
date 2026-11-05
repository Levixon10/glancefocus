"""Calibration: show dots on every monitor, record gaze features, fit the mapping."""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from glancefocus.gaze.features import FEATURE_NAMES
from glancefocus.geometry import Monitor
from glancefocus.mapping import FitReport, GazeMapper
from glancefocus.platforms.base import Platform

log = logging.getLogger(__name__)

CALIBRATION_VERSION = 1

_ROW = (0.06, 0.5, 0.94)
_COL = (0.08, 0.5, 0.92)
GRIDS: dict[int, list[tuple[float, float]]] = {
    5: [(0.5, 0.5), (0.06, 0.08), (0.94, 0.08), (0.94, 0.92), (0.06, 0.92)],
    # Snake order keeps eye travel short.
    9: [(x, _COL[0]) for x in _ROW] + [(x, _COL[1]) for x in reversed(_ROW)] + [(x, _COL[2]) for x in _ROW],
}
GRIDS[13] = GRIDS[9] + [(0.28, 0.29), (0.72, 0.29), (0.72, 0.71), (0.28, 0.71)]

KEY_SPACE, KEY_ESC, KEY_ENTER = 32, 27, 13


class CalibrationAborted(Exception):
    pass


@dataclass
class Calibration:
    mapper: GazeMapper
    accuracy_px: float
    per_monitor_px: dict[str, float]
    layout: list[dict]
    platform: str
    samples: int
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def predict(self, features: np.ndarray) -> tuple[float, float]:
        return self.mapper.predict(features)

    def layout_matches(self, monitors: list[Monitor]) -> bool:
        return _layout(monitors) == self.layout

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": CALIBRATION_VERSION,
            "created": self.created,
            "platform": self.platform,
            "samples": self.samples,
            "accuracy_px": self.accuracy_px,
            "per_monitor_px": self.per_monitor_px,
            "layout": self.layout,
            "mapper": self.mapper.to_dict(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Calibration:
        data = json.loads(path.read_text())
        if data.get("version") != CALIBRATION_VERSION:
            raise ValueError("calibration file is from an incompatible version; run `glancefocus calibrate` again")
        mapper = GazeMapper.from_dict(data["mapper"])
        if tuple(mapper.feature_names) != FEATURE_NAMES:
            raise ValueError("calibration was made with different gaze features; run `glancefocus calibrate` again")
        return cls(
            mapper=mapper,
            accuracy_px=float(data["accuracy_px"]),
            per_monitor_px={k: float(v) for k, v in data["per_monitor_px"].items()},
            layout=data["layout"],
            platform=data["platform"],
            samples=int(data["samples"]),
            created=data["created"],
        )


def _layout(monitors: list[Monitor]) -> list[dict]:
    return sorted(
        ({"name": m.name, "x": round(m.rect.x), "y": round(m.rect.y), "w": round(m.rect.w), "h": round(m.rect.h)} for m in monitors),
        key=lambda d: d["name"],
    )


@dataclass
class CalibrationData:
    features: list[np.ndarray] = field(default_factory=list)
    targets: list[tuple[float, float]] = field(default_factory=list)
    groups: list[int] = field(default_factory=list)
    monitors: list[str] = field(default_factory=list)

    def add(self, f: np.ndarray, target: tuple[float, float], group: int, monitor: str) -> None:
        self.features.append(f)
        self.targets.append(target)
        self.groups.append(group)
        self.monitors.append(monitor)


def collect(
    platform: Platform,
    tracker,
    monitors: list[Monitor],
    points: int = 9,
    settle_s: float = 0.9,
    collect_s: float = 1.0,
) -> CalibrationData:
    """Run the on-screen calibration. Raises CalibrationAborted on Esc."""
    import cv2

    from glancefocus.overlay import Overlay

    grid = GRIDS[points]
    data = CalibrationData()
    group = 0
    for mi, mon in enumerate(monitors):
        with Overlay(platform, mon) as ov:
            # Intro screen: wait for SPACE, show whether a face is visible.
            while True:
                img = ov.canvas()
                ov.text(img, f"glancefocus calibration  -  monitor {mi + 1} of {len(monitors)}  ({mon.name})", 0.30, 1.2)
                ov.text(img, "Sit the way you normally do. Follow each dot with your eyes until it disappears.", 0.42, 0.8, (200, 200, 200))
                ov.text(img, "Moving your head a little is fine - it makes the result more robust.", 0.48, 0.8, (200, 200, 200))
                sample = tracker.latest()
                face = sample is not None and sample.face and time.monotonic() - sample.t < 0.5
                ov.text(img, "face detected" if face else "no face detected - check the camera and lighting",
                        0.60, 0.8, (120, 220, 120) if face else (90, 90, 240))
                ov.text(img, "SPACE  start        ESC  cancel", 0.72, 0.9)
                key = ov.show(img, 30)
                if key == KEY_ESC:
                    raise CalibrationAborted
                if key in (KEY_SPACE, KEY_ENTER) and face:
                    break

            for pi, (fx, fy) in enumerate(grid):
                target = ov.to_desktop(fx, fy)
                center = ov.px(fx, fy)
                got = _show_target(ov, tracker, center, settle_s, collect_s, f"{pi + 1}/{len(grid)}")
                if got is None:
                    raise CalibrationAborted
                if len(got) < 4:
                    log.warning("only %d samples for point %d on %s; skipping it", len(got), pi + 1, mon.name)
                    continue
                for f in got:
                    data.add(f, target, group, mon.name)
                group += 1
    cv2.waitKey(1)
    return data


def _show_target(ov, tracker, center, settle_s, collect_s, label) -> list[np.ndarray] | None:
    import cv2

    u = ov.unit
    r_big, r_small = int(60 * u) + 8, int(9 * u) + 3
    samples: list[np.ndarray] = []
    last_t = None
    t0 = time.monotonic()
    collect_until = t0 + settle_s + collect_s
    hard_stop = collect_until + 1.5  # extra time if the face was lost (blinks, glare)
    while True:
        now = time.monotonic()
        elapsed = now - t0
        img = ov.canvas()
        cv2.putText(img, label, (int(20 * u) + 10, int(40 * u) + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8 * u + 0.3, (110, 110, 110), 1, cv2.LINE_AA)
        if elapsed < settle_s:
            k = elapsed / settle_s
            radius = int(r_big + (r_small * 2 - r_big) * (1 - (1 - k) ** 2))
            cv2.circle(img, center, radius, (90, 170, 255), max(2, int(3 * u)), cv2.LINE_AA)
            cv2.circle(img, center, r_small, (255, 255, 255), -1, cv2.LINE_AA)
        else:
            sample = tracker.latest()
            if sample is not None and sample.t != last_t:
                last_t = sample.t
                if sample.usable and sample.t >= t0 + settle_s:
                    samples.append(sample.observation.features.copy())
            k = min(1.0, (elapsed - settle_s) / collect_s)
            cv2.circle(img, center, r_small * 2, (70, 200, 120), -1, cv2.LINE_AA)
            cv2.ellipse(img, center, (r_small * 3, r_small * 3), -90, 0, 360 * k, (255, 255, 255), max(2, int(3 * u)), cv2.LINE_AA)
            cv2.circle(img, center, max(2, r_small // 2), (255, 255, 255), -1, cv2.LINE_AA)
            if (now >= collect_until and len(samples) >= 8) or now >= hard_stop:
                return samples
        if ov.show(img, 10) == KEY_ESC:
            return None


def fit(data: CalibrationData, monitors: list[Monitor], platform_name: str) -> tuple[Calibration, FitReport]:
    x = np.array(data.features)
    y = np.array(data.targets)
    groups = np.array(data.groups)
    mapper, report = GazeMapper.fit(x, y, groups)
    names = np.array(data.monitors)
    per_monitor = {
        name: float(math.sqrt(np.mean(report.cv_errors[names == name] ** 2))) for name in sorted(set(data.monitors))
    }
    cal = Calibration(
        mapper=mapper,
        accuracy_px=report.cv_rmse,
        per_monitor_px=per_monitor,
        layout=_layout(monitors),
        platform=platform_name,
        samples=len(x),
    )
    return cal, report
