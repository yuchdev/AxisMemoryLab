"""``/proc/PID/smaps_rollup``: PSS and private/shared residency in one cheap read.

Reading it makes the kernel walk the page tables, so it is sparse by policy. If it is missing
or denied the collector reports that and does not fall back to full ``smaps``.
"""

from __future__ import annotations

from axis_memlab.records import Metric
from axis_memlab.sources.common import (
    all_unavailable,
    parse_kb,
    split_key_value,
    unavailable,
    value,
)

SOURCE = "procfs:/proc/PID/smaps_rollup"

FIELDS = {
    "Rss": "process.smaps_rss_bytes",
    "Pss": "process.pss_bytes",
    "Private_Clean": "process.private_clean_bytes",
    "Private_Dirty": "process.private_dirty_bytes",
    "Shared_Clean": "process.shared_clean_bytes",
    "Shared_Dirty": "process.shared_dirty_bytes",
    "Anonymous": "process.anonymous_bytes",
    "Swap": "process.swap_bytes",
    "SwapPss": "process.swap_pss_bytes",
}
USS = "process.uss_approx_bytes"


def metric_names() -> list[str]:
    return [*FIELDS.values(), USS]


def parse(text: str) -> dict[str, Metric]:
    seen: dict[str, str] = {}
    for line in text.splitlines():
        pair = split_key_value(line)
        if pair and pair[0] in FIELDS:  # exact key match: "Pss" never matches "Pss_Anon"
            seen.setdefault(pair[0], pair[1])
    if not seen:
        return all_unavailable(metric_names(), "parse_error", "no recognizable smaps_rollup fields")
    out: dict[str, Metric] = {}
    raw: dict[str, int] = {}
    for key, name in FIELDS.items():
        if key not in seen:
            out[name] = unavailable("unsupported", f"{key} not present in smaps_rollup")
            continue
        parsed = parse_kb(seen[key])
        if parsed is None:
            out[name] = unavailable("parse_error", f"{key} has an unexpected format")
        else:
            raw[key] = parsed
            out[name] = value(parsed, "bytes", SOURCE)
    if "Private_Clean" in raw and "Private_Dirty" in raw:
        # Equals USS only for ordinary resident pages (not hugetlb); the name says "approx".
        out[USS] = value(raw["Private_Clean"] + raw["Private_Dirty"], "bytes", SOURCE)
    else:
        out[USS] = unavailable("unsupported", "needs both Private_Clean and Private_Dirty")
    return out
