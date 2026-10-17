"""Catalog of advanced (Level 3-4) diagnostics and what each one may and may not show.

The repository does not run any of these on a device. The catalog is the single list that the
evidence gate (``evidence.py``), the CLI (``axis-memlab advanced list``), and
``docs/13-advanced-diagnostics.md`` are generated from, so they cannot drift apart. Every entry is
**blocked until verified for specific firmware** (see ``evidence.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

# How much the toolset itself does for a diagnostic.
TOOL_IMPORTS = "imports_data"  # the tool can import or process its output
TOOL_GATE_ONLY = "gate_only"  # a procedure in the guide; the tool only checks permission
TOOL_BLOCKED = "blocked_by_safety_model"  # the safety model forbids it; the gate never allows it


@dataclass(frozen=True)
class Diagnostic:
    id: str
    title: str
    level: int  # 3 = triggered/sparse, 4 = lab-only
    intrusive: bool
    lab_unit_required: bool
    developer_mode_required: bool
    tool_support: str
    provides: str
    cannot_show: str
    risks: str
    guide_section: str


CATALOG: tuple[Diagnostic, ...] = (
    Diagnostic(
        "ddh_topics",
        "Device Data Hub CPU / memory utilization topics",
        3,
        False,
        False,
        False,
        TOOL_IMPORTS,
        "Device-wide CPU and memory utilization over time, from a supported topic",
        "Per-process or per-subsystem attribution; topics are alpha maturity and "
        "firmware-dependent",
        "Low. A client must subscribe; topic shapes can change between releases",
        "2",
    ),
    Diagnostic(
        "server_report",
        "Axis device server report",
        3,
        False,
        False,
        False,
        TOOL_GATE_ONLY,
        "Firmware, configuration, logs, and environment context for one incident",
        "Memory attribution; it is context, not a measurement",
        "Contains identifying data (addresses, serial numbers, configuration). Must be "
        "redacted and reviewed before leaving the operator's machine",
        "3",
    ),
    Diagnostic(
        "strace_scoped",
        "Scoped strace (mmap, munmap, brk, fd syscalls)",
        4,
        True,
        True,
        False,
        TOOL_GATE_ONLY,
        "Which memory-mapping and descriptor system calls the process makes, and when",
        "Which malloc call site requested memory; kernel allocations; anything it did not trace",
        "Slows the target substantially and changes timing; needs ptrace permission",
        "4",
    ),
    Diagnostic(
        "gdbserver",
        "gdbserver remote debugging",
        4,
        True,
        True,
        True,
        TOOL_GATE_ONLY,
        "Interactive inspection of a stopped process from a workstation with matching symbols",
        "Behaviour under load; it interrupts the application",
        "Stops the process and can disturb the video pipeline; Developer Mode required",
        "5",
    ),
    Diagnostic(
        "perf_stat",
        "perf stat (counting events)",
        4,
        False,
        True,
        False,
        TOOL_GATE_ONLY,
        "Page faults, context switches, cache and memory event counts for a process",
        "Allocation sites; it counts, it does not attribute",
        "Needs perf_event access; counting overhead is small but non-zero",
        "6",
    ),
    Diagnostic(
        "perf_record",
        "perf record (sampling)",
        4,
        True,
        True,
        False,
        TOOL_GATE_ONLY,
        "Where time is spent, and with call graphs where fault events happen",
        "Heap ownership; kernel memory use unless kernel symbols are available",
        "Adds CPU load and writes a large data file; needs perf_event access",
        "6",
    ),
    Diagnostic(
        "ftrace",
        "ftrace / kernel tracepoints (kmem, mm)",
        4,
        True,
        True,
        False,
        TOOL_GATE_ONLY,
        "Kernel-side allocation and page events, with the PID that was running",
        "Userspace malloc sites; a PID on a kernel event is not proof of long-term ownership",
        "Needs tracefs and privilege; high event volume; can disturb timing",
        "7",
    ),
    Diagnostic(
        "ebpf",
        "eBPF tracing (memory-related probes)",
        4,
        True,
        True,
        False,
        TOOL_GATE_ONLY,
        "Programmable kernel and userspace probes where the kernel supports them",
        "Anything the kernel build or privilege model disallows",
        "Needs a kernel with BPF enabled and privilege that restricted accounts lack",
        "7",
    ),
    Diagnostic(
        "slabinfo",
        "Kernel slab accounting (/proc/slabinfo)",
        4,
        False,
        True,
        False,
        TOOL_GATE_ONLY,
        "Which kernel slab caches are growing",
        "Which userspace code causes the growth",
        "Usually readable only by root; a read walks kernel structures",
        "8",
    ),
    Diagnostic(
        "dmabuf_debugfs",
        "DMA-BUF accounting (debugfs)",
        4,
        False,
        True,
        False,
        TOOL_GATE_ONLY,
        "Exported DMA buffers, their sizes and holders, where debugfs exposes them",
        "Buffers that are not exported through dma-buf",
        "Needs debugfs mounted and privilege; mounting debugfs is a device change",
        "8",
    ),
    Diagnostic(
        "core_dump",
        "Process core or full memory dump",
        4,
        True,
        True,
        False,
        TOOL_GATE_ONLY,
        "A frozen copy of process memory for offline analysis with matching symbols",
        "History of allocations; Valgrind cannot recover it from a dump",
        "Large, slow, and likely to contain private CCTV data, credentials, or plate text. "
        "Never ordinary telemetry",
        "9",
    ),
    Diagnostic(
        "deep_smaps",
        "Deep capture: full /proc/PID/smaps, full fd inventory, allocator reports",
        3,
        True,
        True,
        False,
        TOOL_BLOCKED,
        "Per-mapping residency and fd targets for differential mapping reports",
        "Allocation sites; paths and names are sensitive",
        "Page-table walks and large output; mapping names and paths can identify users",
        "10",
    ),
)

BY_ID = {d.id: d for d in CATALOG}
IDS = tuple(d.id for d in CATALOG)
