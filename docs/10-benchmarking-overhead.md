# Benchmarking overhead

**Owner:** M0003. **Status:** method defined; host numbers recorded; **no device
measurements exist.** Numbers from a workstation say nothing about an AXIS camera.

## What to measure

Instrumentation changes the system it observes, so each conclusion that depends on it
needs a control without it. On the smallest authorized device, compare an uninstrumented
build with `AXMEM_COUNTERS` and `AXMEM_LEDGER` builds under the same workload (same
firmware, scene, codec, resolution, frame rate):

| Quantity | How |
| --- | --- |
| Pipeline throughput and latency | Frames per second and per-stage timings against the uninstrumented build, over at least two repetitions |
| CPU | Process CPU time per frame or per minute (`/proc/PID/stat` utime+stime) |
| Peak and steady RSS added | `process.rss_anon_bytes` after warm-up in each build; goal for counter-only mode is under 1 MiB added (a design goal, not a result) |
| Snapshot cost | `app.probe.snapshot_duration_ns`, and the added cost when `include_smaps_rollup` is on (page-table scan) |
| Output volume | `app.probe.output_bytes` per hour at the chosen interval |
| Collector cost (M0001) | SSH login and read cost per sample, a single multi-read command against a persistent connection, network bytes |
| `smaps_rollup` scan cost | Time per read on the device, to set the sparse interval |

Report the memory trend with and without the probe: if the slope changes, say so, and use
the lighter mode for the main runs.

## Host microbenchmark (this machine only)

`axis_memlab_overhead_bench` (built in the enabled modes) times the hot-path calls:

```bash
axis_memlab_overhead_bench [OPERATIONS_PER_THREAD]    # CSV: operation,threads,ns_per_op
```

Recorded 2026-10-17 on a Windows laptop (Intel Core i5-6300U, 2 cores / 4 threads), MSVC
Release, 2,000,000 operations per thread. Single run each; the 4-thread rows include
cache-line contention on shared counters by design and are noisy. Treat them as order of
magnitude only.

| Operation | COUNTERS, 1 thread (ns) | LEDGER, 1 thread (ns) | COUNTERS, 4 threads (ns) | LEDGER, 4 threads (ns) |
| --- | ---: | ---: | ---: | ---: |
| empty loop (baseline) | 1.0 | 1.4 | 13.8 | 40.2 |
| `counter.add()` by handle | 9.7 | 11.2 | 92.0 | 88.4 |
| `axmem_counter_add("name")` by name | 113.4 | 98.9 | 129.3 | 138.2 |
| `gauge.set()` by handle | 5.2 | 4.3 | 9.6 | 11.3 |
| `acquire` + `release` | 33.3 | 205.5 | 124.2 | 588.8 |

What this does and does not show:

- Handles are an order of magnitude cheaper than names; register once and keep the handle.
- `COUNTERS` resource hooks cost tens of nanoseconds; `LEDGER` hooks cost a mutex and a
  hash-table update (about 200 ns single-threaded, several times that under contention).
  Use `LEDGER` for short confirmatory runs, not as an always-on mode.
- The disabled mode is inline no-ops; compiler output was not inspected, so "zero cost" is
  not claimed.
- A camera SoC will be slower and memory-bound differently. Re-run on the target.

## Device procedure (proposed)

1. Build disabled, `COUNTERS`, `LEDGER` variants of the same application revision.
2. For each variant run T2 (steady video) for the same duration, at least twice, with the
   same phase markers; collect probe output plus host-side samples.
3. Compare throughput/latency, CPU, RSS slope, and `app.probe.*` health metrics.
4. Record the result in the run manifest and the report's limitations, per device model
   and firmware. Do not generalize across models.

## Collector overhead (M0001)

The host collector reports its own cost in every sample: `collector.cycle_duration_ns`,
`collector.reads_total_count`, `collector.read_errors_count`, `collector.bytes_read_bytes`.
To measure SSH overhead on a device, run the same collection with the intervals you intend
to use and compare the cycle duration against the interval; then compare a regular-only run
against one with frequent sparse reads. Per cycle the collector makes one SSH connection for
the regular reads, plus one for the fd listing and one for sparse files when due, so
connection setup dominates; if it is too costly, lengthen the interval rather than adding
persistent connections (not implemented). No device numbers exist yet.

## Allocation sampler overhead (M0004)

Host numbers for the `operator new` hook at several intervals, and the method, are in
`docs/12-allocation-sampling.md`, section 7. To measure on a device: run the same workload
with a build that does not link the hook, one that links it with the sampler stopped, and ones
that run it at the intervals you intend to use; compare throughput, CPU, and RSS, and read
`app.sampler.*` for dropped records. Sampling nearly every allocation costs roughly an order of
magnitude on a host; do not extrapolate to a camera. No device numbers exist yet.
