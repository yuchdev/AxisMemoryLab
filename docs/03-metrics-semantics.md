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

## Metric-name registry (M0001)

Every metric the host collector can write. Sizes are bytes (kernel `kB` is 1024 bytes,
converted at parse time); a field that is present but zero is recorded as `0`; a field that
cannot be read is recorded as unavailable with a closed `reason_code`
(`missing`, `permission_denied`, `timeout`, `parse_error`, `unsupported`, `not_collected`)
and a human-readable reason, never as zero. A test fails if a parser metric is missing from
this table.

| Metric | Unit | Source | Note |
| --- | --- | --- | --- |
| `system.mem.total_bytes` | bytes | `/proc/meminfo` | `MemTotal` |
| `system.mem.free_bytes` | bytes | `/proc/meminfo` | `MemFree` |
| `system.mem.available_bytes` | bytes | `/proc/meminfo` | `MemAvailable` |
| `system.mem.buffers_bytes` | bytes | `/proc/meminfo` | `Buffers` |
| `system.mem.cached_bytes` | bytes | `/proc/meminfo` | `Cached` |
| `system.mem.shmem_bytes` | bytes | `/proc/meminfo` | `Shmem` |
| `system.mem.slab_bytes` | bytes | `/proc/meminfo` | `Slab` |
| `system.mem.slab_reclaimable_bytes` | bytes | `/proc/meminfo` | `SReclaimable` |
| `system.mem.slab_unreclaim_bytes` | bytes | `/proc/meminfo` | `SUnreclaim` |
| `system.mem.swap_total_bytes` | bytes | `/proc/meminfo` | `SwapTotal` |
| `system.mem.swap_free_bytes` | bytes | `/proc/meminfo` | `SwapFree` |
| `system.vmstat.pgfault_count` | count | `/proc/vmstat` | `pgfault` |
| `system.vmstat.pgmajfault_count` | count | `/proc/vmstat` | `pgmajfault` |
| `system.vmstat.pgscan_kswapd_count` | count | `/proc/vmstat` | `pgscan_kswapd` |
| `system.vmstat.pgscan_direct_count` | count | `/proc/vmstat` | `pgscan_direct` |
| `system.vmstat.oom_kill_count` | count | `/proc/vmstat` | `oom_kill` |
| `system.vmstat.slab_reclaimable_pages` | pages | `/proc/vmstat` | `nr_slab_reclaimable` |
| `system.vmstat.slab_unreclaimable_pages` | pages | `/proc/vmstat` | `nr_slab_unreclaimable` |
| `system.psi.memory_some_avg10_percent` | percent | `/proc/pressure/memory` | `some` stall share over 10 s |
| `system.psi.memory_some_avg60_percent` | percent | `/proc/pressure/memory` | `some` stall share over 60 s |
| `system.psi.memory_some_avg300_percent` | percent | `/proc/pressure/memory` | `some` stall share over 300 s |
| `system.psi.memory_some_total_us` | microseconds | `/proc/pressure/memory` | `some` cumulative stall time |
| `system.psi.memory_full_avg10_percent` | percent | `/proc/pressure/memory` | `full` stall share over 10 s |
| `system.psi.memory_full_avg60_percent` | percent | `/proc/pressure/memory` | `full` stall share over 60 s |
| `system.psi.memory_full_avg300_percent` | percent | `/proc/pressure/memory` | `full` stall share over 300 s |
| `system.psi.memory_full_total_us` | microseconds | `/proc/pressure/memory` | `full` cumulative stall time |
| `process.vm_size_bytes` | bytes | `/proc/PID/status` | `VmSize` |
| `process.rss_bytes` | bytes | `/proc/PID/status` | `VmRSS` |
| `process.rss_anon_bytes` | bytes | `/proc/PID/status` | `RssAnon` |
| `process.rss_file_bytes` | bytes | `/proc/PID/status` | `RssFile` |
| `process.rss_shmem_bytes` | bytes | `/proc/PID/status` | `RssShmem` |
| `process.vm_swap_bytes` | bytes | `/proc/PID/status` | `VmSwap` |
| `process.threads_count` | count | `/proc/PID/status` | `Threads` |
| `process.minor_faults_count` | count | `/proc/PID/stat` | field 10 |
| `process.major_faults_count` | count | `/proc/PID/stat` | field 12 |
| `process.cpu_user_ticks` | ticks | `/proc/PID/stat` | field 14, clock ticks |
| `process.cpu_system_ticks` | ticks | `/proc/PID/stat` | field 15, clock ticks |
| `process.smaps_rss_bytes` | bytes | `/proc/PID/smaps_rollup` | `Rss` |
| `process.pss_bytes` | bytes | `/proc/PID/smaps_rollup` | `Pss` |
| `process.private_clean_bytes` | bytes | `/proc/PID/smaps_rollup` | `Private_Clean` |
| `process.private_dirty_bytes` | bytes | `/proc/PID/smaps_rollup` | `Private_Dirty` |
| `process.shared_clean_bytes` | bytes | `/proc/PID/smaps_rollup` | `Shared_Clean` |
| `process.shared_dirty_bytes` | bytes | `/proc/PID/smaps_rollup` | `Shared_Dirty` |
| `process.anonymous_bytes` | bytes | `/proc/PID/smaps_rollup` | `Anonymous` |
| `process.swap_bytes` | bytes | `/proc/PID/smaps_rollup` | `Swap` |
| `process.swap_pss_bytes` | bytes | `/proc/PID/smaps_rollup` | `SwapPss` |
| `process.uss_approx_bytes` | bytes | `/proc/PID/smaps_rollup` | `Private_Clean + Private_Dirty`; equals USS only for ordinary resident pages |
| `process.fd_count` | count | `/proc/PID/fd` | all descriptors |
| `process.fd_socket_count` | count | `/proc/PID/fd` | targets classified `socket` |
| `process.fd_pipe_count` | count | `/proc/PID/fd` | targets classified `pipe` |
| `process.fd_dmabuf_count` | count | `/proc/PID/fd` | targets classified `dmabuf` |
| `process.fd_anon_inode_other_count` | count | `/proc/PID/fd` | targets classified `anon_inode_other` |
| `process.fd_file_count` | count | `/proc/PID/fd` | targets classified `file` |
| `process.fd_other_count` | count | `/proc/PID/fd` | targets classified `other` |
| `process.cgroup_memory_current_bytes` | bytes | cgroup `memory.current` / `memory.usage_in_bytes` | charge of the process's own cgroup |
| `process.cgroup_memory_limit_bytes` | bytes | cgroup `memory.max` / `memory.limit_in_bytes` | unavailable when no limit is set |
| `process.cgroup_oom_kill_count` | count | cgroup `memory.events` | v2 only |
| `collector.cycle_duration_ns` | nanoseconds | collector | time spent in this cycle's reads |
| `collector.reads_total_count` | count | collector | cumulative reads attempted |
| `collector.read_errors_count` | count | collector | cumulative reads that failed or were unusable |
| `collector.bytes_read_bytes` | bytes | collector | cumulative bytes read |

Notes:

- `system.*` is device-wide and never attributable to one process. `process.cgroup_*` is the
  process's cgroup charge, which measures something different from RSS.
- `smaps_rollup`, the fd inventory, and the cgroup reads happen at the sparse interval
  (`smaps_rollup_interval_seconds`) or on a trigger, not on every sample. A sample without
  them simply does not contain those names.
- `VmSize` is address space, not physical use. Slab counters in `vmstat` are in pages; the
  page size is not part of `vmstat`, so they are not converted.
- `collector.*` describes the collector's own cost and errors, so overhead and data quality
  are part of every run.
- fd targets and paths are classified and discarded; they are never stored.
- Application counters (`app.*`) are chosen by the application; the in-app probe's names are
  in the next section.

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

### Sampler health (`AXMEM_SAMPLER`, only while the sampler runs)

| Name | Unit | Meaning |
| --- | --- | --- |
| `app.sampler.alloc_requests_count` | count | Exact number of allocation requests seen since `axmem_sampler_start` |
| `app.sampler.alloc_requested_total_bytes` | bytes | Exact **cumulative** requested bytes, not live memory |
| `app.sampler.free_requests_count` | count | Exact number of frees seen |
| `app.sampler.samples_taken_count`, `live_samples_count` | count | Tracked samples taken, and those not yet freed |
| `app.sampler.dropped_samples_count` | count | Samples not recorded (full table or ring) |
| `app.sampler.dropped_free_events_count` | count | Free events lost; live estimates may overstate |
| `app.sampler.stack_failures_count` | count | Samples with an empty stack |

Sampled allocation records themselves (`alloc-samples-v1`) are a separate file; see
`docs/12-allocation-sampling.md`.

### Device Data Hub metrics (`advanced import-ddh`)

`system.ddh.*` names come from the operator's mapping file (`src/axis_memlab/sources/ddh.py`).
They are **device-wide utilization**, never per-process memory; the unit and scale are the
operator's, `_bytes` names must use bytes, and every sample's `source_metadata` records the topic
and its maturity (alpha at the time of writing). Missing or non-numeric values are unavailable
with `reason_code` `missing` or `parse_error`.

### Metrics the platform rules read

`system.mem.shmem_bytes`, `system.mem.slab_unreclaim_bytes`, `system.mem.cached_bytes`,
`process.rss_shmem_bytes`, `process.fd_count`, `process.fd_dmabuf_count`, and
`process.cgroup_memory_current_bytes` are analysed automatically when present
(`docs/13-advanced-diagnostics.md`, section 11), in addition to the configured metrics.
