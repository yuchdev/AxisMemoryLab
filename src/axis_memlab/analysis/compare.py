"""Controlled comparison of post-warm-up growth between a baseline and a candidate run."""

from __future__ import annotations

from typing import Any

from axis_memlab.analysis.load import LoadedRun
from axis_memlab.analysis.phase import segment_run
from axis_memlab.analysis.settings import AnalysisSettings
from axis_memlab.analysis.trend import TrendStats, extract_series, piecewise

# Fields that must match for a pairing to count as controlled (docs/07-offline-analysis.md).
CONTROLLED_FIELDS = (
    "firmware_version",
    "build_id",
    "camera_model",
    "soc",
    "sdk_generation",
    "libc",
    "workload",
)


def _best_post(
    run: LoadedRun, metric: str, phase: str | None, settings: AnalysisSettings
) -> tuple[int, str, TrendStats] | None:
    """Post-warm-up stats of the segment (optionally one phase) with the most usable samples."""
    best: tuple[int, str, TrendStats] | None = None
    for segment in segment_run(run):
        if phase is not None and segment.phase != phase:
            continue
        series = extract_series(segment, metric)
        if series is None or not series.points:
            continue
        _, post = piecewise(list(series.points), settings.warmup_seconds, settings.minimum_samples)
        if best is None or post.n > best[2].n:
            best = (segment.index, series.unit, post)
    return best


def comparability(baseline: LoadedRun, candidate: LoadedRun) -> list[str]:
    notes = []
    for name in CONTROLLED_FIELDS:
        a, b = baseline.manifest.get(name), candidate.manifest.get(name)
        if a is None or b is None:
            notes.append(f"{name} is not recorded in both manifests; comparability unverified")
        elif a != b:
            notes.append(f"{name} differs between runs ({a!r} vs {b!r}); not a controlled pair")
    return notes


def compare_runs(
    baseline: LoadedRun,
    candidate: LoadedRun,
    settings: AnalysisSettings,
    phase: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (comparison findings, limitations)."""
    limitations = comparability(baseline, candidate)
    limitations.append(
        "One run per side: decisive comparisons need at least two repetitions of each condition."
    )
    limitations.extend(f"{r.run_id}: {p}" for r in (baseline, candidate) for p in r.problems)
    findings: list[dict[str, Any]] = []
    for metric in settings.metrics:
        base = _best_post(baseline, metric, phase, settings)
        cand = _best_post(candidate, metric, phase, settings)
        finding: dict[str, Any] = {
            "type": "comparison",
            "metric": metric,
            "phase": phase,
            "baseline_run_id": baseline.run_id,
            "candidate_run_id": candidate.run_id,
            "baseline": None,
            "candidate": None,
            "slope_delta_per_hour": None,
            "unit": None,
            "status": "compared",
            "reason": None,
        }
        if base is None or cand is None:
            finding["status"] = "not_compared"
            finding["reason"] = (
                "metric absent from "
                + ("baseline" if base is None else "candidate")
                + (" and candidate" if base is None and cand is None else "")
            )
        elif base[1] != cand[1]:
            finding["status"] = "not_compared"
            finding["reason"] = f"units differ ({base[1]!r} vs {cand[1]!r})"
        else:
            finding["unit"] = base[1]
            finding["baseline"] = {"segment": base[0], **base[2].as_dict()}
            finding["candidate"] = {"segment": cand[0], **cand[2].as_dict()}
            if base[2].slope_per_hour is None or cand[2].slope_per_hour is None:
                finding["status"] = "not_compared"
                finding["reason"] = "post-warm-up window has insufficient data on a side"
            else:
                finding["slope_delta_per_hour"] = cand[2].slope_per_hour - base[2].slope_per_hour
        findings.append(finding)
    return findings, limitations
