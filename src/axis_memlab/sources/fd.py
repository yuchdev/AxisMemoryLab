"""``/proc/PID/fd``: descriptor count and target classes.

Counts alone give no buffer sizes. Targets are classified and discarded: paths and socket
identifiers can identify users or networks, so they never reach the run archive.
"""

from __future__ import annotations

from axis_memlab.records import Metric
from axis_memlab.sources.common import value

SOURCE = "procfs:/proc/PID/fd"

CLASSES = ("socket", "pipe", "dmabuf", "anon_inode_other", "file", "other")
COUNT = "process.fd_count"


def metric_names() -> list[str]:
    return [COUNT, *(f"process.fd_{c}_count" for c in CLASSES)]


def parse_ls_long(text: str) -> dict[str, str]:
    """Parse ``ls -l /proc/PID/fd`` output into ``{fd number: target}``.

    This is also the saved-capture format used for offline fixtures and manual captures.
    """
    targets: dict[str, str] = {}
    for line in text.splitlines():
        head, sep, target = line.partition(" -> ")
        if not sep:
            continue
        fields = head.split()
        if fields and fields[-1].isdigit():
            targets[fields[-1]] = target.strip()
    return targets


def classify(target: str) -> str:
    base = target.removesuffix(" (deleted)")
    if base.startswith("socket:"):
        return "socket"
    if base.startswith("pipe:"):
        return "pipe"
    if base.startswith("anon_inode:"):
        return "dmabuf" if "dmabuf" in base else "anon_inode_other"
    if "/dmabuf" in base or base.startswith("/dmabuf"):
        return "dmabuf"
    if base.startswith("/"):
        return "file"
    return "other"


def metrics(targets: dict[str, str]) -> dict[str, Metric]:
    counts = dict.fromkeys(CLASSES, 0)
    for target in targets.values():
        counts[classify(target)] += 1
    out = {COUNT: value(len(targets), "count", SOURCE)}
    for name in CLASSES:
        out[f"process.fd_{name}_count"] = value(counts[name], "count", SOURCE)
    return out
