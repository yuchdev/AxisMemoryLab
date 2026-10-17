"""``/proc/PID/status`` and ``/proc/PID/stat``: per-process residency, CPU, faults, identity."""

from __future__ import annotations

from axis_memlab.records import Metric
from axis_memlab.sources.common import (
    all_unavailable,
    parse_count,
    parse_kb,
    split_key_value,
    unavailable,
    value,
)

STATUS_SOURCE = "procfs:/proc/PID/status"
STAT_SOURCE = "procfs:/proc/PID/stat"

STATUS_FIELDS = {
    "VmSize": "process.vm_size_bytes",
    "VmRSS": "process.rss_bytes",
    "RssAnon": "process.rss_anon_bytes",
    "RssFile": "process.rss_file_bytes",
    "RssShmem": "process.rss_shmem_bytes",
    "VmSwap": "process.vm_swap_bytes",
}
THREADS = "process.threads_count"

# Field numbers are those of proc(5) "stat"; indices count from the field after the last ")".
_STAT_INDEX = {
    "minflt": (10, "process.minor_faults_count", "count"),
    "majflt": (12, "process.major_faults_count", "count"),
    "utime": (14, "process.cpu_user_ticks", "ticks"),
    "stime": (15, "process.cpu_system_ticks", "ticks"),
}
START_TICKS_FIELD = 22


def status_metric_names() -> list[str]:
    return [*STATUS_FIELDS.values(), THREADS]


def stat_metric_names() -> list[str]:
    return [name for _, name, _ in _STAT_INDEX.values()]


def parse_status(text: str) -> dict[str, Metric]:
    seen: dict[str, str] = {}
    for line in text.splitlines():
        pair = split_key_value(line)
        if pair and (pair[0] in STATUS_FIELDS or pair[0] == "Threads"):
            seen.setdefault(pair[0], pair[1])
    if not seen:
        return all_unavailable(
            status_metric_names(), "parse_error", "no recognizable status fields"
        )
    out: dict[str, Metric] = {}
    for key, name in STATUS_FIELDS.items():
        if key not in seen:
            # RssAnon/RssFile/RssShmem need Linux 4.5+; VmSwap can be absent on swapless kernels.
            out[name] = unavailable("unsupported", f"{key} not present in /proc/PID/status")
            continue
        parsed = parse_kb(seen[key])
        out[name] = (
            value(parsed, "bytes", STATUS_SOURCE)
            if parsed is not None
            else unavailable("parse_error", f"{key} has an unexpected format")
        )
    threads = parse_count(seen["Threads"]) if "Threads" in seen else None
    out[THREADS] = (
        value(threads, "count", STATUS_SOURCE)
        if threads is not None
        else unavailable("unsupported", "Threads not present or malformed")
    )
    return out


def _stat_fields(text: str) -> list[str] | None:
    """Fields after the command name. The name may contain spaces and parentheses."""
    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    return fields if len(fields) >= 20 else None


def parse_start_ticks(text: str) -> int | None:
    """Field 22 (``starttime``), the process-instance part of the identity."""
    fields = _stat_fields(text)
    if fields is None:
        return None
    return parse_count(fields[START_TICKS_FIELD - 3])


def parse_stat(text: str) -> dict[str, Metric]:
    fields = _stat_fields(text)
    if fields is None:
        return all_unavailable(stat_metric_names(), "parse_error", "stat line is truncated")
    out: dict[str, Metric] = {}
    for number, name, unit in _STAT_INDEX.values():
        parsed = parse_count(fields[number - 3])
        out[name] = (
            value(parsed, unit, STAT_SOURCE)
            if parsed is not None
            else unavailable("parse_error", f"stat field {number} is not a number")
        )
    return out
