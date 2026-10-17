"""Run analysis and ``report-v1`` document assembly."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from axis_memlab.analysis.classify import Trends, classify_segment, not_evaluated
from axis_memlab.analysis.correlate import correlate_segment
from axis_memlab.analysis.load import LoadedRun
from axis_memlab.analysis.phase import Segment, segment_run
from axis_memlab.analysis.settings import AnalysisSettings
from axis_memlab.analysis.trend import extract_series, growth_per_1000, piecewise

BASE_LIMITATIONS = (
    "Slopes are robust fits over sampled data. A regression alone does not establish a leak "
    "or its cause.",
    "System-wide availability and per-process RSS/PSS have different scopes and are not "
    "interchangeable.",
    "Trends are computed per segment; process restarts, boot changes, phase markers, and "
    "configuration changes start a new segment and are never fitted across.",
    "Hypothesis findings are observation patterns to test with a controlled comparison, "
    "not diagnoses.",
)


def _metric_names(segment: Segment, settings: AnalysisSettings) -> list[str]:
    present = {name for s in segment.samples for name in s.metrics}
    return sorted((set(settings.metrics) | {n for n in present if n.startswith("app.")}) & present)


def analyze_run(
    run: LoadedRun,
    settings: AnalysisSettings,
    correlations: tuple[tuple[str, str], ...] = (),
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (findings, limitations) for one run."""
    findings: list[dict[str, Any]] = []
    limitations = [f"{run.run_id}: {problem}" for problem in run.problems]
    if run.errors:
        counts: dict[str, int] = {}
        for item in run.errors:
            key = f"{item.get('source', '?')}:{item.get('reason_code', '?')}"
            counts[key] = counts.get(key, 0) + 1
        summary = ", ".join(f"{k} x{n}" for k, n in sorted(counts.items()))
        limitations.append(
            f"{run.run_id}: the collector recorded read errors ({summary}); affected metrics "
            "are unavailable for those samples"
        )
    segments = segment_run(run)
    if not segments:
        limitations.append(f"{run.run_id}: no usable sample records")
    seen_metrics: set[str] = set()
    counters_used: set[str] = set()

    for segment in segments:
        findings.append(
            {
                "type": "segment",
                "run_id": run.run_id,
                "segment": segment.index,
                "phase": segment.phase,
                "start_reason": segment.start_reason,
                "time_basis": segment.time_basis,
                "samples": len(segment.samples),
                "first_sample_line": segment.samples[0].line,
                "start_utc_ns": segment.samples[0].ts_utc_ns,
                "end_utc_ns": segment.samples[-1].ts_utc_ns,
            }
        )
        trends: Trends = {}
        for metric in _metric_names(segment, settings):
            series = extract_series(segment, metric)
            if series is None:
                limitations.append(
                    f"{run.run_id} segment {segment.index}: {metric} skipped (conflicting units)"
                )
                continue
            seen_metrics.add(metric)
            warm, post = piecewise(
                list(series.points), settings.warmup_seconds, settings.minimum_samples
            )
            trends[metric] = (warm, post)
            normalized: list[dict[str, Any]] = []
            for counter in settings.normalization:
                if counter == "elapsed_seconds" or counter == metric:
                    continue
                counter_series = extract_series(segment, counter)
                if counter_series is None or not counter_series.points:
                    continue
                counters_used.add(counter)
                _, counter_post = piecewise(
                    list(counter_series.points), settings.warmup_seconds, settings.minimum_samples
                )
                growth = growth_per_1000(post, counter_post, series.unit, counter)
                if growth:
                    normalized.append(growth)
            findings.append(
                {
                    "type": "trend",
                    "run_id": run.run_id,
                    "segment": segment.index,
                    "phase": segment.phase,
                    "metric": metric,
                    "unit": series.unit,
                    "time_basis": segment.time_basis,
                    "warmup_seconds": settings.warmup_seconds,
                    "unavailable_samples": series.unavailable,
                    "non_numeric_samples": series.non_numeric,
                    "warmup": warm.as_dict() if warm else None,
                    "post_warmup": post.as_dict(),
                    "normalized": normalized,
                }
            )
        findings.extend(classify_segment(run.run_id, segment, trends))
        for a, b in correlations:
            findings.append(
                {
                    "type": "correlation",
                    "run_id": run.run_id,
                    **correlate_segment(segment, a, b, settings.minimum_samples),
                }
            )

    for requested in settings.metrics:
        if requested not in seen_metrics:
            limitations.append(f"{run.run_id}: requested metric {requested} is absent or unusable")
    for counter in settings.normalization:
        if counter != "elapsed_seconds" and counter not in counters_used:
            limitations.append(
                f"{run.run_id}: normalizer {counter} produced no result "
                "(counter absent, or not rising after warm-up)"
            )
    short = [
        f"{f['segment']}"
        for f in findings
        if f["type"] == "trend" and f["post_warmup"]["direction"] == "insufficient_data"
    ]
    if short:
        limitations.append(
            f"{run.run_id}: post-warm-up window had too little data in segment(s) "
            f"{', '.join(sorted(set(short)))}; no growth statement is made for them"
        )
    findings.extend(not_evaluated(run.run_id))
    return findings, limitations


def build_report(
    runs: list[LoadedRun],
    findings: list[dict[str, Any]],
    limitations: list[str],
    generated_at: datetime,
) -> dict[str, Any]:
    """Assemble a ``report-v1`` document; ``generated_at`` must be timezone-aware."""
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    return {
        "schema_version": 1,
        "run_references": [run.run_id for run in runs],
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "limitations": [*BASE_LIMITATIONS, *limitations],
        "findings": findings,
    }
