# Integrating C/C++ probes

**Owner:** M0003. **Status:** implemented and host-tested; not yet run on a camera. The ABI
(version 2) is provisional, not frozen. Design decisions:
`docs/decisions/0001-tech-notes-reconciliation.md`.

The probe is an SDK-free C ABI with a C++17 wrapper. It records what the application
declares about its own counters and resource lifetimes, and writes `record-v1` JSON Lines.
It never owns, extends, or reorders a resource release, never assumes how VDO or Larod
objects are owned, opens no network connection, and starts no thread.

## 1. Build modes

Select exactly one base mode per build (none or several is a configure error); `AXMEM_SAMPLER` may be added to COUNTERS or LEDGER:

| Option | What you get | Hot-path cost |
| --- | --- | --- |
| `-DAXMEM_DISABLED=ON` | Inline no-ops; nothing to link; `axmem_emit_snapshot()` returns `AXMEM_STATUS_DISABLED` | none |
| `-DAXMEM_COUNTERS=ON` | Counters, gauges, per-kind acquired/released/in-flight **counts**, snapshots | relaxed atomics, no lock |
| `-DAXMEM_LEDGER=ON` | `COUNTERS` plus an identity ledger: exact in-flight **bytes**, high-water mark, duplicate and unmatched detection, oldest live ids | one mutex per acquire/release |
| `AXMEM_SAMPLER=ON` (add-on) | Statistical allocation sampling and the opt-in `operator new` hook; needs COUNTERS or LEDGER, refused with DISABLED. See `docs/12-allocation-sampling.md` | sampled events only; development builds |

```bash
cmake -S . -B build/native -DAXMEM_LEDGER=ON
cmake --build build/native --parallel && ctest --test-dir build/native --output-on-failure
```

Link `axis_memlab_probe` (or compile `native/src/*.cpp` into your target) and define the
same mode macro (`AXMEM_COUNTERS=1` or `AXMEM_LEDGER=1`) for the code that includes the
headers. Mixing a header mode with a library built in another mode is not detected at
link time; `axmem_mode()` reports what the library was built with.

## 2. Using it

```cpp
#include "axis_memlab/probe.hpp"

// Once, at start-up (not per frame): register names and keep the handles.
axis_memlab::Counter frames("app.frames_total_count");
axis_memlab::Gauge   results_depth("app.queue.results_depth_count");
axis_memlab::ResourceKind frame_kind("frame");

axmem_config cfg{};                        // zero-initialised
cfg.struct_size = sizeof cfg;
cfg.output_path = "/path/you/choose/records.jsonl";
cfg.run_id      = "<uuid>";                // from the test driver
cfg.device_id   = "<pseudonym>";           // never a serial number, address, or user name
cfg.include_fd_count = 1;                  // optional, cheap
cfg.include_smaps_rollup = 0;              // optional, costs a page-table scan per snapshot
if (axmem_init(&cfg) != AXMEM_OK) { /* run without the probe */ }

// Hot path: no I/O, no allocation.
frame_kind.acquire(frame_id, bytes);       // where the application takes ownership
frames.add();
frame_kind.release(frame_id);              // where it gives ownership up: on EVERY path

// Control or timer thread, every 10-15 s: file I/O happens here.
axmem_phase_marker("T2");                  // at test-phase boundaries
axmem_emit_snapshot();
```

Rules enforced by the library:

- Metric names match `^app\.[a-z0-9_.]+$` (at most 64 characters), so output always
  validates against `schemas/record-v1.schema.json`. A name ending in `_bytes` is exported
  in bytes, `_ns` in nanoseconds, anything else as a count. Invalid names return an inert
  handle and are counted in `app.probe.registration_rejected_count`.
- At most 128 counters/gauges and 16 resource kinds (fixed tables, no allocation after
  start-up). A name cannot be both a counter and a gauge.
- `device_id` is restricted to `[A-Za-z0-9._-]` (at most 64 characters), `run_id` must be
  a UUID, phases match `[A-Za-z0-9_.:-]{1,48}`. The library has no free-text fields, so
  frame data, plate text, credentials, and addresses cannot be written by accident.
- The output file is capped (`max_output_bytes`, default 4 MiB). At the cap, snapshots
  return `AXMEM_ERR_LIMIT`, nothing partial is written, and the drop is counted.
- Unreadable process memory is exported as `{available:false, reason}`, never as zero.

## 3. What a snapshot contains

| Group | Metrics |
| --- | --- |
| Your counters and gauges | exactly the names you registered |
| Process (`/proc/self`) | `process.rss_bytes`, `rss_anon_bytes`, `rss_file_bytes`, `rss_shmem_bytes`, `vm_swap_bytes`, `threads_count`; with `include_smaps_rollup`: `pss_bytes`, `private_clean_bytes`, `private_dirty_bytes`, `anonymous_bytes`, `swap_bytes`; with `include_fd_count`: `fd_count` |
| Resource kinds | `app.resource.<kind>.acquired_total_count`, `released_total_count`, `in_flight_count`, `in_flight_bytes` (LEDGER; unavailable in COUNTERS), `high_watermark_bytes` (LEDGER) |
| Ledger (LEDGER) | `app.ledger.capacity_count`, `live_count`, `events_dropped_count`, `duplicate_acquire_count`, `unmatched_release_count`, `degraded`; `annotations.ledger.oldest_live` lists up to 8 oldest live resources with kind, id, sequence, bytes, age |
| Allocator (opt-in, glibc 2.33+) | `app.allocator.arena_bytes`, `in_use_bytes`, `free_bytes`, `mmapped_bytes`; unavailable elsewhere. `mallinfo2` takes the arena lock: development only |
| Probe health | `app.probe.snapshots_emitted_count`, `snapshots_dropped_count`, `registration_rejected_count`, `rejected_calls_count`, `output_bytes`, `snapshot_duration_ns`, `metric_slots_used_count` |

Identity carries `device_id`, `pid`, `process_start_ticks`, and `boot_id` when readable, so
the analysis segments on restarts automatically.

Data-quality flags to check before trusting a run: `app.ledger.degraded = 1`,
`unmatched_release_count > 0`, `duplicate_acquire_count > 0`, `snapshots_dropped_count > 0`,
`rejected_calls_count > 0`.

## 4. Where the hooks belong

1. **At ownership boundaries only.** Acquire where the application takes ownership, release
   where it gives it up. A hook in a middle stage that sees the same resource again double
   counts.
2. **On every exit path**, including timeouts, early returns, and error branches. Missing
   release hooks on error paths are the usual cause of a false "leak" in the ledger.
3. **Use `ResourceGuard` only for scope-bound ownership.** For ownership that crosses
   threads or sits in a queue, call `acquire`/`release` at the real boundaries.
4. **Stable ids.** Use an id that is unique among live resources of the kind (a sequence
   number, not a raw pointer that the allocator may reuse immediately).
5. **Do not change lifetimes.** A hook must not hold a reference, delay a release, or add
   a lock around the SDK call it observes.
6. **Bytes are what the application declares.** The probe cannot verify them.

## 5. SDK-specific placement (patterns, not drop-in code)

`native/examples/vdo_lifecycle.cpp` shows the shape with a stand-in stream type; it is
**not** the VDO API. Before hooking a real SDK call, read the exact free/unref sequence and
the buffer-lifetime rules of the SDK generation in use.

- **VDO video buffers.** Acquire when the SDK hands the buffer to the application; release
  directly after the call that returns it. Axis lists a `vdo_buffer_get_data` leak on some
  ARTPEC firmware (`docs/01-axis-compatibility.md`): a rising in-flight count after the
  release call is not necessarily your code, so repeat on a firmware outside that range.
- **Larod tensors and jobs.** Larod 3 changes who frees buffers and how DMA buffers are
  synchronised. Hook the destruction calls of the generation you build against; do not
  reuse hooks written for another generation. Count jobs submitted/completed and tensors
  active as separate kinds or counters.
- **Image conversion, queues, results, network retry buffers.** Use gauges for depth and
  bytes at the queue's own push/pop (`native/examples/queue_metrics.cpp`), a counter for
  drops, and `watermark` for high-water marks.
- **Threads.** A gauge for worker count; `process.threads_count` is exported for you.

## 6. Isolating stages (test builds)

To tell a backlog from a leak, make each stage independently switchable in a test build:
acquisition, conversion, inference, result queue, event/network upload, and diagnostics.
Each toggle needs a defined bypass behaviour (for example, drop the frame at the boundary
and release it) and a phase marker when it flips. Add controls for the maximum queue count
and bytes, and a test-triggered drain. Then compare acquisition-only with the full pipeline
and re-enable stages one at a time (`docs/11-investigation-workflow.md`, S6). These toggles
belong to the application; the probe only reports their effect.

## 7. Allocator experiments

`mallinfo2` stats are exported when asked and available. `malloc_info()` XML,
`malloc_trim(0)`, and allocator swaps are development-only experiments run by the
application owner on a lab unit: a trim that lowers RSS suggests allocator retention, not
the absence of a leak, and it can perturb the workload. The library deliberately offers no
trim call. For call-site attribution of allocations use the sampler (`docs/12-allocation-sampling.md`).

## 8. Limits and known gaps

- Developed and tested on MSVC; Linux gcc/clang builds are exercised only by CI, and the
  `/proc` paths are verified through parsers on synthetic text.
- No device measurements of CPU, peak RSS, or throughput exist; see
  `docs/10-benchmarking-overhead.md` for the method and host-only numbers.
- Headers use no exceptions or RTTI; `probe.cpp` uses `std::string` and `std::mutex`, but
  only in snapshot, init, and ledger paths, never in counter or gauge updates.
- Not yet provided: `malloc_info()` export, release latency per resource, sampling of very
  large populations, an optional emitter thread, and real VDO/Larod adapters
  (`docs/roadmap/0003-inapp-profiling.md`).
