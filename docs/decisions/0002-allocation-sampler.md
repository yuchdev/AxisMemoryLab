# Decision 0002: allocation sampler and symbolization

Date: 2026-10-17. Applies to milestone 0004. Design and usage: `docs/12-allocation-sampling.md`.

## Decisions

**Sample by bytes with exponential gaps.** The gap between samples is exponentially distributed
with a configured mean, so an allocation is sampled with probability `1 - exp(-size / interval)`
and each sample carries the weight `1 / probability`. Sums of weighted samples are then unbiased
for any subset, large objects are never missed, and the cost scales with bytes requested, not with
allocation count. The alternative (every Nth allocation) over-samples tiny objects and has no
simple unbiased estimator. An exact cumulative counter kept for every request calibrates the
estimate and exposes dropped samples.

**Standard `operator new` behaviour is reproduced, not wrapped.** Replacing the global operator
removes the runtime's original, so the hook implements the documented behaviour (`new_handler`
loop, `bad_alloc`, nothrow, alignment, zero size) on top of `malloc`/aligned allocation, and the
deallocation overloads release with the matching function. A `dlsym(RTLD_NEXT)` forwarder would
call the original but works only for a preloaded shared object, not for a statically linked
executable or on MSVC; it was not built.

**Capture the stack first, attach the pointer last.** The stack is recorded before the allocation
so allocator and handler frames cannot appear in it; the pointer is attached only after success,
so a failed or throwing allocation leaves no sample. In `delete` the sampler runs before the
release so a recycled address cannot match a stale sample.

**No I/O on the allocation path; caller-driven flush.** Samples go to a fixed ring written only by
`axmem_sampler_flush()`, consistent with decision 0001 (no library threads). Overflow of the ring,
the live table, and the output file is counted and reported rather than hidden; tracked samples
and recorded samples are kept identical so the live estimate cannot silently include allocations
whose records were lost.

**Frame-pointer unwinding, bounds-checked.** No libc `backtrace()` (it can allocate) and no
`libunwind` dependency. Frame records are read only inside the thread's stack bounds and must climb
in small steps. This needs frame pointers in the profiled code, which the build guidance and the
`axis_memlab_sampler_flags` target provide. Targets without a supported walker record the call
site only and say so in the header.

**Addresses on the device, names on the host.** Samples hold raw program counters and per-module
base names with build-ids; nothing is symbolized or demangled on the device. The host resolves a
module only against a symbol file whose build-id equals the module's, found by content, never by
file name, and reports `build_id_mismatch` instead of resolving against the wrong build.

**Live and cumulative are separate quantities.** The report keeps them in separate fields and
columns, ranks by either on request, and states that cumulative volume is not live memory.
Per-site confidence tiers and a calibration ratio keep thin evidence from reading as fact.

**Add-on, not a mode.** `AXMEM_SAMPLER` builds on COUNTERS or LEDGER so one snapshot file can
carry both; it is refused with DISABLED or alone. The hook that replaces the global allocation
functions is a separate opt-in object library.

## Consequences

- Coverage is C++ `operator new` and explicit call sites only; the report says so every time.
- Linux behaviour (unwinder, module table, ELF resolution of a real binary) is verified by CI, not
  by the local MSVC environment.
- ELF only on the host; PE/PDB symbolization is out of scope.
