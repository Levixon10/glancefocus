"""Windows backend (pure ctypes, no extra dependencies)."""

from __future__ import annotations

import ctypes
import sys

from glancefocus.geometry import Monitor, Rect, Window, assign_monitor
from glancefocus.platforms.base import Platform, PlatformError

GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


class WindowsPlatform(Platform):
    name = "windows"
    status = "experimental"

    def __init__(self):
        if sys.platform != "win32":
            raise PlatformError("the windows backend only runs on Windows")
        from ctypes import wintypes

        self._wt = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._dwm = ctypes.WinDLL("dwmapi")
        # Per-monitor DPI awareness, so window rects and monitor rects share one pixel space.
        try:
            self._user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            try:
                ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
            except (AttributeError, OSError):
                pass

        u = self._user32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindow.restype = wintypes.HWND
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.BringWindowToTop.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    def monitors(self) -> list[Monitor]:
        wt = self._wt

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32),
            ]

        result: list[Monitor] = []
        proc_t = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

        def callback(hmon, _hdc, _rect, _lparam):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if self._user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                result.append(Monitor(info.szDevice, Rect(float(r.left), float(r.top), float(r.right - r.left), float(r.bottom - r.top))))
            return True

        self._user32.EnumDisplayMonitors(None, None, proc_t(callback), 0)
        return result

    def _rect(self, hwnd) -> Rect:
        wt = self._wt
        r = wt.RECT()
        if self._dwm.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            self._user32.GetWindowRect(hwnd, ctypes.byref(r))
        return Rect(float(r.left), float(r.top), float(r.right - r.left), float(r.bottom - r.top))

    def _cloaked(self, hwnd) -> bool:
        val = self._wt.DWORD()
        if self._dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val)) != 0:
            return False
        return bool(val.value)

    def windows(self) -> list[Window]:
        wt, u = self._wt, self._user32
        monitors = self.monitors()
        foreground = u.GetForegroundWindow()
        hwnds: list[int] = []
        proc_t = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def callback(hwnd, _lparam):
            hwnds.append(hwnd)
            return True

        u.EnumWindows(proc_t(callback), 0)  # top of the Z order first

        result = []
        for hwnd in hwnds:
            if not hwnd or not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd):
                continue
            if u.GetWindow(hwnd, GW_OWNER):
                continue
            if u.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                continue
            length = u.GetWindowTextLengthW(hwnd)
            if length == 0 or self._cloaked(hwnd):
                continue
            buf = ctypes.create_unicode_buffer(length + 1)
            u.GetWindowTextW(hwnd, buf, length + 1)
            rect = self._rect(hwnd)
            if rect.w < 50 or rect.h < 50:
                continue
            result.append(
                Window(
                    id=str(int(hwnd)),
                    title=buf.value,
                    app="",
                    rect=rect,
                    monitor=assign_monitor(rect, monitors),
                    focused=bool(foreground) and int(hwnd) == int(foreground),
                    z=len(result),
                )
            )
        return result

    def focus_window(self, window: Window) -> None:
        u = self._user32
        hwnd = self._wt.HWND(int(window.id))
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, SW_RESTORE)
        # Windows only lets the foreground process change the foreground window, so
        # temporarily attach to the current foreground thread's input queue.
        fg = u.GetForegroundWindow()
        fg_thread = u.GetWindowThreadProcessId(fg, None) if fg else 0
        me = self._kernel32.GetCurrentThreadId()
        attached = bool(fg_thread and fg_thread != me and u.AttachThreadInput(me, fg_thread, True))
        try:
            u.BringWindowToTop(hwnd)
            ok = u.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(me, fg_thread, False)
        if not ok or u.GetForegroundWindow() != hwnd.value:
            # Fallback: a synthetic Alt tap counts as user input and unlocks SetForegroundWindow.
            u.keybd_event(VK_MENU, 0, 0, 0)
            u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            if not u.SetForegroundWindow(hwnd):
                raise PlatformError(f"SetForegroundWindow failed for {window.title!r}")

    def cursor_pos(self) -> tuple[float, float] | None:
        p = self._wt.POINT()
        if self._user32.GetCursorPos(ctypes.byref(p)):
            return float(p.x), float(p.y)
        return None
