"""Robust piecewise trends: Theil-Sen slope, spread, and a deliberately cautious direction."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from axis_memlab.analysis.load import Sample
from axis_memlab.analysis.phase import Segment

Point = tuple[float, float]  # (seconds since segment start, value)

_MAX_FIT_POINTS = 400  # pairwise slopes are O(n^2); thin deterministically beyond this
_SIGMA_FACTOR = 3.0
_MIN_RELATIVE_RISE = 0.02


@dataclass(frozen=True)
class TrendStats:
    n: int
    span_s: float | None
    start: float | None
    end: float | None
    minimum: float | None
    maximum: float | None
    slope_per_second: float | None
    slope_per_hour: float | None
    direction: str  # rising | falling | flat | insufficient_data
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "span_seconds": self.span_s,
            "start": self.start,
            "end": self.end,
            "min": self.minimum,
            "max": self.maximum,
            "slope_per_hour": self.slope_per_hour,
            "direction": self.direction,
            "reason": self.reason,
        }


def _insufficient(n: int, reason: str) -> TrendStats:
    return TrendStats(n, None, None, None, None, None, None, None, "insufficient_data", reason)


@dataclass(frozen=True)
class Series:
    metric: str
    unit: str
    points: tuple[Point, ...]
    unavailable: int
    non_numeric: int


def extract_series(segment: Segment, metric: str) -> Series | None:
    """Numeric points of ``metric`` in a segment; ``None`` if absent or units conflict."""
    points: list[Point] = []
    units: set[str] = set()
    unavailable = non_numeric = 0
    for sample in segment.samples:
        found = sample.metrics.get(metric)
        if found is None:
            continue
        if not found.available:
            unavailable += 1
        elif isinstance(found.value, bool) or not isinstance(found.value, int | float):
            non_numeric += 1
        else:
            points.append((segment.t_seconds(sample), float(found.value)))
            units.add(found.unit or "")
    if not points and not unavailable and not non_numeric:
        return None
    if len(units) > 1:
        return None
    return Series(metric, next(iter(units), ""), tuple(points), unavailable, non_numeric)


def paired_values(segment: Segment, a: str, b: str) -> list[tuple[Sample, float, float]]:
    """Samples where both metrics are numeric and available."""
    pairs = []
    for sample in segment.samples:
        ma, mb = sample.metrics.get(a), sample.metrics.get(b)
        if ma is None or mb is None or not ma.available or not mb.available:
            continue
        va, vb = ma.value, mb.value
        if isinstance(va, bool) or isinstance(vb, bool):
            continue
        if isinstance(va, int | float) and isinstance(vb, int | float):
            pairs.append((sample, float(va), float(vb)))
    return pairs


def _thin(points: list[Point]) -> list[Point]:
    if len(points) <= _MAX_FIT_POINTS:
        return points
    step = (len(points) - 1) / (_MAX_FIT_POINTS - 1)
    return [points[round(i * step)] for i in range(_MAX_FIT_POINTS)]


def summarize(points: list[Point], minimum_samples: int) -> TrendStats:
    """Describe a window. Direction is ``flat`` unless the fitted rise clearly exceeds noise."""
    n = len(points)
    needed = max(2, minimum_samples)
    if n < needed:
        return _insufficient(n, f"{n} samples is fewer than the required {needed}")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span = xs[-1] - xs[0]
    if span <= 0:
        return _insufficient(n, "samples have no time span")
    fit = _thin(points)
    slopes = [
        (fit[j][1] - fit[i][1]) / (fit[j][0] - fit[i][0])
        for i in range(len(fit))
        for j in range(i + 1, len(fit))
        if fit[j][0] > fit[i][0]
    ]
    slope = statistics.median(slopes)
    intercept = statistics.median(y - slope * x for x, y in fit)
    sigma = 1.4826 * statistics.median(abs(y - (slope * x + intercept)) for x, y in fit)
    tolerance = _SIGMA_FACTOR * sigma + _MIN_RELATIVE_RISE * abs(statistics.median(ys))
    rise = slope * span
    direction = "rising" if rise > tolerance else "falling" if -rise > tolerance else "flat"
    return TrendStats(n, span, ys[0], ys[-1], min(ys), max(ys), slope, slope * 3600.0, direction)


def piecewise(
    points: list[Point], warmup_seconds: float, minimum_samples: int
) -> tuple[TrendStats | None, TrendStats]:
    """Return (warm-up window stats or None, post-warm-up stats) split at the warm-up time."""
    warm = [p for p in points if p[0] < warmup_seconds]
    post = [p for p in points if p[0] >= warmup_seconds]
    warm_stats = summarize(warm, minimum_samples) if warm else None
    if not post:
        return warm_stats, _insufficient(0, "segment is not longer than the warm-up window")
    rebased = [(x - post[0][0], y) for x, y in post]
    return warm_stats, summarize(rebased, minimum_samples)


def growth_per_1000(
    metric: TrendStats, counter: TrendStats, metric_unit: str, counter_name: str
) -> dict[str, Any] | None:
    """Metric growth per 1,000 counter units over the same window, if both trends are usable."""
    if (
        metric.slope_per_second is None
        or counter.slope_per_second is None
        or counter.direction != "rising"
    ):
        return None
    return {
        "per": counter_name,
        "value": metric.slope_per_second / counter.slope_per_second * 1000.0,
        "unit": f"{metric_unit} per 1000 {counter_name}",
    }
