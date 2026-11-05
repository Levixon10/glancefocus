"""Keyboard activity, for the "don't move focus while I'm typing" lock.

Privacy: only the *time* of the last key press is kept. Key codes are read by the
OS-level listener and immediately discarded; nothing is logged or stored.
"""

from __future__ import annotations

import logging
import math
import select
import sys
import threading
import time

log = logging.getLogger(__name__)


class KeyboardActivity:
    available = False
    description = "disabled"

    def __init__(self):
        self.last_key = -math.inf

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _touch(self) -> None:
        self.last_key = time.monotonic()


class EvdevActivity(KeyboardActivity):
    """Linux, any session type (X11 or Wayland). Needs read access to /dev/input."""

    def __init__(self):
        super().__init__()
        import evdev  # noqa: F401 - raise ImportError early

        self._devices = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import evdev
        from evdev import ecodes

        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            keys = dev.capabilities().get(ecodes.EV_KEY, [])
            if ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys:
                self._devices.append(dev)
            else:
                dev.close()
        if not self._devices:
            self.description = "no readable keyboards in /dev/input (add yourself to the 'input' group)"
            return
        self.available = True
        self.description = f"evdev ({len(self._devices)} keyboard{'s' if len(self._devices) != 1 else ''})"
        self._thread = threading.Thread(target=self._loop, name="glancefocus-keys", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        from evdev import ecodes

        by_fd = {d.fd: d for d in self._devices}
        while not self._stop.is_set() and by_fd:
            ready, _, _ = select.select(list(by_fd), [], [], 0.5)
            for fd in ready:
                dev = by_fd[fd]
                try:
                    for ev in dev.read():
                        if ev.type == ecodes.EV_KEY and ev.value in (1, 2):  # press or auto-repeat
                            self._touch()
                except OSError:  # unplugged
                    by_fd.pop(fd, None)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        for d in self._devices:
            try:
                d.close()
            except OSError:
                pass


class PynputActivity(KeyboardActivity):
    """X11, Windows, macOS (macOS needs Input Monitoring permission)."""

    def __init__(self):
        super().__init__()
        from pynput import keyboard  # noqa: F401

        self._listener = None

    def start(self) -> None:
        from pynput import keyboard

        self._listener = keyboard.Listener(on_press=lambda _key: self._touch())
        self._listener.daemon = True
        self._listener.start()
        self.available = True
        self.description = "pynput"

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()


def create_keyboard_activity() -> KeyboardActivity:
    candidates = [EvdevActivity, PynputActivity] if sys.platform.startswith("linux") else [PynputActivity]
    reasons = []
    for cls in candidates:
        try:
            act = cls()
            act.start()
        except ImportError as e:
            reasons.append(f"{cls.__name__}: {e.name} not installed")
            continue
        except Exception as e:  # noqa: BLE001 - listener backends fail in many ways
            reasons.append(f"{cls.__name__}: {e}")
            continue
        if act.available:
            return act
        reasons.append(act.description)
    fallback = KeyboardActivity()
    fallback.description = "unavailable — " + "; ".join(reasons)
    return fallback
