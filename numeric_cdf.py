"""
Ways to turn a forecaster's percentiles into the CDF that Metaculus scores (201 points
for numeric questions, fewer for discrete ones). Used by the numeric backtest, and by
the live bot for whichever method the backtest supports.

- linear: forecasting-tools' default, straight lines between percentiles. Between the
  outermost percentile and the question bound the density drops abruptly, so an outcome
  just outside the stated range scores very badly.
- pchip: a smooth monotone curve through the same points (Fritsch-Carlson PCHIP, as used
  by several top tournament bots), so density tapers into the tails instead.
- widen: stretch every percentile away from the median by a factor before building the CDF.
- aggregation: median (forecasting-tools' default) or mean of the members' CDFs.
"""
from __future__ import annotations

import numpy as np
from forecasting_tools import NumericDistribution, NumericQuestion, Percentile


def _end_slope(h0: float, h1: float, d0: float, d1: float) -> float:
    slope = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if np.sign(slope) != np.sign(d0):
        return 0.0
    if np.sign(d0) != np.sign(d1) and abs(slope) > abs(3 * d0):
        return 3 * d0
    return slope


def pchip(x: np.ndarray, y: np.ndarray, xi: np.ndarray) -> np.ndarray:
    """Monotone piecewise cubic interpolation of (x, y) at xi (x strictly increasing)."""
    x, y, xi = (np.asarray(a, dtype=float) for a in (x, y, xi))
    h = np.diff(x)
    delta = np.diff(y) / h
    n = len(x)
    slopes = np.zeros(n)
    if n == 2:
        slopes[:] = delta[0]
    else:
        for k in range(1, n - 1):
            if delta[k - 1] * delta[k] > 0:
                w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
                slopes[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])
        slopes[0] = _end_slope(h[0], h[1], delta[0], delta[1])
        slopes[-1] = _end_slope(h[-1], h[-2], delta[-1], delta[-2])
    i = np.clip(np.searchsorted(x, xi, side="right") - 1, 0, n - 2)
    t = (xi - x[i]) / h[i]
    return (
        (2 * t**3 - 3 * t**2 + 1) * y[i]
        + (t**3 - 2 * t**2 + t) * h[i] * slopes[i]
        + (-2 * t**3 + 3 * t**2) * y[i + 1]
        + (t**3 - t**2) * h[i] * slopes[i + 1]
    )


class PchipDistribution(NumericDistribution):
    """NumericDistribution with a smooth monotone curve through the percentiles instead of straight lines."""

    def _get_cdf_at(self, cdf_location: float) -> float:
        points = self._add_explicit_upper_lower_bound_percentiles(self.declared_percentiles)
        xs = np.array([self._nominal_location_to_cdf_location(p.value) for p in points])
        ys = np.array([p.percentile for p in points])
        keep = np.concatenate([[True], np.diff(xs) > 1e-12])  # drop repeated locations
        xs, ys = xs[keep], ys[keep]
        if not xs[0] - 1e-10 <= cdf_location <= xs[-1] + 1e-10:
            raise ValueError(f"CDF location {cdf_location} is outside the percentiles")
        value = float(pchip(xs, ys, np.array([min(max(cdf_location, xs[0]), xs[-1])]))[0])
        return min(max(value, 0.0), 1.0)


def widen(percentiles: list[Percentile], factor: float) -> list[Percentile]:
    """Stretch percentile values away from the median by factor (1 = unchanged)."""
    if factor == 1:
        return percentiles
    pts = sorted(percentiles, key=lambda p: p.percentile)
    median = float(np.interp(0.5, [p.percentile for p in pts], [p.value for p in pts]))
    return [Percentile(percentile=p.percentile, value=median + factor * (p.value - median)) for p in pts]


def member_cdf(
    percentiles: list[Percentile], question: NumericQuestion, method: str = "linear", widen_by: float = 1.0
) -> np.ndarray:
    """One forecaster's CDF heights at the question's CDF points."""
    base = NumericDistribution.from_question(widen(percentiles, widen_by), question)
    cls = PchipDistribution if method == "pchip" else NumericDistribution
    dist = cls(**base.model_dump())
    return np.array([p.percentile for p in dist.get_cdf()])


def aggregate(cdfs: list[np.ndarray], question: NumericQuestion, how: str = "median") -> NumericDistribution:
    """Combine members' CDFs pointwise and return the distribution that would be submitted."""
    stacked = np.vstack(cdfs)
    heights = np.median(stacked, axis=0) if how == "median" else stacked.mean(axis=0)
    points = [Percentile(percentile=float(h), value=v) for h, v in zip(heights, x_axis(question))]
    return NumericDistribution.from_question(points, question)


def x_axis(question: NumericQuestion) -> list[float]:
    """The question values at which Metaculus evaluates the CDF."""
    span = question.upper_bound - question.lower_bound
    probe = NumericDistribution.from_question(
        [
            Percentile(percentile=0.4, value=question.lower_bound + span / 3),
            Percentile(percentile=0.6, value=question.lower_bound + 2 * span / 3),
        ],
        question,
    )
    return [p.value for p in probe.get_cdf()]
