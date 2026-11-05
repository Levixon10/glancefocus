"""Hyprland backend (via hyprctl).

Supports both dispatcher syntaxes: the Lua one used by recent Hyprland releases
(`hyprctl dispatch 'hl.dsp.focus({ window = "address:0x…" })'`) and the classic one
(`hyprctl dispatch focuswindow address:0x…`). The working syntax is detected on
first use.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable

from glancefocus.geometry import Monitor, Rect, Window
from glancefocus.platforms.base import Platform, PlatformError, run_command

log = logging.getLogger(__name__)

Runner = Callable[[list[str]], str]


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _hyprctl(args: list[str]) -> str:
    return run_command(["hyprctl", *args])


class Hyprland(Platform):
    name = "hyprland"
    status = "tested"

    def __init__(self, runner: Runner | None = None):
        self._run = runner or _hyprctl
        self._lua: bool | None = None  # dispatcher syntax, detected lazily

    # ---- low level -----------------------------------------------------------
    def _json(self, *args: str):
        out = self._run(["-j", *args])
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise PlatformError(f"hyprctl {' '.join(args)} returned invalid JSON") from e

    def _dispatch(self, lua: str, legacy: list[str]) -> None:
        if self._lua is not False:
            out = self._run(["dispatch", lua]).strip()
            if out == "ok":
                self._lua = True
                return
            if self._lua is True:
                raise PlatformError(f"hyprctl dispatch failed: {out}")
        out = self._run(["dispatch", *legacy]).strip()
        if out == "ok":
            self._lua = False
            return
        raise PlatformError(f"hyprctl dispatch failed: {out}")

    # ---- Platform API --------------------------------------------------------
    def monitors(self) -> list[Monitor]:
        result = []
        for m in self._json("monitors"):
            if m.get("disabled"):
                continue
            scale = float(m.get("scale") or 1.0)
            w, h = m["width"] / scale, m["height"] / scale
            if int(m.get("transform", 0)) % 2 == 1:  # rotated 90/270
                w, h = h, w
            result.append(Monitor(m["name"], Rect(float(m["x"]), float(m["y"]), w, h)))
        return result

    def windows(self) -> list[Window]:
        monitors = self._json("monitors")
        clients = self._json("clients")
        active = self._json("activewindow") or {}
        active_addr = active.get("address")

        mon_name = {m["id"]: m["name"] for m in monitors}
        normal_ws: dict[int, str] = {}
        special_ws: dict[int, str] = {}
        for m in monitors:
            if m.get("disabled"):
                continue
            normal_ws[m["activeWorkspace"]["id"]] = m["name"]
            sid = (m.get("specialWorkspace") or {}).get("id", 0)
            if sid:
                special_ws[sid] = m["name"]
        # An open special workspace covers its monitor's normal workspace.
        covered = set(special_ws.values())

        entries = []
        for c in clients:
            if not c.get("mapped", True) or c.get("hidden"):
                continue
            ws = c["workspace"]["id"]
            if ws in special_ws:
                layer = 0
            elif ws in normal_ws and normal_ws[ws] not in covered:
                layer = 1 if (c.get("floating") or c.get("fullscreen")) else 2
            else:
                continue
            x, y = c["at"]
            w, h = c["size"]
            if w <= 0 or h <= 0:
                continue
            win = Window(
                id=c["address"],
                title=c.get("title", ""),
                app=c.get("class", ""),
                rect=Rect(float(x), float(y), float(w), float(h)),
                monitor=mon_name.get(c.get("monitor")),
                focused=c["address"] == active_addr,
                floating=bool(c.get("floating")),
            )
            entries.append((layer, c.get("focusHistoryID", 1_000_000), ws, bool(c.get("fullscreen")), win))

        # A fullscreen window hides the other tiled windows on its workspace.
        fullscreen_ws = {ws for _, _, ws, fs, _ in entries if fs}
        entries = [e for e in entries if e[2] not in fullscreen_ws or e[3] or e[4].floating]

        entries.sort(key=lambda e: (e[0], e[1]))
        return [dataclasses.replace(e[4], z=i) for i, e in enumerate(entries)]

    def focus_window(self, window: Window) -> None:
        addr = window.id
        self._dispatch(f"hl.dsp.focus({{ window = {_lua_str('address:' + addr)} }})", ["focuswindow", f"address:{addr}"])

    def focus_monitor(self, monitor: Monitor) -> None:
        self._dispatch(f"hl.dsp.focus({{ monitor = {_lua_str(monitor.name)} }})", ["focusmonitor", monitor.name])

    def cursor_pos(self) -> tuple[float, float] | None:
        try:
            p = self._json("cursorpos")
            return float(p["x"]), float(p["y"])
        except (PlatformError, KeyError, TypeError):
            return None

    # ---- calibration overlay -------------------------------------------------
    def overlay_prepare(self, monitor: Monitor) -> None:
        # New windows open on the focused monitor.
        self.focus_monitor(monitor)

    def overlay_place(self, title: str, monitor: Monitor) -> bool | None:
        clients = [c for c in self._json("clients") if c.get("title") == title]
        if not clients:
            return False
        c = clients[0]
        mon_ids = {m["name"]: m["id"] for m in self._json("monitors")}
        if c.get("fullscreen") and c.get("monitor") == mon_ids.get(monitor.name):
            return True
        # Only ever send window dispatchers after confirming our overlay is the active window,
        # because Hyprland's fullscreen dispatcher acts on whatever window has focus.
        if (self._json("activewindow") or {}).get("address") != c["address"]:
            self.focus_window(Window(c["address"], title, "", Rect(0, 0, 1, 1), None))
            return False
        toggle_fullscreen = ('hl.dsp.window.fullscreen({ mode = "fullscreen" })', ["fullscreen", "0"])
        if c.get("fullscreen"):
            # Fullscreen on the wrong monitor: leave fullscreen, move to the right monitor's workspace.
            target_ws = next(
                (m["activeWorkspace"]["id"] for m in self._json("monitors") if m["name"] == monitor.name), None
            )
            self._dispatch(*toggle_fullscreen)
            if target_ws is not None:
                ws = str(target_ws)
                self._dispatch(f"hl.dsp.window.move({{ workspace = {_lua_str(ws)} }})", ["movetoworkspace", ws])
            return False
        self._dispatch(*toggle_fullscreen)
        return False
