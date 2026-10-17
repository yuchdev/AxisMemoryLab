"""Aggregate sampled allocations by call site and assemble a ``report-v1`` document.

Two quantities are kept strictly apart and never relabelled: *cumulative* volume (everything that
was allocated at a site) and *live* volume (sampled allocations whose free was not recorded). Both
are statistical estimates: each sample stands for ``weight_count`` allocations of its size, so sums
of ``size * weight_count`` are unbiased. Every site carries the number of samples behind it, a
rough relative error, and a confidence tier, because a site with three samples is a lead, not a
measurement.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from axis_memlab.symbolization.resolve import Frame, Resolver
from axis_memlab.symbolization.stackmap import AllocSample, Session

COVERAGE_LIMITATIONS = (
    "Covers only C++ operator new / new[] linked through the hook library and any manual call "
    "sites. malloc, mmap, SDK or hardware buffers, and allocations made before the sampler "
    "started are not seen.",
    "Estimates come from sampling by bytes and carry sampling error; see each site's sample "
    "counts and confidence. A site's live estimate counts only sampled allocations whose free "
    "was not recorded.",
    "Cumulative volume is the total ever allocated at a site; it is not live memory and must "
    "not be read as such.",
    "A call stack shows where memory was requested, not who is responsible for keeping it.",
)


@dataclass
class Site:
    frames: tuple[Frame, ...]
    sampled_allocs: int = 0
    sampled_live: int = 0
    cumulative_count: float = 0.0
    cumulative_bytes: float = 0.0
    live_count: float = 0.0
    live_bytes: float = 0.0
    largest: int = 0
    kinds: Counter[str] = field(default_factory=Counter)
    threads: set[int] = field(default_factory=set)

    @property
    def label_key(self) -> tuple[str, ...]:
        return tuple(f.label for f in self.frames)


def confidence(samples: int) -> str:
    return "high" if samples >= 30 else "medium" if samples >= 5 else "low"


def relative_error(samples: int) -> float | None:
    """Approximate relative standard error of a sum over ``samples`` equal-weight samples."""
    return None if samples < 1 else 1.0 / math.sqrt(samples)


def _frames_for(
    sample: AllocSample, expanded: dict[int, list[Frame]], skip_top: int, max_depth: int | None
) -> tuple[Frame, ...]:
    frames: list[Frame] = []
    for pc in sample.stack[skip_top:]:
        frames.extend(expanded[pc])
    return tuple(frames[:max_depth] if max_depth else frames)


def aggregate(
    session: Session,
    resolver: Resolver,
    *,
    skip_top: int = 0,
    max_depth: int | None = None,
) -> list[Site]:
    pcs = [pc for s in session.allocs for pc in s.stack[skip_top:]]
    expanded = resolver.resolve_all(session, pcs)
    sites: dict[tuple[str, ...], Site] = {}
    for sample in session.allocs:
        frames = _frames_for(sample, expanded, skip_top, max_depth)
        key = tuple(f.label for f in frames) or ("<no stack>",)
        site = sites.get(key)
        if site is None:
            site = sites[key] = Site(frames=frames)
        weight_bytes = sample.weight_count * sample.size
        site.sampled_allocs += 1
        site.cumulative_count += sample.weight_count
        site.cumulative_bytes += weight_bytes
        site.largest = max(site.largest, sample.size)
        site.kinds[sample.kind] += 1
        site.threads.add(sample.thread)
        if sample.id not in session.freed:
            site.sampled_live += 1
            site.live_count += sample.weight_count
            site.live_bytes += weight_bytes
    return list(sites.values())


def _summary_finding(
    session: Session, sites: list[Site], resolver: Resolver
) -> tuple[dict[str, Any], list[str]]:
    limitations = list(COVERAGE_LIMITATIONS)
    summary = session.summary
    estimated_cumulative = sum(s.cumulative_bytes for s in sites)
    estimated_live = sum(s.live_bytes for s in sites)
    calibration: dict[str, Any] = {
        "estimated_cumulative_bytes": estimated_cumulative,
        "exact_requested_bytes": None,
        "ratio": None,
    }
    finding: dict[str, Any] = {
        "type": "allocation_summary",
        "session": session.index,
        "sample_interval_bytes": session.interval,
        "arch": session.header.get("arch"),
        "unwinder": session.header.get("unwinder"),
        "samples": len(session.allocs),
        "sampled_live": sum(s.sampled_live for s in sites),
        "estimated_live_bytes": estimated_live,
        "estimated_cumulative_bytes": estimated_cumulative,
        "closing_summary_present": session.summary_final,
        "counters": summary,
        "calibration": calibration,
        "unresolved_frames": 0,
    }
    if summary is None:
        limitations.append(
            "No summary record: exact totals, drop counters, and calibration are unavailable."
        )
    else:
        exact = summary["alloc_request_bytes"]
        calibration["exact_requested_bytes"] = exact
        if exact > 0:
            ratio = estimated_cumulative / exact
            calibration["ratio"] = ratio
            if abs(ratio - 1.0) > 0.25:
                limitations.append(
                    f"The cumulative estimate is {ratio:.2f}x the exact requested volume: "
                    "sampling is too sparse for these sizes, or samples were dropped. Treat "
                    "per-site numbers as rough."
                )
        if not session.summary_final:
            limitations.append(
                "The file has no closing summary (the process may have exited without stopping "
                "the sampler); counters are from the last periodic summary and some records "
                "may be missing."
            )
        if summary["dropped_free_events"] > 0:
            limitations.append(
                f"{summary['dropped_free_events']} free event(s) were lost; live estimates may "
                "overstate memory that was actually released."
            )
        lost = summary["dropped_ring_full"] + summary["dropped_table_full"]
        if lost > 0:
            limitations.append(
                f"{lost} sample(s) were not recorded (full buffer or table); cumulative "
                "estimates are low and some sites may be missing."
            )
        if summary["dropped_output_cap"] > 0:
            limitations.append(
                f"The output size cap was reached; {summary['dropped_output_cap']} record(s) "
                "were not written."
            )
        if summary["stack_failures"] > 0:
            limitations.append(
                f"{summary['stack_failures']} sample(s) have no stack (no unwinder or stack "
                "bounds unavailable); they are grouped as '<no stack>'."
            )
    if session.header.get("unwinder") == "caller_only":
        limitations.append("This target records only the call site of operator new (depth 1).")
    if session.unknown_frees:
        limitations.append(
            f"{session.unknown_frees} free record(s) refer to unknown samples (a truncated file)."
        )
    if session.problems:
        limitations.append(f"{len(session.problems)} line(s) in the file were skipped as invalid.")
    limitations.extend(resolver.limitations)
    return finding, limitations


def build_report(
    session: Session,
    sites: list[Site],
    resolver: Resolver,
    *,
    top: int,
    sort: str,
    generated_at: datetime,
) -> dict[str, Any]:
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware")
    key = (lambda s: s.live_bytes) if sort == "live" else (lambda s: s.cumulative_bytes)
    ranked = sorted(sites, key=key, reverse=True)
    summary_finding, limitations = _summary_finding(session, sites, resolver)

    status_counts: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []
    for rank, site in enumerate(ranked, start=1):
        for frame in site.frames:
            status_counts[frame.status] += 1
        if rank > top:
            continue
        findings.append(
            {
                "type": "allocation_site",
                "rank": rank,
                "ranked_by": sort,
                "frames": [f.as_dict() for f in site.frames],
                "sampled_allocs": site.sampled_allocs,
                "sampled_live": site.sampled_live,
                "estimated_live_bytes": site.live_bytes,
                "estimated_live_count": site.live_count,
                "estimated_cumulative_bytes": site.cumulative_bytes,
                "estimated_cumulative_count": site.cumulative_count,
                "relative_error_live": relative_error(site.sampled_live),
                "relative_error_cumulative": relative_error(site.sampled_allocs),
                "confidence_live": confidence(site.sampled_live),
                "confidence_cumulative": confidence(site.sampled_allocs),
                "largest_sampled_size": site.largest,
                "kinds": dict(sorted(site.kinds.items())),
                "threads": len(site.threads),
            }
        )
    unresolved = sum(n for status, n in status_counts.items() if status != "resolved")
    summary_finding["unresolved_frames"] = unresolved
    summary_finding["frame_status_counts"] = dict(sorted(status_counts.items()))
    if unresolved:
        bad = ", ".join(f"{k}: {v}" for k, v in sorted(status_counts.items()) if k != "resolved")
        limitations.append(
            f"Some frames could not be resolved ({bad}). Unresolved frames are shown as "
            "module+offset or raw addresses, never guessed."
        )
    if len(ranked) > top:
        limitations.append(f"Only the top {top} of {len(ranked)} sites are listed.")
    run_id = str(session.header.get("run_id", ""))
    return {
        "schema_version": 1,
        "run_references": [run_id],
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "limitations": limitations,
        "findings": [summary_finding, *findings],
    }
