"""``/proc/pressure/memory`` (PSI): stall time, not a size; only when the kernel enables it."""

from __future__ import annotations

import re

from axis_memlab.records import Metric
from axis_memlab.sources.common import all_unavailable, unavailable, value

SOURCE = "procfs:/proc/pressure/memory"

_LINE = re.compile(
    r"^(some|full) avg10=(\d+(?:\.\d+)?) avg60=(\d+(?:\.\d+)?) avg300=(\d+(?:\.\d+)?) total=(\d+)$"
)


def metric_names() -> list[str]:
    names = []
    for kind in ("some", "full"):
        names += [
            f"system.psi.memory_{kind}_avg10_percent",
            f"system.psi.memory_{kind}_avg60_percent",
            f"system.psi.memory_{kind}_avg300_percent",
            f"system.psi.memory_{kind}_total_us",
        ]
    return names


def parse(text: str) -> dict[str, Metric]:
    out: dict[str, Metric] = {}
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if not match:
            continue
        kind = match.group(1)
        for window, group in (("avg10", 2), ("avg60", 3), ("avg300", 4)):
            out[f"system.psi.memory_{kind}_{window}_percent"] = value(
                float(match.group(group)), "percent", SOURCE
            )
        out[f"system.psi.memory_{kind}_total_us"] = value(
            int(match.group(5)), "microseconds", SOURCE
        )
    if not out:
        return all_unavailable(metric_names(), "parse_error", "no PSI lines recognized")
    for name in metric_names():
        # Some kernels expose only "some" for memory-less configurations; say so per metric.
        out.setdefault(name, unavailable("unsupported", "line not present in PSI output"))
    return out
