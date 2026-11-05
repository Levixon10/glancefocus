import numpy as np
import pytest

from glancefocus.gaze.features import FEATURE_NAMES, N_FEATURES
from glancefocus.mapping import GazeMapper


def synthetic(n_targets=18, per_target=15, noise=0.002, seed=1):
    """Fake calibration data: screen point depends (non-linearly) on gaze + head features."""
    rng = np.random.default_rng(seed)
    gh, gv = FEATURE_NAMES.index("gaze_h"), FEATURE_NAMES.index("gaze_v")
    fx, fy = FEATURE_NAMES.index("head_fx"), FEATURE_NAMES.index("head_fy")
    xs, ys, gs = [], [], []
    for g in range(n_targets):
        target = rng.uniform([0, 0], [3200, 1080])
        for _ in range(per_target):
            f = rng.normal(0, 0.05, N_FEATURES)
            head = rng.normal(0, 0.03, 2)
            f[fx], f[fy] = head
            # Invert a known model: target = 9000*gaze + 6000*head + 3000*gaze^2 + offset
            u = (target - np.array([1600, 540]) - 6000 * head) / 9000
            f[gh], f[gv] = u - 3000 * u**2 / 9000
            f[gh] += rng.normal(0, noise)
            f[gv] += rng.normal(0, noise)
            xs.append(f)
            ys.append(target)
            gs.append(g)
    return np.array(xs), np.array(ys), np.array(gs)


def test_fit_recovers_mapping():
    x, y, g = synthetic()
    mapper, report = GazeMapper.fit(x, y, g)
    assert report.cv_rmse < 60, report.cv_rmse
    pred = mapper.predict_many(x)
    assert np.sqrt(np.mean(np.sum((pred - y) ** 2, axis=1))) < 40


def test_roundtrip():
    x, y, g = synthetic(n_targets=8)
    mapper, _ = GazeMapper.fit(x, y, g)
    again = GazeMapper.from_dict(mapper.to_dict())
    np.testing.assert_allclose(again.predict_many(x[:5]), mapper.predict_many(x[:5]))
    assert mapper.predict(x[0]) == pytest.approx(tuple(mapper.predict_many(x[:1])[0]))


def test_constant_feature_does_not_crash():
    x, y, g = synthetic(n_targets=6)
    x[:, 3] = 1.0
    mapper, report = GazeMapper.fit(x, y, g)
    assert np.isfinite(report.cv_rmse)


def test_too_little_data():
    x, y, g = synthetic(n_targets=2, per_target=3)
    with pytest.raises(ValueError):
        GazeMapper.fit(x, y, g)
