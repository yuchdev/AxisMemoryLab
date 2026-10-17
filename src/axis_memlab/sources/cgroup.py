"""Cgroup memory charge for a process's own cgroup (v1 or v2); conditional source.

Cgroup memory and RSS measure different things and must not be compared as equals.
"""

from __future__ import annotations

import re

from axis_memlab.records import Metric
from axis_memlab.sources.common import parse_count, unavailable, value

SOURCE = "cgroupfs"
CURRENT = "process.cgroup_memory_current_bytes"
LIMIT = "process.cgroup_memory_limit_bytes"
OOM_KILL = "process.cgroup_oom_kill_count"

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9_.@:/-]*$")


def metric_names() -> list[str]:
    return [CURRENT, LIMIT, OOM_KILL]


def parse_proc_cgroup(text: str) -> tuple[int, str] | None:
    """``/proc/PID/cgroup`` -> (version, relative path). v2 is the ``0::`` line; v1 uses the
    ``memory`` controller line. Paths with unusual characters or ``..`` are refused."""
    chosen: tuple[int, str] | None = None
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, path = parts
        if hierarchy == "0" and controllers == "":
            chosen = (2, path)
        elif "memory" in controllers.split(",") and chosen is None:
            chosen = (1, path)
    if chosen is None:
        return None
    path = chosen[1]
    if not _SAFE_PATH.match(path) or ".." in path.split("/"):
        return None
    return chosen[0], path


def files_for(version: int, path: str) -> dict[str, str]:
    """Absolute file paths to read for each quantity."""
    base = "/sys/fs/cgroup" + ("" if path == "/" else path)
    if version == 2:
        return {
            "current": f"{base}/memory.current",
            "limit": f"{base}/memory.max",
            "events": f"{base}/memory.events",
        }
    v1 = "/sys/fs/cgroup/memory" + ("" if path == "/" else path)
    return {
        "current": f"{v1}/memory.usage_in_bytes",
        "limit": f"{v1}/memory.limit_in_bytes",
    }


def parse(version: int, texts: dict[str, str]) -> dict[str, Metric]:
    out: dict[str, Metric] = {}
    current = parse_count(texts.get("current", ""))
    out[CURRENT] = (
        value(current, "bytes", SOURCE)
        if current is not None
        else unavailable("parse_error", "memory current is not a number")
    )
    limit_text = texts.get("limit", "").strip()
    if limit_text == "max":
        out[LIMIT] = unavailable("unsupported", "no memory limit configured (max)")
    else:
        limit = parse_count(limit_text)
        # v1 reports an enormous number for "unlimited"; treat anything >= 2**60 as no limit.
        if limit is None:
            out[LIMIT] = unavailable("parse_error", "memory limit is not a number")
        elif limit >= 1 << 60:
            out[LIMIT] = unavailable("unsupported", "no memory limit configured")
        else:
            out[LIMIT] = value(limit, "bytes", SOURCE)
    if version == 2:
        oom = None
        for line in texts.get("events", "").splitlines():
            key, _, val = line.partition(" ")
            if key == "oom_kill":
                oom = parse_count(val)
        out[OOM_KILL] = (
            value(oom, "count", SOURCE)
            if oom is not None
            else unavailable("unsupported", "oom_kill not present in memory.events")
        )
    else:
        out[OOM_KILL] = unavailable("unsupported", "cgroup v1 oom counter is not collected")
    return out
