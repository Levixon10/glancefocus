import json

import pytest

from glancefocus.platforms.base import PlatformError
from glancefocus.platforms.hyprland import Hyprland

MONITORS = [
    {"id": 0, "name": "eDP-1", "width": 1920, "height": 1200, "x": 1920, "y": 0, "scale": 1.5, "transform": 0,
     "activeWorkspace": {"id": 2}, "specialWorkspace": {"id": 0}},
    {"id": 1, "name": "HDMI-A-1", "width": 2560, "height": 1440, "x": 0, "y": 0, "scale": 1.3333334, "transform": 0,
     "activeWorkspace": {"id": 1}, "specialWorkspace": {"id": 0}},
]


def client(addr, ws, mon, at, size, history, floating=False, fullscreen=0, title=None):
    return {"address": addr, "mapped": True, "hidden": False, "at": at, "size": size, "workspace": {"id": ws},
            "monitor": mon, "floating": floating, "fullscreen": fullscreen, "class": f"app-{addr}",
            "title": title or f"title-{addr}", "focusHistoryID": history}


CLIENTS = [
    client("0xa", 1, 1, [0, 0], [960, 1080], 0),
    client("0xb", 1, 1, [960, 0], [960, 540], 2),
    client("0xc", 1, 1, [960, 540], [960, 540], 3),
    client("0xd", 2, 0, [1920, 0], [1280, 800], 1),
    client("0xe", 5, 1, [0, 0], [1920, 1080], 4),  # other workspace: invisible
    client("0xf", 1, 1, [500, 300], [400, 300], 5, floating=True),
]


class FakeHyprctl:
    def __init__(self, monitors=MONITORS, clients=CLIENTS, active="0xa", lua=True):
        self.monitors, self.clients, self.active, self.lua = monitors, clients, active, lua
        self.dispatched = []

    def __call__(self, args):
        if args[0] == "-j":
            what = args[1]
            if what == "monitors":
                return json.dumps(self.monitors)
            if what == "clients":
                return json.dumps(self.clients)
            if what == "activewindow":
                return json.dumps({"address": self.active} if self.active else {})
            if what == "cursorpos":
                return json.dumps({"x": 10, "y": 20})
        if args[0] == "dispatch":
            self.dispatched.append(args[1:])
            is_lua = args[1].startswith("hl.dsp")
            return "ok" if is_lua == self.lua else "error: bad syntax"
        raise AssertionError(args)


def test_monitors_logical_size():
    mons = {m.name: m.rect for m in Hyprland(FakeHyprctl()).monitors()}
    assert mons["eDP-1"].w == pytest.approx(1280) and mons["eDP-1"].h == pytest.approx(800)
    assert mons["HDMI-A-1"].w == pytest.approx(1920, abs=0.1)


def test_rotated_monitor_swaps_dimensions():
    mons = [dict(MONITORS[0], transform=1)]
    rect = Hyprland(FakeHyprctl(monitors=mons)).monitors()[0].rect
    assert (round(rect.w), round(rect.h)) == (800, 1280)


def test_windows_visible_only_and_ordered():
    wins = Hyprland(FakeHyprctl()).windows()
    ids = [w.id for w in wins]
    assert "0xe" not in ids
    assert ids[0] == "0xf"  # floating first
    assert ids[1:] == ["0xa", "0xd", "0xb", "0xc"]  # then by focus history
    by_id = {w.id: w for w in wins}
    assert by_id["0xa"].focused and not by_id["0xb"].focused
    assert by_id["0xd"].monitor == "eDP-1" and by_id["0xa"].monitor == "HDMI-A-1"
    assert [w.z for w in wins] == list(range(len(wins)))


def test_fullscreen_hides_other_tiled_windows():
    clients = [dict(c) for c in CLIENTS]
    clients[1]["fullscreen"] = 2
    ids = {w.id for w in Hyprland(FakeHyprctl(clients=clients)).windows()}
    assert ids == {"0xb", "0xf", "0xd"}


def test_special_workspace_covers_monitor():
    mons = [dict(m) for m in MONITORS]
    mons[1]["specialWorkspace"] = {"id": -98}
    clients = CLIENTS + [client("0x5", -98, 1, [100, 100], [800, 600], 6)]
    ids = {w.id for w in Hyprland(FakeHyprctl(monitors=mons, clients=clients)).windows()}
    assert ids == {"0x5", "0xd"}


def test_focus_uses_lua_syntax_when_available():
    fake = FakeHyprctl(lua=True)
    h = Hyprland(fake)
    w = h.windows()[2]
    h.focus_window(w)
    assert fake.dispatched == [[f'hl.dsp.focus({{ window = "address:{w.id}" }})']]


def test_focus_falls_back_to_legacy_syntax():
    fake = FakeHyprctl(lua=False)
    h = Hyprland(fake)
    w = h.windows()[2]
    h.focus_window(w)
    h.focus_window(w)
    assert fake.dispatched[-1] == ["focuswindow", f"address:{w.id}"]
    assert len(fake.dispatched) == 3  # lua tried once, then legacy remembered


def test_dispatch_error_raises():
    class Broken(FakeHyprctl):
        def __call__(self, args):
            if args[0] == "dispatch":
                return "error: nope"
            return super().__call__(args)

    h = Hyprland(Broken())
    with pytest.raises(PlatformError):
        h.focus_window(h.windows()[0])


def test_cursor_pos():
    assert Hyprland(FakeHyprctl()).cursor_pos() == (10.0, 20.0)
