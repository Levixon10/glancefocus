"""Window-manager / OS backends and auto-detection."""

from __future__ import annotations

import os
import sys

from glancefocus.platforms.base import Platform, PlatformError

BACKENDS = ("hyprland", "sway", "i3", "x11", "windows", "macos")


def detect_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if os.environ.get("SWAYSOCK"):  # check before I3SOCK: sway sets both
        return "sway"
    if os.environ.get("I3SOCK"):
        return "i3"
    if os.environ.get("WAYLAND_DISPLAY"):
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
        raise PlatformError(
            f"Wayland desktop '{desktop}' is not supported yet. Wayland has no standard way for one app to "
            "focus another app's window, so every compositor needs its own backend. Supported: Hyprland, Sway. "
            "If you're on GNOME or KDE, you can log into an X11 session for now, or help add a backend "
            "(see CONTRIBUTING.md)."
        )
    if os.environ.get("DISPLAY"):
        return "x11"
    raise PlatformError("could not detect a desktop session (no WAYLAND_DISPLAY or DISPLAY)")


def get_platform(name: str | None = None) -> Platform:
    name = (name or os.environ.get("GLANCEFOCUS_PLATFORM") or detect_name()).lower()
    if name == "hyprland":
        from glancefocus.platforms.hyprland import Hyprland

        return Hyprland()
    if name in ("sway", "i3"):
        from glancefocus.platforms.sway import Sway

        return Sway(flavor=name)
    if name == "x11":
        from glancefocus.platforms.x11 import X11

        return X11()
    if name == "windows":
        from glancefocus.platforms.windows import WindowsPlatform

        return WindowsPlatform()
    if name == "macos":
        from glancefocus.platforms.macos import MacOS

        return MacOS()
    raise PlatformError(f"unknown platform {name!r}; choose one of {', '.join(BACKENDS)}")


__all__ = ["BACKENDS", "Platform", "PlatformError", "detect_name", "get_platform"]
