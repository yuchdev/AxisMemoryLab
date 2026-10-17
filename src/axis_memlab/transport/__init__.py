"""Read-only access to procfs/cgroupfs on a local tree or a remote device.

Every reader exposes the same few operations and the same allowlist of readable paths, so a
bug in a collector cannot turn into arbitrary command execution or arbitrary file reads. Reads
return text or raise :class:`ReadError` carrying a closed reason code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from axis_memlab.records import REASON_CODES

DEFAULT_MAX_BYTES = 1024 * 1024

# Paths a reader will ever open. Anything else is refused before it reaches a file or a shell.
_ALLOWED = re.compile(
    r"^/proc/(?:"
    r"meminfo|vmstat|pressure/memory|sys/kernel/osrelease|sys/kernel/random/boot_id"
    r"|[0-9]{1,10}/(?:status|stat|smaps_rollup|comm|cgroup)"
    r")$|^/sys/fs/cgroup/(?:[A-Za-z0-9_.@:-]+/)*"
    r"memory\.(?:current|max|events|usage_in_bytes|limit_in_bytes)$"
)
_FD_DIR = re.compile(r"^/proc/([0-9]{1,10})/fd$")


class ReadError(Exception):
    """A single read failed. ``code`` is one of :data:`axis_memlab.records.REASON_CODES`."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in REASON_CODES:
            raise ValueError(f"unknown reason code: {code}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def is_allowed_file(path: str) -> bool:
    return bool(_ALLOWED.match(path)) and ".." not in path.split("/")


def fd_dir_pid(path: str) -> int | None:
    match = _FD_DIR.match(path)
    return int(match.group(1)) if match else None


def require_allowed(path: str) -> None:
    if not is_allowed_file(path):
        raise ReadError("unsupported", f"path is not on the read-only allowlist: {path[:80]!r}")


class Reader(Protocol):
    """What collectors need from a transport."""

    def describe(self) -> str:
        """A short, secret-free label for logs and manifests."""

    def read_text(self, path: str) -> str:
        """Contents of an allowlisted file, at most the reader's byte cap."""

    def read_many(self, paths: Iterable[str]) -> dict[str, str | ReadError]:
        """Several reads in one round trip where the transport can do that."""

    def read_fd_targets(self, pid: int) -> dict[str, str]:
        """``{fd number: link target}`` for a process, from ``/proc/PID/fd``."""

    def scan_comm(self) -> dict[int, str]:
        """``{pid: command name}`` for processes this account can see."""
