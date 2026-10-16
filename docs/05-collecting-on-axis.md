# Collecting on AXIS OS (planned)

**Owner:** M0001. **Status:** documentation outline; no device collection is
implemented or authorized by this scaffold.

Before documenting runnable device procedures, verify compatibility and
permissions, establish explicit operator consent, and use read-only bounded
collection. Never imply that M0000 can access an AXIS device.

## Planned collection levels (M0001 and later)

| Level | Content | Cadence | Gate |
| --- | --- | --- | --- |
| 0 | Device facts and capabilities (model, SoC, firmware, SDK generation, libc, available tools and `/proc` nodes) | Once per run | Record capabilities; require none |
| 1 | Selected `meminfo`, `vmstat`, PSI, process `status`/`stat`, app counters | `sample_interval_seconds` | Default |
| 2 | `smaps_rollup`, fd/maps inventory | `smaps_rollup_interval_seconds` | Not every interval |
| 3 | One-shot `smaps`, full fd classification, allocator report | Triggered, with cooldown, size and time budget | `allow_deep_snapshot`; refuse under critical memory pressure |
| 4 | `gdbserver`, `strace`, `perf`/eBPF on a lab unit | Manual | M0005; never automatic |

Collectors identify a process by `(boot_id, pid, process_start_ticks)`, use
monotonic time for slopes, record their own elapsed time and read errors, drop
telemetry rather than block the device, and avoid repeated writes to camera
flash. Prefer in-app self-telemetry when the SSH user cannot read the
application's `/proc/PID`. fd targets and paths may identify networks or
users and must be redacted per `docs/08-security-privacy.md`.
