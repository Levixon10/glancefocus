"""One Euro filter (Casiez et al., CHI 2012): smooth when still, responsive when moving."""

from __future__ import annotations

import math


class OneEuro:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._x: float | None = None
        self._dx = 0.0
        self._t: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float) -> float:
        if self._x is None or self._t is None or t <= self._t:
            self._x, self._t = x, t
            return x
        dt = t - self._t
        self._t = t
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * ((x - self._x) / dt) + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x = a * x + (1 - a) * self._x
        return self._x


class OneEuro2D:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0):
        self.fx = OneEuro(min_cutoff, beta)
        self.fy = OneEuro(min_cutoff, beta)

    def reset(self) -> None:
        self.fx.reset()
        self.fy.reset()

    def __call__(self, p: tuple[float, float], t: float) -> tuple[float, float]:
        return self.fx(p[0], t), self.fy(p[1], t)
