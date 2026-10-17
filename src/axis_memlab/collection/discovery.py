"""Capability discovery: what this account can read on the target, without assuming anything.

Everything is a read-only, allowlisted read. Results are capability states, never errors; only
a transport failure (cannot connect at all) aborts discovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axis_memlab.capability import Capability, state_for_reason_code
from axis_memlab.errors import CollectionError
from axis_memlab.sources import cgroup as cgroup_source
from axis_memlab.sources import meminfo
from axis_memlab.transport import Reader, ReadError

SYSTEM_PATHS = {
    "meminfo": "/proc/meminfo",
    "vmstat": "/proc/vmstat",
    "pressure_memory": "/proc/pressure/memory",
    "kernel_release": "/proc/sys/kernel/osrelease",
    "boot_id": "/proc/sys/kernel/random/boot_id",
}
PROCESS_FILES = {
    "process_status": "status",
    "process_stat": "stat",
    "process_smaps_rollup": "smaps_rollup",
    "process_cgroup": "cgroup",
}
NOT_PROBED = (
    "ps/top/pmap/journalctl/gdbserver/perf availability: only allowlisted read-only /proc and "
    "cgroup reads are made; check these manually and record them in the compatibility matrix"
)


@dataclass
class Discovery:
    capabilities: list[Capability] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    processes: list[tuple[int, str]] = field(default_factory=list)
    pid: int | None = None
    cgroup: tuple[int, str] | None = None

    def state(self, name: str) -> str:
        for cap in self.capabilities:
            if cap.name == name:
                return cap.state
        return "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "capabilities": [c.annotations() for c in self.capabilities],
            "facts": self.facts,
            "processes": [{"pid": pid, "comm": comm} for pid, comm in self.processes],
            "not_probed": NOT_PROBED,
        }


def select_process(
    reader: Reader, pid: int | None, app: str | None
) -> tuple[int | None, list[tuple[int, str]]]:
    """Resolve the target process. ``app`` matches the kernel command name (``comm``)."""
    if pid is not None:
        if pid < 1:
            raise CollectionError("pid must be positive")
        return pid, []
    if app is None:
        return None, []
    visible = reader.scan_comm()
    wanted = app[:15]  # the kernel truncates comm to 15 characters
    matches = sorted(p for p, comm in visible.items() if comm == wanted)
    if not matches:
        raise CollectionError(
            f"no visible process has command name {wanted!r}; the SSH account may not be able to "
            "see it (use the in-app probe) or the name differs (use --pid)"
        )
    if len(matches) > 1:
        raise CollectionError(
            f"{len(matches)} processes match {wanted!r} (pids {matches}); choose one with --pid"
        )
    return matches[0], [(matches[0], wanted)]


def _capability(name: str, result: str | ReadError) -> Capability:
    if isinstance(result, ReadError):
        return Capability(name, state_for_reason_code(result.code), result.detail)
    return Capability(name, "available")


def discover(reader: Reader, *, pid: int | None = None, app: str | None = None) -> Discovery:
    found = Discovery()
    found.pid, found.processes = select_process(reader, pid, app)

    paths = list(SYSTEM_PATHS.values())
    if found.pid is not None:
        paths += [f"/proc/{found.pid}/{leaf}" for leaf in PROCESS_FILES.values()]
    results = reader.read_many(paths)

    for name, path in SYSTEM_PATHS.items():
        found.capabilities.append(_capability(name, results[path]))
    release = results[SYSTEM_PATHS["kernel_release"]]
    if isinstance(release, str):
        found.facts["kernel_release"] = release.strip()[:64]
    boot = results[SYSTEM_PATHS["boot_id"]]
    if isinstance(boot, str) and len(boot.strip()) == 36:
        found.facts["boot_id"] = boot.strip()
    mem = results[SYSTEM_PATHS["meminfo"]]
    if isinstance(mem, str):
        total = meminfo.parse(mem).get("system.mem.total_bytes")
        if total is not None and total.available:
            found.facts["mem_total_bytes"] = total.value

    if found.pid is not None:
        found.facts["pid"] = found.pid
        for name, leaf in PROCESS_FILES.items():
            found.capabilities.append(_capability(name, results[f"/proc/{found.pid}/{leaf}"]))
        try:
            reader.read_fd_targets(found.pid)
            found.capabilities.append(Capability("process_fd", "available"))
        except ReadError as exc:
            found.capabilities.append(
                Capability("process_fd", state_for_reason_code(exc.code), exc.detail)
            )
        cg = results[f"/proc/{found.pid}/cgroup"]
        if isinstance(cg, str):
            found.cgroup = cgroup_source.parse_proc_cgroup(cg)
            if found.cgroup is None:
                found.capabilities.append(
                    Capability("cgroup_memory", "unsupported", "no usable memory cgroup path")
                )
            else:
                files = cgroup_source.files_for(*found.cgroup)
                probe = reader.read_many([files["current"]])[files["current"]]
                found.capabilities.append(_capability("cgroup_memory", probe))
                found.facts["cgroup_version"] = found.cgroup[0]
    return found
