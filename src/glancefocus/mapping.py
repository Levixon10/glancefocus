"""Calibration model: gaze feature vector → point on the desktop.

A ridge regression over standardised features plus pairwise products of the most
informative ones. It is small (fits in milliseconds, no scikit-learn needed), and
the regularisation strength is chosen by cross-validation that holds out whole
calibration *targets*, which gives an honest estimate of on-screen error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from glancefocus.gaze.features import CORE_FEATURES, FEATURE_NAMES

DEFAULT_LAMBDAS = (1e-3, 1e-2, 0.1, 1.0, 10.0, 100.0, 1000.0)


def _core_index(feature_names) -> list[int]:
    return [list(feature_names).index(name) for name in CORE_FEATURES if name in feature_names]


def expand(z: np.ndarray, core: list[int]) -> np.ndarray:
    """[1, z, products of core features] for each row of standardised features z."""
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


@dataclass
class FitReport:
    lam: float
    cv_rmse: float  # root-mean-square on-screen error of held-out targets, in desktop px
    cv_errors: np.ndarray = field(repr=False)  # per-sample held-out error, aligned with the input


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
        return cls(mean, std, coef, lam, tuple(feature_names)), FitReport(lam, rmse, errors)

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
            "std": self.std.tolist(),
            "coef": self.coef.tolist(),
            "lam": self.lam,
            "feature_names": list(self.feature_names),
        }

    @classmethod
    def from_dict(cls, d: dict) -> GazeMapper:
        return cls(
            np.array(d["mean"]), np.array(d["std"]), np.array(d["coef"]), float(d["lam"]),
            tuple(d["feature_names"]),
        )


def _standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-9] = 1.0
    return mean, std
