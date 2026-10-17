"""Local filesystem reader: a saved procfs tree (fixtures, manual captures) or a live local host.

``root`` is a directory laid out like ``/``: ``root/proc/meminfo`` backs ``/proc/meminfo``. For a
live Linux host pass ``/``. Because Windows cannot hold symlinks in a fixture, ``/proc/PID/fd``
falls back to ``root/proc/PID/fd.ls``, a saved copy of ``ls -l /proc/PID/fd``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from axis_memlab.sources import fd as fd_source
from axis_memlab.transport import (
    DEFAULT_MAX_BYTES,
    ReadError,
    require_allowed,
)


class LocalProcfsReader:
    def __init__(self, root: str | Path, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._root = Path(root)
        self._max_bytes = max_bytes

    def describe(self) -> str:
        return "local-procfs"

    def _real(self, path: str) -> Path:
        return self._root / path.lstrip("/")

    def read_text(self, path: str) -> str:
        require_allowed(path)
        try:
            with self._real(path).open("rb") as stream:
                data = stream.read(self._max_bytes + 1)
        except FileNotFoundError:
            raise ReadError("missing", f"{path} does not exist") from None
        except PermissionError:
            raise ReadError("permission_denied", f"{path} is not readable") from None
        except OSError as exc:
            # A process can vanish between listing and reading; the kernel reports ESRCH.
            raise ReadError("missing", f"{path}: {exc.strerror or 'read failed'}") from None
        if len(data) > self._max_bytes:
            raise ReadError("not_collected", f"{path} exceeds the {self._max_bytes}-byte cap")
        return data.decode("utf-8", errors="replace")

    def read_many(self, paths: Iterable[str]) -> dict[str, str | ReadError]:
        out: dict[str, str | ReadError] = {}
        for path in paths:
            try:
                out[path] = self.read_text(path)
            except ReadError as exc:
                out[path] = exc
        return out

    def read_fd_targets(self, pid: int) -> dict[str, str]:
        directory = self._real(f"/proc/{pid}/fd")
        saved = self._real(f"/proc/{pid}/fd.ls")
        try:
            if directory.is_dir():
                targets: dict[str, str] = {}
                own = os.fspath(directory)
                skipped_own = False
                for entry in os.scandir(directory):
                    if entry.name.isdigit():
                        try:
                            target = os.readlink(entry.path)
                        except OSError:
                            continue  # the descriptor closed while we were looking
                        if target == own and not skipped_own:
                            # On a live /proc listing our own process, the directory handle used
                            # for the listing appears in the listing; do not count it.
                            skipped_own = True
                            continue
                        targets[entry.name] = target
                return targets
        except PermissionError:
            raise ReadError("permission_denied", f"/proc/{pid}/fd is not readable") from None
        except OSError:
            raise ReadError("missing", f"/proc/{pid}/fd could not be listed") from None
        try:
            return fd_source.parse_ls_long(saved.read_text(encoding="utf-8", errors="replace"))
        except FileNotFoundError:
            raise ReadError("missing", f"/proc/{pid}/fd does not exist") from None
        except PermissionError:
            raise ReadError("permission_denied", f"/proc/{pid}/fd is not readable") from None

    def scan_comm(self) -> dict[int, str]:
        proc = self._real("/proc")
        found: dict[int, str] = {}
        try:
            names = sorted(n for n in os.listdir(proc) if n.isdigit())
        except PermissionError:
            raise ReadError("permission_denied", "/proc is not listable") from None
        except OSError:
            raise ReadError("missing", "/proc could not be listed") from None
        for name in names[:4096]:
            try:
                found[int(name)] = self.read_text(f"/proc/{name}/comm").strip()
            except ReadError:
                continue  # exited, or another account's process: simply not visible
        return found
