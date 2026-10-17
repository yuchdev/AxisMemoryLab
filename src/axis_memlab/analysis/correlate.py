"""Rank correlation of interval changes between two metrics; association only."""

from __future__ import annotations

from typing import Any

from axis_memlab.analysis.phase import Segment
from axis_memlab.analysis.trend import paired_values


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rho, or ``None`` when either input is constant."""
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    cross = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    return float(cross / (sxx * syy) ** 0.5)


def correlate_segment(segment: Segment, a: str, b: str, minimum_samples: int) -> dict[str, Any]:
    """Correlate first differences (not levels) so a shared trend does not look like coupling."""
    pairs = paired_values(segment, a, b)
    deltas_a = [pairs[i + 1][1] - pairs[i][1] for i in range(len(pairs) - 1)]
    deltas_b = [pairs[i + 1][2] - pairs[i][2] for i in range(len(pairs) - 1)]
    result: dict[str, Any] = {
        "metric_a": a,
        "metric_b": b,
        "segment": segment.index,
        "phase": segment.phase,
        "n_intervals": len(deltas_a),
        "spearman_rho": None,
        "reason": None,
        "interpretation": "Association between interval changes only; it does not show cause.",
    }
    if len(deltas_a) < max(3, minimum_samples):
        result["reason"] = f"{len(deltas_a)} intervals is too few"
        return result
    rho = spearman(deltas_a, deltas_b)
    if rho is None:
        result["reason"] = "one metric did not change between samples"
    else:
        result["spearman_rho"] = rho
    return result
