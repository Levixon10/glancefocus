import math

from glancefocus.geometry import Monitor, Rect, Window
from glancefocus.policy import FocusPolicy, PolicyConfig

BIG = Monitor("big", Rect(0, 0, 1920, 1080))
SMALL = Monitor("small", Rect(1920, 0, 1280, 800))
MONITORS = [BIG, SMALL]


def win(id, x, y, w, h, monitor="big", focused=False, z=0):
    return Window(id, id, id, Rect(x, y, w, h), monitor, focused=focused, z=z)


LEFT = win("left", 0, 0, 960, 1080, focused=True, z=0)
RIGHT = win("right", 960, 0, 960, 1080, z=1)
LAPTOP_A = win("lapA", 1920, 0, 640, 800, monitor="small", z=2)
LAPTOP_B = win("lapB", 2560, 0, 640, 800, monitor="small", z=3)
WINDOWS = [LEFT, RIGHT, LAPTOP_A, LAPTOP_B]

CFG = PolicyConfig(dwell_s=0.4, typing_lock_s=1.0, mouse_lock_s=0.5, cooldown_s=0.6, small_window_factor=2.0)


def make(accuracy=60.0):
    return FocusPolicy(CFG, accuracy)


def run_steps(policy, point, t0, t1, step=0.05, windows=WINDOWS, **kw):
    t, decision = t0, None
    while t <= t1 + 1e-9:
        d = policy.update(t, point, windows, MONITORS, **kw)
        decision = decision or d
        t += step
    return decision


def test_dwell_required_before_switch():
    p = make()
    assert run_steps(p, (1440, 540), 0.0, 0.3) is None
    d = run_steps(p, (1440, 540), 0.35, 0.5)
    assert d is not None and d.window.id == "right" and d.reason == "window"


def test_no_switch_to_already_focused_window():
    p = make()
    assert run_steps(p, (480, 540), 0.0, 2.0) is None


def test_edge_margin_holds():
    p = make()
    # 960 is the border between the windows; 965 is inside RIGHT's margin.
    assert p.resolve((965, 540), WINDOWS, MONITORS).kind == "hold"
    assert run_steps(p, (965, 540), 0.0, 2.0) is None


def test_hold_keeps_dwell_timer():
    p = make()
    p.update(0.0, (1440, 540), WINDOWS, MONITORS)
    p.update(0.2, (965, 540), WINDOWS, MONITORS)  # brief slip into the margin
    d = p.update(0.45, (1440, 540), WINDOWS, MONITORS)
    assert d is not None and d.window.id == "right"


def test_leaving_screens_resets():
    p = make()
    p.update(0.0, (1440, 540), WINDOWS, MONITORS)
    p.update(0.2, (5000, 5000), WINDOWS, MONITORS)
    assert p.update(0.45, (1440, 540), WINDOWS, MONITORS) is None


def test_typing_lock():
    p = make()
    assert run_steps(p, (1440, 540), 0.0, 1.0, last_key=0.5) is None
    assert p.blocked_by == "typing"
    assert run_steps(p, (1440, 540), 1.05, 1.6, last_key=0.5) is not None


def test_mouse_lock():
    p = make()
    assert run_steps(p, (1440, 540), 0.0, 0.6, last_mouse=0.4) is None
    assert p.blocked_by == "mouse"


def test_cooldown_between_switches():
    p = make()
    windows = WINDOWS
    d1 = run_steps(p, (1440, 540), 0.0, 0.5, windows=windows)
    assert d1 is not None
    windows = [Window(**{**w.__dict__, "focused": w.id == "right"}) for w in WINDOWS]
    p.update(0.55, (480, 540), windows, MONITORS)
    assert p.update(1.0, (480, 540), windows, MONITORS) is None  # dwell met, but within cooldown
    assert p.blocked_by == "cooldown"
    assert p.update(1.2, (480, 540), windows, MONITORS) is not None


def test_small_windows_fall_back_to_monitor():
    # 640px-wide laptop windows with 400px error: too small to pick, so focus the monitor.
    p = FocusPolicy(CFG, {"big": 60.0, "small": 400.0})
    res = p.resolve((2900, 400), WINDOWS, MONITORS)
    assert res.kind == "monitor"
    assert res.window.id == "lapA"  # lowest z on that monitor = most recently used
    d = run_steps(p, (2900, 400), 0.0, 0.5)
    assert d is not None and d.reason == "monitor" and d.window.id == "lapA"


def test_small_windows_ok_with_good_accuracy():
    p = FocusPolicy(CFG, {"big": 60.0, "small": 60.0})
    assert p.resolve((2900, 400), WINDOWS, MONITORS).window.id == "lapB"


def test_monitor_fallback_noop_when_monitor_already_focused():
    windows = [Window(**{**w.__dict__, "focused": w.id == "lapB"}) for w in WINDOWS]
    p = FocusPolicy(CFG, {"big": 60.0, "small": 400.0})
    assert run_steps(p, (2100, 400), 0.0, 1.0, windows=windows) is None


def test_floating_window_on_top_wins():
    floating = Window("float", "float", "float", Rect(1200, 300, 500, 400), "big", z=-1, floating=True)
    p = make()
    assert p.resolve((1450, 500), WINDOWS + [floating], MONITORS).window.id == "float"


def test_none_point():
    p = make()
    assert p.update(0.0, None, WINDOWS, MONITORS, last_key=-math.inf) is None
    assert p.last_resolution.kind == "none"
