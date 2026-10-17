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

## Probe-emitted metrics (M0003)

| Name | Unit | Meaning |
| --- | --- | --- |
| `app.<name>` (application-chosen) | `_bytes` → bytes, `_ns` → nanoseconds, else count | Counters only increase; gauges are the last value set; `watermark` keeps the maximum |
| `process.rss_bytes`, `rss_anon_bytes`, `rss_file_bytes`, `rss_shmem_bytes`, `vm_swap_bytes` | bytes | `/proc/self/status`; kB converted at parse time |
| `process.threads_count`, `process.fd_count` | count | fd count excludes the descriptor used to list the directory |
| `process.pss_bytes`, `private_clean_bytes`, `private_dirty_bytes`, `anonymous_bytes`, `swap_bytes` | bytes | `/proc/self/smaps_rollup`, opt-in |
| `app.resource.<kind>.acquired_total_count` / `released_total_count` | count | Applied events only; in LEDGER mode duplicates and unmatched releases are excluded |
| `app.resource.<kind>.in_flight_count` | count | Acquired minus released (COUNTERS: clamped at zero) or live ledger entries (LEDGER) |
| `app.resource.<kind>.in_flight_bytes`, `high_watermark_bytes` | bytes | LEDGER only; bytes are as declared by the application |
| `app.ledger.*` | count | `degraded = 1` means the ledger overflowed and in-flight numbers are lower bounds at best |
| `app.allocator.*` | bytes | glibc `mallinfo2`, opt-in; arena size is not live bytes |
| `app.probe.*` | count / bytes / nanoseconds | Probe self-health and the previous snapshot's duration |

A matching total of acquires and releases is necessary but not sufficient evidence of no
leak: resources can be mis-sized or have their ownership transferred.
