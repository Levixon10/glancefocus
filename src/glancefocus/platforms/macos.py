"""macOS backend (Quartz window list + Accessibility API).

Needs `pip install "glancefocus[macos]"`, and in System Settings → Privacy & Security:
* Accessibility, to raise a specific window,
* Screen Recording, for window titles (optional; focusing works without it),
* Camera, for the terminal/app that runs glancefocus.
"""

from __future__ import annotations

import sys

from glancefocus.geometry import Monitor, Rect, Window, assign_monitor
from glancefocus.platforms.base import Platform, PlatformError


class MacOS(Platform):
    name = "macos"
    status = "experimental"

    def __init__(self):
        if sys.platform != "darwin":
            raise PlatformError("the macos backend only runs on macOS")
        try:
            import AppKit
            import ApplicationServices
            import Quartz
        except ImportError as e:
            raise PlatformError('macOS support needs pyobjc: pip install "glancefocus[macos]"') from e
        self._q, self._ax, self._appkit = Quartz, ApplicationServices, AppKit
        if not ApplicationServices.AXIsProcessTrusted():
            raise PlatformError(
                "grant Accessibility access to your terminal (System Settings → Privacy & Security → Accessibility)"
            )

    def monitors(self) -> list[Monitor]:
        q = self._q
        err, ids, count = q.CGGetActiveDisplayList(32, None, None)
        if err:
            raise PlatformError(f"CGGetActiveDisplayList failed ({err})")
        result = []
        for d in ids[:count]:
            b = q.CGDisplayBounds(d)  # global display space, points, origin top-left of main display
            result.append(Monitor(f"display-{int(d)}", Rect(b.origin.x, b.origin.y, b.size.width, b.size.height)))
        return result

    def windows(self) -> list[Window]:
        q = self._q
        monitors = self.monitors()
        front = self._appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        front_pid = int(front.processIdentifier()) if front else -1
        infos = q.CGWindowListCopyWindowInfo(
            q.kCGWindowListOptionOnScreenOnly | q.kCGWindowListExcludeDesktopElements, q.kCGNullWindowID
        )
        result = []
        focused_given = False
        for info in infos or []:  # front to back
            if info.get("kCGWindowLayer", 0) != 0:
                continue
            b = info.get("kCGWindowBounds") or {}
            rect = Rect(float(b.get("X", 0)), float(b.get("Y", 0)), float(b.get("Width", 0)), float(b.get("Height", 0)))
            if rect.w < 50 or rect.h < 50:
                continue
            pid = int(info.get("kCGWindowOwnerPID", -1))
            focused = not focused_given and pid == front_pid
            focused_given |= focused
            result.append(
                Window(
                    id=f"{pid}:{int(info.get('kCGWindowNumber', 0))}",
                    title=str(info.get("kCGWindowName") or ""),
                    app=str(info.get("kCGWindowOwnerName") or ""),
                    rect=rect,
                    monitor=assign_monitor(rect, monitors),
                    focused=focused,
                    z=len(result),
                )
            )
        return result

    def focus_window(self, window: Window) -> None:
        ax = self._ax
        pid = int(window.id.split(":", 1)[0])
        app_el = ax.AXUIElementCreateApplication(pid)
        err, ax_windows = ax.AXUIElementCopyAttributeValue(app_el, ax.kAXWindowsAttribute, None)
        target = None
        for w in ax_windows or []:
            _, pos = ax.AXUIElementCopyAttributeValue(w, ax.kAXPositionAttribute, None)
            _, size = ax.AXUIElementCopyAttributeValue(w, ax.kAXSizeAttribute, None)
            if pos is None or size is None:
                continue
            _, p = ax.AXValueGetValue(pos, ax.kAXValueCGPointType, None)
            _, s = ax.AXValueGetValue(size, ax.kAXValueCGSizeType, None)
            if abs(p.x - window.rect.x) < 4 and abs(p.y - window.rect.y) < 4 and abs(s.width - window.rect.w) < 4:
                target = w
                break
        if target is not None:
            ax.AXUIElementPerformAction(target, ax.kAXRaiseAction)
            ax.AXUIElementSetAttributeValue(target, ax.kAXMainAttribute, True)
        app = self._appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            raise PlatformError(f"process {pid} is gone")
        app.activateWithOptions_(self._appkit.NSApplicationActivateIgnoringOtherApps)

    def cursor_pos(self) -> tuple[float, float] | None:
        q = self._q
        p = q.CGEventGetLocation(q.CGEventCreate(None))
        return float(p.x), float(p.y)
