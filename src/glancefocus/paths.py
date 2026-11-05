"""Per-OS locations for config, cache and runtime files."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP = "glancefocus"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP


def cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / APP


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    return Path(base) / APP if base else Path(tempfile.gettempdir()) / f"{APP}-{os.getuid() if hasattr(os, 'getuid') else 'user'}"


def config_file() -> Path:
    return config_dir() / "config.toml"


def calibration_file() -> Path:
    return config_dir() / "calibration.json"


def pid_file() -> Path:
    return runtime_dir() / "glancefocus.pid"
