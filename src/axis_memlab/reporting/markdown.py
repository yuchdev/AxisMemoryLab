"""Evidence-linked Markdown report; every row cites run, segment, and sample counts."""

from __future__ import annotations

from typing import Any

from axis_memlab.reporting import by_type


def _cell(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _window(stats: dict[str, Any] | None) -> list[str]:
    if stats is None:
        return ["none", "0", "n/a", "n/a", "n/a", "n/a"]
    return [
        _cell(stats["direction"]),
        _cell(stats["n"]),
        _cell(stats["span_seconds"]),
        _cell(stats["start"]),
        _cell(stats["end"]),
        _cell(stats["slope_per_hour"]),
    ]


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return [*lines, ""]


def render_markdown(doc: dict[str, Any]) -> str:
    out = ["# Memory evidence report", ""]
    out += [f"Generated: {doc['generated_at']}", ""]
    out += ["Runs: " + ", ".join(f"`{r}`" for r in doc["run_references"]), ""]
    out += ["## Limitations", ""] + [f"- {item}" for item in doc["limitations"]] + [""]

    segments = by_type(doc, "segment")
    if segments:
        out += ["## Segments", ""]
        out += _table(
            ["run", "segment", "phase", "starts at", "samples", "clock"],
            [
                [
                    _cell(s["run_id"]),
                    _cell(s["segment"]),
                    _cell(s["phase"]),
                    _cell(s["start_reason"]),
                    _cell(s["samples"]),
                    _cell(s["time_basis"]),
                ]
                for s in segments
            ],
        )
    trends = by_type(doc, "trend")
    if trends:
        out += [
            "## Trends",
            "",
            "Slopes are per hour in the metric's unit. Values are bare numbers.",
            "",
        ]
        rows = []
        for t in trends:
            for name in ("warmup", "post_warmup"):
                rows.append(
                    [_cell(t["run_id"]), _cell(t["segment"]), _cell(t["metric"]), _cell(t["unit"]),
                     name, *_window(t[name])]
                )  # fmt: skip
        out += _table(
            ["run", "seg", "metric", "unit", "window", "direction", "n", "span s", "start", "end",
             "slope/h"],
            rows,
        )  # fmt: skip
        for t in trends:
            for norm in t["normalized"]:
                out.append(
                    f"- {t['metric']} (segment {t['segment']}): {_cell(norm['value'])} "
                    f"{norm['unit']}"
                )
        out.append("")
    hyps = by_type(doc, "hypothesis")
    if hyps:
        out += ["## Hypotheses to test", ""]
        for h in hyps:
            where = f" (segment {h['segment']})" if "segment" in h else ""
            out.append(f"### {h['id']}: {h['hypothesis']}{where}")
            out.append("")
            out.append(f"- Status: {h['status']}")
            if h["status"] == "observed":
                out.append(f"- {h['caveat']}")
                out += [
                    f"- Evidence: {e['metric']} {e['direction']} after warm-up "
                    f"(n={e['n']}, slope/h={_cell(e['slope_per_hour'])})"
                    for e in h["evidence"]
                ]
                out.append("- Alternatives: " + "; ".join(h["alternatives"]))
            else:
                out.append(f"- Reason: {h['reason']}")
            out += [f"- Next comparison: {h['next_comparison']}", ""]
    comps = by_type(doc, "comparison")
    if comps:
        out += ["## Comparisons", ""]
        out += _table(
            [
                "metric",
                "unit",
                "phase",
                "status",
                "baseline slope/h",
                "candidate slope/h",
                "delta/h",
            ],
            [
                [
                    _cell(c["metric"]),
                    _cell(c["unit"]),
                    _cell(c["phase"]),
                    _cell(c["status"] if not c["reason"] else f"{c['status']}: {c['reason']}"),
                    _cell((c["baseline"] or {}).get("slope_per_hour")),
                    _cell((c["candidate"] or {}).get("slope_per_hour")),
                    _cell(c["slope_delta_per_hour"]),
                ]
                for c in comps
            ],
        )
    for summary in by_type(doc, "allocation_summary"):
        cal = summary["calibration"]
        out += ["## Allocation summary", ""]
        out.append(
            f"- Session {summary['session']}: {summary['samples']} samples at a mean interval of "
            f"{summary['sample_interval_bytes']} bytes ({summary['unwinder']}, {summary['arch']})"
        )
        out.append(
            f"- Estimated live: {_cell(summary['estimated_live_bytes'])} bytes from "
            f"{summary['sampled_live']} sampled live allocations"
        )
        out.append(
            f"- Estimated cumulative (all ever allocated, NOT live): "
            f"{_cell(summary['estimated_cumulative_bytes'])} bytes"
        )
        if cal["exact_requested_bytes"] is not None:
            out.append(
                f"- Exact cumulative requested: {_cell(cal['exact_requested_bytes'])} bytes "
                f"(estimate / exact = {_cell(cal['ratio'])})"
            )
        out.append(f"- Unresolved frames: {summary['unresolved_frames']}")
        out.append("")
    sites = by_type(doc, "allocation_site")
    if sites:
        out += [f"## Allocation sites (ranked by {sites[0]['ranked_by']})", ""]
        rows = []
        for site in sites:
            top = " <- ".join(f["label"] for f in site["frames"][:4]) or "<no stack>"
            rows.append(
                [
                    _cell(site["rank"]),
                    _cell(site["estimated_live_bytes"]),
                    f"{site['sampled_live']} ({site['confidence_live']})",
                    _cell(site["estimated_cumulative_bytes"]),
                    f"{site['sampled_allocs']} ({site['confidence_cumulative']})",
                    _cell(top),
                ]
            )
        out += _table(
            [
                "rank",
                "live est. bytes",
                "live samples",
                "cumulative est. bytes (not live)",
                "samples",
                "call site (innermost first)",
            ],
            rows,
        )
    cors = by_type(doc, "correlation")
    if cors:
        out += ["## Correlations", ""]
        out += _table(
            ["run", "seg", "a", "b", "intervals", "rho", "note"],
            [
                [
                    _cell(c["run_id"]),
                    _cell(c["segment"]),
                    _cell(c["metric_a"]),
                    _cell(c["metric_b"]),
                    _cell(c["n_intervals"]),
                    _cell(c["spearman_rho"]),
                    _cell(c["reason"] or c["interpretation"]),
                ]
                for c in cors
            ],
        )
    return "\n".join(out).rstrip() + "\n"
