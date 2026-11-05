"""User settings, loaded from a flat TOML file (see `glancefocus init-config`)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from glancefocus import paths

log = logging.getLogger(__name__)


@dataclass
class Settings:
    # Camera: an index ("0") or a device path ("/dev/video2").
    camera: str = "0"
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30

    # How long your gaze must rest on a window before it gets focus.
    dwell_ms: int = 450
    # Ignore gaze near window edges: max(margin_min_px, margin_frac * shorter side).
    margin_frac: float = 0.08
    margin_min_px: float = 20.0
    # Never switch within this long after a key press (needs keyboard access, see README).
    typing_lock_ms: int = 900
    # Never switch within this long after the mouse moved.
    mouse_lock_ms: int = 700
    # Minimum time between two automatic switches.
    cooldown_ms: int = 600
    # A window is "too small to pick by gaze" when its shorter side is under
    # small_window_factor * the calibration error on that monitor. Looking at a
    # monitor full of small windows then only moves focus to that monitor.
    small_window_factor: float = 2.0

    # One-Euro smoothing of the gaze point (lower min_cutoff = smoother but laggier).
    smoothing_min_cutoff: float = 0.6
    smoothing_beta: float = 0.004
    # Keep the last gaze point this long when the face is briefly lost (blinks).
    face_timeout_ms: int = 400
    # Main loop rate.
    poll_hz: float = 20.0


def load_settings(path: Path | None = None) -> Settings:
    path = path or paths.config_file()
    settings = Settings()
    if not path.exists():
        return settings
    with open(path, "rb") as f:
        data = tomllib.load(f)
    known = {f.name: f for f in fields(Settings)}
    for key, value in data.items():
        if key not in known:
            log.warning("config: unknown setting %r ignored", key)
            continue
        current = getattr(settings, key)
        try:
            setattr(settings, key, type(current)(value))
        except (TypeError, ValueError):
            log.warning("config: bad value for %s: %r", key, value)
    return settings


def render_default_config() -> str:
    lines = ["# glancefocus configuration. Delete a line to use the default.", ""]
    for key, value in asdict(Settings()).items():
        lines.append(f"{key} = {value!r}" if not isinstance(value, str) else f'{key} = "{value}"')
    return "\n".join(lines) + "\n"
