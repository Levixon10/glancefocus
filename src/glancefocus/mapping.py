"""Calibration model: gaze feature vector → point on the desktop.

A ridge regression over standardised features plus pairwise products of the most
informative ones. It is small (fits in milliseconds, no scikit-learn needed), and
the regularisation strength is chosen by cross-validation that holds out whole
calibration *targets*, which gives an honest estimate of on-screen error.

Robustness matters more than flexibility here. Webcam features are noisy, some
(blendshapes) are nearly constant for long stretches, and a single bad landmark
frame can be far off. So:

* standardised features are clipped to ±Z_CLIP, so a value far outside what was
  seen in training cannot blow up the squared terms;
* frames that disagree with the other frames recorded for the same dot are
  dropped before fitting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from glancefocus.gaze.features import CORE_FEATURES, FEATURE_NAMES

DEFAULT_LAMBDAS = (1e-2, 0.1, 1.0, 10.0, 100.0, 1e3, 1e4)
Z_CLIP = 4.0
# Only reject truly broken frames: on real webcam data, aggressive rejection made fits worse.
OUTLIER_Z = 30.0


def _core_index(feature_names) -> list[int]:
    return [list(feature_names).index(name) for name in CORE_FEATURES if name in feature_names]


def expand(z: np.ndarray, core: list[int]) -> np.ndarray:
    """[1, z, products of core features] for each row of standardised features z."""
    z = np.clip(z, -Z_CLIP, Z_CLIP)
    n = z.shape[0]
    c = z[:, core]
    iu = np.triu_indices(len(core))
    quad = (c[:, :, None] * c[:, None, :])[:, iu[0], iu[1]]
    return np.hstack([np.ones((n, 1)), z, quad])


def _ridge(phi: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    reg = lam * np.eye(phi.shape[1])
    reg[0, 0] = 0.0  # don't shrink the intercept
    return np.linalg.solve(phi.T @ phi + reg, phi.T @ y)


def _folds(groups: np.ndarray, k: int, seed: int = 0) -> list[np.ndarray]:
    unique = np.unique(groups)
    rng = np.random.default_rng(seed)
    rng.shuffle(unique)
    k = max(2, min(k, len(unique)))
    return [np.isin(groups, unique[i::k]) for i in range(k)]


def _standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    # Features that (almost) never vary carry no information; neutralise them.
    std[std < 1e-6] = np.inf
    return mean, std


def inlier_mask(x: np.ndarray, groups: np.ndarray, min_keep: int = 3) -> np.ndarray:
    """Drop frames that disagree with the other frames recorded for the same dot.

    For each feature, the typical within-dot spread is the median (over dots) of the
    per-dot MAD. A frame is an outlier if any feature is more than OUTLIER_Z typical
    spreads from its dot's median.
    """
    keep = np.ones(len(x), dtype=bool)
    unique = np.unique(groups)
    medians = {g: np.median(x[groups == g], axis=0) for g in unique}
    mads = np.array([np.median(np.abs(x[groups == g] - medians[g]), axis=0) for g in unique])
    scale = 1.4826 * np.median(mads, axis=0)
    scale[scale < 1e-9] = np.inf  # constant within dots: can't judge, don't reject on it
    for g in unique:
        idx = np.flatnonzero(groups == g)
        dev = np.max(np.abs(x[idx] - medians[g]) / scale, axis=1)
        bad = dev > OUTLIER_Z
        if (~bad).sum() < min_keep:  # never drop a whole dot; keep its most typical frames
            bad = np.ones(len(idx), dtype=bool)
            bad[np.argsort(dev)[:min_keep]] = False
        keep[idx[bad]] = False
    return keep


@dataclass
class FitReport:
    lam: float
    cv_rmse: float  # root-mean-square on-screen error of held-out targets, in desktop px
    inliers: np.ndarray = field(repr=False)  # bool mask over the input rows used for fitting
    cv_errors: np.ndarray = field(repr=False)  # held-out error for each inlier row


@dataclass
class GazeMapper:
    mean: np.ndarray
    std: np.ndarray
    coef: np.ndarray  # (n_terms, 2)
    lam: float
    feature_names: tuple[str, ...] = FEATURE_NAMES

    # ---- fitting ---------------------------------------------------------
    @classmethod
    def fit(
        cls,
        x: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray,
        lambdas=DEFAULT_LAMBDAS,
        folds: int = 10,
        feature_names: tuple[str, ...] = FEATURE_NAMES,
    ) -> tuple[GazeMapper, FitReport]:
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        groups = np.asarray(groups)
        if len(x) < 10 or len(np.unique(groups)) < 3:
            raise ValueError("not enough calibration data (need at least 3 targets and 10 samples)")
        inliers = inlier_mask(x, groups)
        x, y, groups = x[inliers], y[inliers], groups[inliers]
        core = _core_index(feature_names)
        masks = _folds(groups, folds)

        best: tuple[float, float, np.ndarray] | None = None
        for lam in lambdas:
            errors = np.zeros(len(x))
            for test in masks:
                train = ~test
                mean, std = _standardise(x[train])
                coef = _ridge(expand((x[train] - mean) / std, core), y[train], lam)
                pred = expand((x[test] - mean) / std, core) @ coef
                errors[test] = np.linalg.norm(pred - y[test], axis=1)
            rmse = float(np.sqrt(np.mean(errors**2)))
            if best is None or rmse < best[1]:
                best = (lam, rmse, errors)

        lam, rmse, errors = best
        mean, std = _standardise(x)
        coef = _ridge(expand((x - mean) / std, core), y, lam)
        return cls(mean, std, coef, lam, tuple(feature_names)), FitReport(lam, rmse, inliers, errors)

    # ---- prediction ------------------------------------------------------
    def predict_many(self, x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(np.asarray(x, float))
        return expand((x - self.mean) / self.std, _core_index(self.feature_names)) @ self.coef

    def predict(self, features: np.ndarray) -> tuple[float, float]:
        p = self.predict_many(features)[0]
        return float(p[0]), float(p[1])

    # ---- persistence -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "mean": self.mean.tolist(),
            # JSON has no infinity; 0 marks a neutralised feature.
            "std": np.where(np.isinf(self.std), 0.0, self.std).tolist(),
            "coef": self.coef.tolist(),
            "lam": self.lam,
            "feature_names": list(self.feature_names),
        }

    @classmethod
    def from_dict(cls, d: dict) -> GazeMapper:
        std = np.array(d["std"], float)
        std[std == 0] = np.inf
        return cls(np.array(d["mean"]), std, np.array(d["coef"]), float(d["lam"]), tuple(d["feature_names"]))
