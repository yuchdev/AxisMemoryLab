# Allocation sampling and symbolization

**Owner:** M0004. **Status:** implemented and tested on a Windows/MSVC host with synthetic
programs; the Linux paths (frame-pointer unwinder, ELF module table, ELF symbol resolution) are
exercised only by CI. Nothing here has run on a camera. **Development use only**: it replaces the
global `operator new`, costs memory and CPU, and must not ship in a production build.

Use it when counters (`docs/06`) show that application memory grows but not *where it was
requested*: it answers "which call sites request the memory that is still live?". It does not
answer "who keeps it alive?"; that needs the ledger, queue gauges, or code reading
(`docs/11-investigation-workflow.md`, S5 to S8).

## 1. What it does and does not cover

| Covered | Not covered |
| --- | --- |
| C++ `operator new`, `new[]`, nothrow and over-aligned forms, when `axis_memlab_new_hook` is linked into the executable | `malloc`, `calloc`, `realloc`, `mmap`, `brk` |
| Any allocator you instrument by hand with `axmem_sampler_record_alloc/free` | SDK, driver, DMA, and hardware buffers unless you instrument them |
| Allocations made after `axmem_sampler_start` | Allocations made before it (frees of those are only counted) |
| Raw program counters, size, alignment, kind, thread, time | Symbols, source lines, object contents, pointer values, command lines |

No single mechanism sees every allocator on AXIS OS. Do not read "no samples from this
subsystem" as "this subsystem does not allocate".

## 2. Design

### 2.1 Sampling by bytes

The gap between samples is drawn from an exponential distribution with mean
`sample_interval_bytes` (default 512 KiB). An allocation of `s` bytes is therefore sampled
with probability `P(s) = 1 - exp(-s / interval)`: big allocations are almost always seen,
small ones rarely, and a loop of tiny allocations is seen in proportion to the bytes it
requests. The count restarts after each sample (the process is memoryless, so this is exact).

Each sample carries `weight_count = 1 / P(s)`: the number of allocations of that size it stands
for. Then, over any subset of samples,

* estimated allocation count = sum of `weight_count`,
* estimated bytes = sum of `size * weight_count`

are unbiased estimates of the true totals for that subset. The exact total requested volume is
kept separately (sum of the sizes of every request, sampled or not) and reported in the
summary, which gives a built-in calibration: *estimated cumulative / exact* should be close to 1.

Rule of thumb: the relative standard error of an estimate built from `n` samples is about
`1 / sqrt(n)`; the report prints it and a tier (`low` under 5 samples, `medium` under 30,
`high` from 30). A smaller interval gives more samples and a higher cost.

| Interval | Samples per MiB requested (large objects) | When to use |
| --- | --- | --- |
| 512 KiB (default) | about 2 | Long runs; finds the big consumers; lowest cost |
| 64 KiB | about 16 | Medium runs; mid-sized leaks |
| 4 KiB | about 250 | Short, focused runs; expect a clearly visible slowdown |

### 2.2 Order of work in each `operator new`

1. Decide, from the byte counter, whether this request is sampled (a few instructions).
2. If it is: capture the call stack **now**, before allocating, so new-handler frames or
   allocator internals cannot appear in it.
3. Perform the **standard allocation**: the hook allocates from `malloc` (or an aligned
   allocator) in the `new_handler` retry loop of a conforming `operator new`. Failure throws
   `std::bad_alloc` for the throwing forms and returns `nullptr` for the nothrow forms
   (an exception escaping the handler also yields `nullptr` there); `size == 0` returns a
   unique non-null pointer; alignment is honoured and paired with the matching aligned
   release. Behaviour is the same with the sampler stopped.
4. Only if the allocation succeeded, attach the returned pointer to the sample and track it. A
   failed or throwing allocation leaves no sample and cannot leave the thread in a half-sampled
   state.

The hook does not forward to the C++ runtime's original `operator new` (that function is
replaced, not wrapped); it reproduces its documented behaviour. In `operator delete` (all
overloads) the sampler is told **before** the memory is released, so a recycled address can
never be matched against a stale sample.

### 2.3 Matching frees

Tracked (sampled) allocations live in a fixed lock-free hash table keyed by pointer (probe
length bounded at 64). A `delete` of an untracked pointer costs one hash and usually one load; of
a tracked one, it removes the entry and queues a `free` record. The host subtracts matched frees:
a sampled allocation without a recorded free is "live". Frees of untracked pointers are only
counted. If a free record is lost (ring full or output cap) the summary says so and the live
estimate is flagged as possibly too high.

### 2.4 Cost control and safety rules

* Hot path: no heap allocation, no stdio, no locks except one short mutex on a *sampled* event
  and no symbolization, demangling, or libc `backtrace()` anywhere on the device.
* No I/O on the allocation path: samples go to a fixed in-memory ring (two buffers of 1,024
  events); the application calls `axmem_sampler_flush()` from a control thread. Overflow is
  counted (`dropped_ring_full`), never silent, and an alloc whose record cannot be queued is not
  tracked either, so tracked and recorded stay identical.
* Reentrancy: any allocation made by the sampler itself, a flush, or a `new_handler` callback on
  the same thread passes straight through unsampled.
* Bounds: output file cap (`max_output_bytes`, default 4 MiB; room is reserved for a closing
  summary), live table (`max_live_samples`, power of two up to 16,384), stack depth up to 32.
* Static memory is on the order of 1 MiB (rings about 620 KB, table about 390 KB, line and module
  buffers about 45 KB), touched lazily. The library starts no thread and opens no socket.
* Exact counters are kept per thread (plain load+store for the first 63 threads; later threads
  share one slot with atomic adds).

### 2.5 Call stacks

| Target | Method |
| --- | --- |
| Linux x86-64, AArch64 | Walk the frame-pointer chain starting at `operator new`'s own frame. Each record is bounds-checked against the thread's stack (from `pthread_getattr_np`, cached) and must climb in steps of at most 1 MiB. Needs the **caller's code built with frame pointers** |
| Windows | `CaptureStackBackTrace`. A fixed skip count removes the hook frames; heavy inlining can shift it by a frame |
| Anything else (including 32-bit ARM) | The call site of `operator new` only (depth 1). The ARM frame layout is not walked; this is stated in the file header (`unwinder: caller_only`) |

### 2.6 Modules and build identity

The header (and a `modules` record when libraries are loaded later) lists each loaded binary by
**base name only**, its load base, extent, and **GNU build-id** (PE: timestamp and image size).
A program counter becomes `(module, pc - base)`, the address in that module's file. Directories
are never recorded.

## 3. File format

`alloc-samples-v1` JSON Lines, schema in `schemas/alloc-samples-v1.schema.json`:

| Record | Meaning |
| --- | --- |
| `header` | `run_id`, pseudonymous `device_id`, `pid`, clocks, interval, depth, `pointer_bits`, `arch`, `unwinder`, `modules` |
| `modules` | New module table after a load/unload (written at flush only if it changed) |
| `alloc` | `id`, `ts_mono_ns`, `size`, `align`, `kind`, `thread`, `weight_count`, `stack` (hex program counters) |
| `free` | `id` of a sampled allocation that was freed |
| `summary` | Exact `alloc_requests`, `alloc_request_bytes` (cumulative, not live), `free_requests`, sample and drop counters; `final: true` on stop |

Appending to an existing file starts a new **session** (a new header); ids restart per session
and the host keeps sessions apart. Addresses are code addresses only. `device_id` follows the
pseudonym rule and nothing in the file is free text.

## 4. Using it

Build (development builds only):

```bash
cmake -S . -B build/native -DAXMEM_COUNTERS=ON -DAXMEM_SAMPLER=ON    # or AXMEM_LEDGER=ON
```

`AXMEM_SAMPLER` is an add-on to `COUNTERS` or `LEDGER`; it is refused with `DISABLED` or alone.
When it is not compiled in, the functions in `axis_memlab/sampler.h` are inline stubs.

In CMake, link the hook into the **executable** (not a library loaded late) and build your own
code so that stacks can be walked and symbols kept:

```cmake
target_link_libraries(app PRIVATE axis_memlab_probe axis_memlab_new_hook axis_memlab_sampler_flags)
# axis_memlab_sampler_flags adds: -g -fno-omit-frame-pointer   (GCC/Clang)
```

```cpp
#include "axis_memlab/sampler.h"

axmem_sampler_config cfg{};
cfg.struct_size = sizeof cfg;
cfg.output_path = "/path/you/choose/allocs.jsonl";
cfg.run_id = "<uuid>";             // same run as the probe output, if you also use it
cfg.device_id = "<pseudonym>";
cfg.sample_interval_bytes = 65536;
axmem_sampler_start(&cfg);          // allocations before this call are invisible
// ... run the workload; from a control or timer thread, every few seconds:
axmem_sampler_flush();
// ... at the end:
axmem_sampler_stop();               // final flush and closing summary
```

For allocators the hook does not cover (a pool, an SDK buffer API), call
`axmem_sampler_record_alloc(ptr, size, align)` and `axmem_sampler_record_free(ptr)` at the
ownership boundaries; their stacks are those of the caller. `axmem_sampler_get_stats` returns the
exact counters. With a probe snapshot running, `app.sampler.*` metrics are added to it
(`docs/03-metrics-semantics.md`).

### Preparing binaries (build identity)

* Link with a build-id: `-Wl,--build-id` (GCC/Clang usually add it by default).
* Build the profiled application with `-g -fno-omit-frame-pointer`.
* Keep the **unstripped** binaries and libraries, and any separated debug files, on the
  workstation. Strip what goes on the camera:
  `objcopy --only-keep-debug app app.debug && strip --strip-unneeded app` (the build-id is
  preserved, so `app.debug` matches the stripped `app`).
* Never run symbolization on the device; the camera needs no symbols.

## 5. Host: `axis-memlab symbolize`

```bash
axis-memlab symbolize --samples allocs.jsonl --symbols ./symbols/ --top 20 --sort live
axis-memlab symbolize --samples allocs.jsonl --symbols ./symbols/ --format markdown --out sites.md
```

| Option | Meaning |
| --- | --- |
| `--symbols DIR` | Directory of unstripped binaries/debug files; matched to modules by **build-id found inside the file**, never by file name |
| `--tool auto|builtin|llvm-symbolizer|addr2line` | `auto` uses `llvm-symbolizer`, then `addr2line`, then the built-in ELF reader (function names only, no lines or inlined frames) |
| `--sort live|cumulative` | Rank sites by estimated live bytes (default) or cumulative bytes |
| `--skip-top N`, `--max-depth N` | Drop leading frames (for example allocator wrappers) or group by the first N frames |
| `--session N` | Session in the file (default: the last) |
| `--no-demangle` | Keep mangled names; otherwise `c++filt` is used if present |

Rules the resolver follows:

* A module is resolved only against a file with the **same build-id**. If a file with the same
  *name* but another build-id is all that exists, the frames are reported as `build_id_mismatch`.
* Return addresses are looked up one byte earlier, so a call that is the last instruction of a
  function is attributed to that function.
* Frames that cannot be resolved stay as `module+0xoffset` or a raw address; nothing is guessed.
* Tools are run with an argument list (no shell) on the matched file only; nothing is looked up
  online and the binaries are never executed.

### Reading the report

* **Live estimate** counts sampled allocations whose free was not recorded. **Cumulative
  estimate** counts everything ever allocated at the site. They answer different questions and are
  printed in separate columns; cumulative is never relabelled as live.
* Check the `calibration` ratio (estimate / exact requested volume). Far from 1 means too few
  samples or dropped records.
* Check `confidence` per site; a site with `low` confidence is a lead, not a measurement.
* Read the limitations: dropped records, a missing closing summary, shallow stacks, and
  unresolved frames each weaken specific conclusions and are listed with counts.

Typical next steps: a site with large live bytes and a stable stack is the place to ask "what
holds this?" (queue gauges, ledger, code review); a site with huge cumulative but zero live bytes
is churn, which matters for fragmentation and CPU, not for leaks.

## 6. Replaying on a workstation (sanitizers and heap profilers)

These run **off the camera**, on a build and workload you can replay. They perturb timing and
memory a lot and are not telemetry.

| Tool | Use | Typical use |
| --- | --- | --- |
| AddressSanitizer + LeakSanitizer | Memory errors and unreachable allocations at exit | `-fsanitize=address -fno-omit-frame-pointer -g`; run the replayed workload; `ASAN_OPTIONS=detect_leaks=1`. Finds *unreachable* leaks only: memory still referenced by a queue is not reported |
| `heaptrack` | Allocation history, peaks, leaks, flame graphs, per call site | `heaptrack ./app args`, then `heaptrack_print heaptrack.app.*.gz` |
| Valgrind Massif / DHAT | Heap profile over time; lifetimes and access patterns | `valgrind --tool=massif ./app` then `ms_print massif.out.*`; `valgrind --tool=dhat ./app` |

Limits to remember: they need a compatible workstation build and a reproducible input (video
replay); results differ from the camera's allocator and memory pressure; and **Valgrind cannot
reconstruct allocation history from `/proc` snapshots, `smaps` output, or a memory dump**. Heap
history must be recorded while the program runs, by these tools or by this sampler.

## 7. Perturbation and failure cases

Host microbenchmark (`axis_memlab_sampler_bench`, `axis_memlab_alloc_baseline_bench`), Windows
laptop (Intel Core i5-6300U), MSVC Release, `new char[n]` + `delete[]` in a loop, nanoseconds per
pair, minimum to maximum over three runs of 2,000,000 iterations. Flush time is excluded. In the
first run every 32-byte row, including the stopped hook, read about 3 µs; that is system noise
and those readings are left out. The machine is a laptop, so expect a few tens of percent of
run-to-run spread. These numbers describe a workstation, **not** a camera.

| Variant | 32 B | 256 B | 4096 B |
| --- | ---: | ---: | ---: |
| plain `operator new` (no hook) | 84-90 | 86-89 | 79-89 |
| hook linked, sampler stopped | 89-96 | 93-100 | 92-134 |
| interval 512 KiB | 103-141 | 100-118 | 108-113 |
| interval 64 KiB | 99-105 | 107-108 | 180-220 |
| interval 4 KiB | 113-129 | 181-199 | 947-979 |

Reading it: the linked-but-stopped hook typically costs 5-10%; sparse sampling adds roughly 15-50 ns
per pair; sampling nearly every allocation (4 KiB interval with 4 KiB objects) costs about 10x
because every sample walks a stack and queues a record. Measure on the target before choosing an
interval, and compare RSS and throughput with and without the hook
(`docs/10-benchmarking-overhead.md`).

Failure cases covered by tests: invalid configuration (no file created), double start, flush or
stop before start, full live table, full ring (tracked equals recorded), lost free events,
output cap (no torn lines, closing summary kept), failed and throwing allocations (no sample, no
wedged state), `new_handler` loops, nothrow forms, over-aligned forms, frees of memory from
before the sampler started, frees after stop, concurrent allocation with a concurrent flush, and
non-climbing, misaligned, out-of-range or junk frame chains in the unwinder.

## 8. Known gaps

* Linux paths (frame-pointer unwinder, `dl_iterate_phdr` module table, ELF symbol resolution of a
  real GCC binary) are compiled and tested by CI only; local development used MSVC.
* PE/Windows binaries are not symbolized (no PDB support); ELF only.
* 32-bit ARM frame chains are not walked (call site only); `glibc`-less or statically
  unusual targets are untested.
* The hook must be linked into the executable; a late-loaded shared library may allocate while
  thread-local storage is being set up. Replacing global `operator new` also affects every
  library in the process.
* Exceptions disabled: a failing throwing `new` aborts instead of throwing.
* Not provided: sampling of `malloc`/`mmap`, on-device symbolization (by design), allocation
  *timing* statistics beyond the sample timestamps.
