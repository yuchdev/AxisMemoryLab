"""``/proc/meminfo``: device-wide memory. Never attributable to one process."""

from __future__ import annotations

from axis_memlab.records import Metric
from axis_memlab.sources.common import (
    all_unavailable,
    parse_kb,
    split_key_value,
    unavailable,
    value,
)

SOURCE = "procfs:/proc/meminfo"

FIELDS = {
    "MemTotal": "system.mem.total_bytes",
    "MemFree": "system.mem.free_bytes",
    "MemAvailable": "system.mem.available_bytes",
    "Buffers": "system.mem.buffers_bytes",
    "Cached": "system.mem.cached_bytes",
    "Shmem": "system.mem.shmem_bytes",
    "Slab": "system.mem.slab_bytes",
    "SReclaimable": "system.mem.slab_reclaimable_bytes",
    "SUnreclaim": "system.mem.slab_unreclaim_bytes",
    "SwapTotal": "system.mem.swap_total_bytes",
    "SwapFree": "system.mem.swap_free_bytes",
}


def metric_names() -> list[str]:
    return list(FIELDS.values())


def parse(text: str) -> dict[str, Metric]:
    """Parse meminfo text. Field order and spacing do not matter; absent fields are explicit."""
    seen: dict[str, str] = {}
    for line in text.splitlines():
        pair = split_key_value(line)
        if pair and pair[0] in FIELDS:
            seen.setdefault(pair[0], pair[1])  # first occurrence wins; duplicates are junk
    if not seen:
        return all_unavailable(metric_names(), "parse_error", "no recognizable meminfo fields")
    out: dict[str, Metric] = {}
    for key, name in FIELDS.items():
        if key not in seen:
            out[name] = unavailable("unsupported", f"{key} not present in /proc/meminfo")
            continue
        parsed = parse_kb(seen[key])
        out[name] = (
            value(parsed, "bytes", SOURCE)
            if parsed is not None
            else unavailable("parse_error", f"{key} has an unexpected format")
        )
    return out
