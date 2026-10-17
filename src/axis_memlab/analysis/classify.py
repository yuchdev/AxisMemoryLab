"""Hypotheses to test, taken from ``docs/04-diagnostic-decision-tree.md``.

A finding here is an observation pattern consistent with a hypothesis. It is never a diagnosis;
every finding carries alternatives and the controlled comparison that would test it.
"""

from __future__ import annotations

from typing import Any

from axis_memlab.analysis.phase import Segment
from axis_memlab.analysis.trend import TrendStats

Trends = dict[str, tuple[TrendStats | None, TrendStats]]

AVAILABLE = "system.mem.available_bytes"
PROCESS_METRICS = ("process.pss_bytes", "process.rss_anon_bytes")
CAVEAT = "Observation consistent with the hypothesis; it does not establish a cause."

_NOT_EVALUATED = (
    (
        "H-RECONNECT",
        "Growth per reconnect only (lifecycle cleanup defect)",
        "Needs repeated start/stop cycles and a reconnect counter; compare normalized growth.",
        "Repeat reconnect cycles with a fixed scene and compare growth per cycle.",
    ),
    (
        "H-DETECTION",
        "Growth tracks detections rather than frames (result/event accumulation)",
        "Needs frame and detection counters from in-app instrumentation (milestone 0003).",
        "Disable or cap result publication and compare slopes after warm-up.",
    ),
)


def _post(trends: Trends, metric: str) -> TrendStats | None:
    entry = trends.get(metric)
    if entry is None or entry[1].direction == "insufficient_data":
        return None
    return entry[1]


def _direction(trends: Trends, metric: str) -> str | None:
    stats = _post(trends, metric)
    return stats.direction if stats else None


def _evidence(trends: Trends, metrics: list[str]) -> list[dict[str, Any]]:
    rows = []
    for metric in metrics:
        stats = _post(trends, metric)
        if stats:
            rows.append(
                {
                    "metric": metric,
                    "window": "post_warmup",
                    "direction": stats.direction,
                    "slope_per_hour": stats.slope_per_hour,
                    "n": stats.n,
                    "span_seconds": stats.span_s,
                }
            )
    return rows


def _rising(trends: Trends, names: list[str]) -> list[str]:
    return [m for m in names if _direction(trends, m) == "rising"]


def classify_segment(run_id: str, segment: Segment, trends: Trends) -> list[dict[str, Any]]:
    """Return observed-hypothesis findings for one segment (post-warm-up windows only)."""
    names = sorted(trends)
    queues = [m for m in names if m.startswith("app.") and "queue" in m]
    inflight = [m for m in names if m.startswith("app.") and ("in_flight" in m or "inflight" in m)]
    live = [m for m in names if m.startswith("app.") and "live_bytes" in m]
    growing_process = _rising(trends, list(PROCESS_METRICS))
    findings: list[dict[str, Any]] = []

    def add(fid: str, hypothesis: str, metrics: list[str], alt: list[str], nxt: str) -> None:
        findings.append(
            {
                "type": "hypothesis",
                "id": fid,
                "run_id": run_id,
                "segment": segment.index,
                "phase": segment.phase,
                "status": "observed",
                "hypothesis": hypothesis,
                "evidence": _evidence(trends, metrics),
                "alternatives": alt,
                "next_comparison": nxt,
                "caveat": CAVEAT,
            }
        )

    explained = False
    if growing_process and (rising_q := _rising(trends, queues)):
        explained = True
        add(
            "H-RETENTION",
            "Unbounded application retention",
            growing_process + rising_q,
            ["Allocator caching", "Workload ramp not yet at steady state"],
            "Cap or drain the queues and compare post-warm-up slopes.",
        )
    if growing_process and (rising_f := _rising(trends, inflight)):
        explained = True
        add(
            "H-MISSED-RELEASE",
            "Missed release or reference retention",
            growing_process + rising_f,
            ["Legitimate backlog from a slow consumer", "Counter instrumented at the wrong point"],
            "Compare acquire/release counts against throughput.",
        )
    if _direction(trends, "process.rss_anon_bytes") == "rising" and live:
        if all(_direction(trends, m) == "flat" for m in live):
            explained = True
            add(
                "H-ALLOCATOR",
                "Allocator retention or an untracked library allocation",
                ["process.rss_anon_bytes", *live],
                ["Fragmentation", "Allocations outside the instrumented paths"],
                "Run a development-only allocator experiment on a lab unit.",
            )
    if growing_process and not explained:
        add(
            "H-UNATTRIBUTED",
            "Process memory is growing; available counters do not discriminate between causes",
            growing_process,
            ["Application retention", "Library or driver buffers", "Warm-up longer than declared"],
            "Add in-app counters or extend the run past the declared warm-up window.",
        )
    flat_process = [m for m in PROCESS_METRICS if _direction(trends, m) == "flat"]
    if (
        _direction(trends, AVAILABLE) == "falling"
        and _direction(trends, "process.pss_bytes") == "flat"
        and not growing_process
    ):
        add(
            "H-NOT-IN-PROCESS",
            "System memory use rises while the monitored process is flat "
            "(shared, driver, or other-service memory)",
            [AVAILABLE, *flat_process],
            ["Another process growing", "Page cache or buffers", "A different PID is the app"],
            "Sample other accessible processes and compare against a no-ACAP baseline.",
        )
    for metric in PROCESS_METRICS:
        warm = trends.get(metric, (None, None))[0]
        if warm and warm.direction == "rising" and _direction(trends, metric) == "flat":
            add(
                "H-PLATEAU",
                "Plateau after warm-up (bounded cache or preallocation)",
                [metric],
                ["The run is too short to see later growth"],
                "Verify the bound across representative workloads and longer durations.",
            )
            break
    return findings


def not_evaluated(run_id: str) -> list[dict[str, Any]]:
    """Hypotheses this milestone has no automated rule for, stated so they are not forgotten."""
    return [
        {
            "type": "hypothesis",
            "id": fid,
            "run_id": run_id,
            "status": "not_evaluated",
            "hypothesis": hypothesis,
            "reason": reason,
            "next_comparison": nxt,
        }
        for fid, hypothesis, reason, nxt in _NOT_EVALUATED
    ]
