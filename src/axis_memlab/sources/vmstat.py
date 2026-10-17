"""``/proc/vmstat``: kernel memory and reclaim counters. Names vary by kernel."""

from __future__ import annotations

from axis_memlab.records import Metric
from axis_memlab.sources.common import all_unavailable, parse_count, unavailable, value

SOURCE = "procfs:/proc/vmstat"

# vmstat field -> (metric name, unit). Slab counters are in pages, not bytes: the page size is
# not part of vmstat, so they are not converted.
FIELDS = {
    "pgfault": ("system.vmstat.pgfault_count", "count"),
    "pgmajfault": ("system.vmstat.pgmajfault_count", "count"),
    "pgscan_kswapd": ("system.vmstat.pgscan_kswapd_count", "count"),
    "pgscan_direct": ("system.vmstat.pgscan_direct_count", "count"),
    "oom_kill": ("system.vmstat.oom_kill_count", "count"),
    "nr_slab_reclaimable": ("system.vmstat.slab_reclaimable_pages", "pages"),
    "nr_slab_unreclaimable": ("system.vmstat.slab_unreclaimable_pages", "pages"),
}


def metric_names() -> list[str]:
    return [name for name, _ in FIELDS.values()]


def parse(text: str) -> dict[str, Metric]:
    seen: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in FIELDS:
            seen.setdefault(parts[0], parts[1])
    if not seen and not text.strip():
        return all_unavailable(metric_names(), "parse_error", "empty /proc/vmstat")
    out: dict[str, Metric] = {}
    for key, (name, unit) in FIELDS.items():
        if key not in seen:
            out[name] = unavailable("unsupported", f"{key} not present in /proc/vmstat")
            continue
        parsed = parse_count(seen[key])
        out[name] = (
            value(parsed, unit, SOURCE)
            if parsed is not None
            else unavailable("parse_error", f"{key} has an unexpected format")
        )
    return out
