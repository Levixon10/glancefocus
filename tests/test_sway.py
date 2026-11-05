import json

from glancefocus.platforms.sway import Sway


def leaf(id, x, y, w, h, focused=False, fullscreen=0, app="app"):
    return {"id": id, "type": "con", "name": f"win{id}", "app_id": app, "pid": 100 + id, "focused": focused,
            "fullscreen_mode": fullscreen, "rect": {"x": x, "y": y, "width": w, "height": h},
            "nodes": [], "floating_nodes": []}


def tree(ws1_nodes, ws1_floating=()):
    return {
        "type": "root", "nodes": [
            {"type": "output", "name": "__i3", "nodes": []},
            {"type": "output", "name": "DP-1", "nodes": [
                {"type": "workspace", "name": "1", "nodes": ws1_nodes, "floating_nodes": list(ws1_floating)},
                {"type": "workspace", "name": "3", "nodes": [leaf(99, 0, 0, 100, 100)], "floating_nodes": []},
            ]},
            {"type": "output", "name": "eDP-1", "nodes": [
                {"type": "workspace", "name": "2", "nodes": [leaf(7, 1920, 0, 1280, 800)], "floating_nodes": []},
            ]},
        ],
    }


class FakeMsg:
    def __init__(self, t):
        self.tree = t
        self.commands = []

    def __call__(self, args):
        if "-t" in args:
            kind = args[args.index("-t") + 1]
            if kind == "get_tree":
                return json.dumps(self.tree)
            if kind == "get_workspaces":
                return json.dumps([{"name": "1", "visible": True}, {"name": "2", "visible": True},
                                   {"name": "3", "visible": False}])
            if kind == "get_outputs":
                return json.dumps([
                    {"name": "DP-1", "active": True, "rect": {"x": 0, "y": 0, "width": 1920, "height": 1080}},
                    {"name": "eDP-1", "active": True, "rect": {"x": 1920, "y": 0, "width": 1280, "height": 800}},
                    {"name": "HDMI-1", "active": False, "rect": {"x": 0, "y": 0, "width": 0, "height": 0}},
                ])
        self.commands.append(args[1])
        return json.dumps([{"success": True}])


def test_outputs():
    s = Sway(runner=FakeMsg(tree([])))
    assert [m.name for m in s.monitors()] == ["DP-1", "eDP-1"]


def test_tabbed_only_focused_child_visible():
    tabbed = {"id": 50, "type": "con", "layout": "tabbed", "focus": [12, 11], "rect": {},
              "nodes": [leaf(11, 0, 0, 960, 1080), leaf(12, 0, 0, 960, 1080, focused=True)], "floating_nodes": []}
    t = tree([tabbed, leaf(13, 960, 0, 960, 1080)], [leaf(14, 300, 300, 500, 400) | {"type": "floating_con"}])
    wins = Sway(runner=FakeMsg(t)).windows()
    ids = [w.id for w in wins]
    assert set(ids) == {"12", "13", "14", "7"}
    assert ids[0] == "14"  # floating first
    assert {w.id: w.monitor for w in wins}["7"] == "eDP-1"


def test_fullscreen_hides_siblings():
    t = tree([leaf(11, 0, 0, 1920, 1080, fullscreen=1), leaf(13, 960, 0, 960, 1080)])
    ids = {w.id for w in Sway(runner=FakeMsg(t)).windows()}
    assert ids == {"11", "7"}


def test_focus_command():
    fake = FakeMsg(tree([leaf(11, 0, 0, 960, 1080)]))
    s = Sway(runner=fake)
    s.focus_window(s.windows()[0])
    assert fake.commands == ["[con_id=11] focus"]
