import tomllib

from glancefocus.config import Settings, load_settings, render_default_config
from glancefocus.geometry import Monitor, Rect, assign_monitor
from glancefocus.smoothing import OneEuro


def test_default_config_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(render_default_config())
    tomllib.loads(path.read_text())
    assert load_settings(path) == Settings()


def test_config_override_and_unknown_key(tmp_path, caplog):
    path = tmp_path / "config.toml"
    path.write_text('dwell_ms = 800\ncamera = "/dev/video2"\nbogus = 1\n')
    s = load_settings(path)
    assert s.dwell_ms == 800 and s.camera == "/dev/video2"
    assert "bogus" in caplog.text


def test_rect_inset_never_negative():
    r = Rect(0, 0, 10, 10).inset(100)
    assert r.w == 0 and r.h == 0


def test_assign_monitor_by_overlap():
    mons = [Monitor("a", Rect(0, 0, 100, 100)), Monitor("b", Rect(100, 0, 100, 100))]
    assert assign_monitor(Rect(90, 0, 40, 10), mons) == "b"
    assert assign_monitor(Rect(500, 500, 10, 10), mons) is None


def test_one_euro_converges_and_smooths():
    f = OneEuro(min_cutoff=1.0, beta=0.0)
    out = [f(10.0 if i % 2 else -10.0, i * 0.05) for i in range(200)]
    assert max(abs(v) for v in out[100:]) < 10  # jitter attenuated
    g = OneEuro(min_cutoff=1.0)
    for i in range(100):
        v = g(5.0, i * 0.05)
    assert abs(v - 5.0) < 1e-6


def test_samples_roundtrip(tmp_path):
    import numpy as np

    from glancefocus.calibration import CalibrationData, load_samples, save_samples

    data = CalibrationData()
    for i in range(4):
        data.add(np.arange(3.0) + i, (10.0 * i, 5.0), i // 2, "HDMI-A-1" if i < 2 else "eDP-1")
    path = tmp_path / "s.npz"
    save_samples(data, path)
    back = load_samples(path)
    assert back.targets == data.targets and back.groups == data.groups and back.monitors == data.monitors
    np.testing.assert_array_equal(np.array(back.features), np.array(data.features))
