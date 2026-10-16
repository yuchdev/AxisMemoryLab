# Metric semantics

RSS is resident memory mapped by a process and can count shared pages in more
than one process. PSS apportions shared pages among processes; USS is the
process's unique resident pages. Anonymous and file-backed memory differ and
must not be conflated. Availability and kernel interfaces vary by platform;
unsupported or unreadable metrics must be marked unavailable with a reason,
not represented as zero.

Internal byte counts use bytes, not decimal kB or binary KiB. Names should state
the measured scope and unit. M0001 will define normalization and source parsing
semantics before collectors are implemented.

## Planned metric sources (M0001 to finalize names)

| Namespace | Source | Notes |
| --- | --- | --- |
| `system.mem.*` | `/proc/meminfo` (`MemAvailable`, `MemFree`, `Cached`, `Shmem`, `Slab`, `SReclaimable`, `SUnreclaim`) | Device-wide; never attributable to one process. |
| `system.vmstat.*` | `/proc/vmstat` (slab, fault, reclaim counters) | Names vary by kernel. |
| `system.psi.*` | `/proc/pressure/memory` (`some`, `full`) | Only when the kernel enables PSI; stall time, not size. |
| `process.*` | `/proc/PID/status` (`VmSize`, `VmRSS`, `RssAnon`, `RssFile`, `RssShmem`, threads), `smaps_rollup` (`Pss`, `Private_*`, `Anonymous`, `Swap`) | `smaps_rollup` may be missing or unreadable; mark unavailable. |
| `process.fd_count`, fd target classes | `/proc/PID/fd` | Count alone gives no buffer sizes. |
| `app.*` | Application-owned counters (frames, queues, in-flight resources) | Generic names; no VDO/Larod ownership assumed. |

Kernel `kB` values convert to bytes at parse time. `VmSize` is address space,
not physical use. Private clean plus private dirty approximates USS only for
ordinary resident pages. A matching acquire/release total is necessary but not
sufficient evidence of no leak.
