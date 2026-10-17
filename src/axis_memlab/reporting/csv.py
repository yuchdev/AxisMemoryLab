"""Unit-labelled CSV export of trend findings, safe to open in spreadsheet software."""

from __future__ import annotations

import csv as _csv
import io
from typing import Any

from axis_memlab.reporting import by_type

HEADER = [
    "run_id", "segment", "phase", "metric", "window", "direction", "samples", "span_seconds",
    "start_value", "end_value", "min_value", "max_value", "value_unit", "slope_per_hour",
    "slope_unit",
]  # fmt: skip


def _safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


def render_csv(doc: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = _csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    for t in by_type(doc, "trend"):
        for window in ("warmup", "post_warmup"):
            s = t[window]
            if s is None:
                continue
            writer.writerow(
                [
                    _safe(v)
                    for v in (
                        t["run_id"], t["segment"], t["phase"], t["metric"], window, s["direction"],
                        s["n"], s["span_seconds"], s["start"], s["end"], s["min"], s["max"],
                        t["unit"], s["slope_per_hour"], f"{t['unit']} per hour",
                    )
                ]
            )  # fmt: skip
    return buffer.getvalue()
