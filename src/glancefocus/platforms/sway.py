"""Sway and i3 backend (via swaymsg / i3-msg; both speak the same IPC)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable

from glancefocus.geometry import Monitor, Rect, Window
from glancefocus.platforms.base import Platform, PlatformError, run_command

Runner = Callable[[list[str]], str]


class Sway(Platform):
    status = "experimental"

    def __init__(self, flavor: str = "sway", runner: Runner | None = None):
        self.name = flavor
        self._cmd = "swaymsg" if flavor == "sway" else "i3-msg"
        self._run = runner or (lambda args: run_command(args))

    def _get(self, kind: str):
        args = [self._cmd, "-t", kind]
        if self._cmd == "swaymsg":
            args.append("-r")
        try:
            return json.loads(self._run(args))
        except json.JSONDecodeError as e:
            raise PlatformError(f"{self._cmd} -t {kind} returned invalid JSON") from e

    def _command(self, command: str) -> None:
        out = self._run([self._cmd, command])
        try:
            replies = json.loads(out)
        except json.JSONDecodeError:
            return
        for r in replies if isinstance(replies, list) else [replies]:
            if isinstance(r, dict) and not r.get("success", True):
                raise PlatformError(f"{self._cmd} {command!r}: {r.get('error')}")

    def monitors(self) -> list[Monitor]:
        out = []
        for o in self._get("get_outputs"):
            if not o.get("active"):
                continue
            r = o["rect"]
            out.append(Monitor(o["name"], Rect(float(r["x"]), float(r["y"]), float(r["width"]), float(r["height"]))))
        return out

    def windows(self) -> list[Window]:
        visible = {w["name"] for w in self._get("get_workspaces") if w.get("visible")}
        tree = self._get("get_tree")
        found: list[tuple[int, int, Window, bool, str]] = []

        def leaves(node, output: str, ws: str, floating: bool):
            kids = node.get("nodes") or []
            floats = node.get("floating_nodes") or []
            if node.get("type") in ("con", "floating_con") and not kids and not floats:
                if node.get("pid") is not None or node.get("window") is not None:
                    yield node, output, ws, floating
                return
            if node.get("layout") in ("tabbed", "stacked") and kids:
                # Only the focused tab is visible.
                order = node.get("focus") or []
                top = next((k for k in kids if order and k["id"] == order[0]), kids[0])
                kids = [top]
            for k in kids:
                yield from leaves(k, output, ws, floating)
            for f in floats:
                yield from leaves(f, output, ws, True)

        for out in tree.get("nodes", []):
            if out.get("type") != "output" or out.get("name", "").startswith("__"):
                continue
            for ws in out.get("nodes", []):
                if ws.get("type") != "workspace" or ws.get("name") not in visible:
                    continue
                for node, output, wsname, floating in leaves(ws, out["name"], ws["name"], False):
                    r = node["rect"]
                    props = node.get("window_properties") or {}
                    win = Window(
                        id=str(node["id"]),
                        title=node.get("name") or "",
                        app=node.get("app_id") or props.get("class") or "",
                        rect=Rect(float(r["x"]), float(r["y"]), float(r["width"]), float(r["height"])),
                        monitor=output,
                        focused=bool(node.get("focused")),
                        floating=floating,
                    )
                    rank = 0 if floating else 1
                    found.append((rank, 0 if win.focused else 1, win, bool(node.get("fullscreen_mode")), wsname))

        fullscreen_ws = {ws for *_, fs, ws in found if fs}
        found = [f for f in found if f[4] not in fullscreen_ws or f[3]]
        found.sort(key=lambda f: (f[0], f[1]))
        return [dataclasses.replace(f[2], z=i) for i, f in enumerate(found)]

    def focus_window(self, window: Window) -> None:
        self._command(f"[con_id={int(window.id)}] focus")

    def focus_monitor(self, monitor: Monitor) -> None:
        self._command(f'focus output "{monitor.name}"')

    def overlay_prepare(self, monitor: Monitor) -> None:
        self.focus_monitor(monitor)

    def overlay_place(self, title: str, monitor: Monitor) -> bool | None:
        for w in self.windows():
            if w.title == title:
                if w.monitor != monitor.name:
                    self._command(f'[con_id={int(w.id)}] move container to output "{monitor.name}"')
                    return False
                self._command(f"[con_id={int(w.id)}] fullscreen enable")
                return True
        return False
