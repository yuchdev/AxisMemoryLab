# Milestone 0004 — Allocation samples and symbolization

**Owner:** M0004. **Depends on:** M0003. **Status:** implemented and host-tested (MSVC); Linux paths and device acceptance open.

Specify bounded allocation samples and offline address resolution. Acceptance
requires synthetic stacks, privacy controls, symbol/build identity checks, and
no proprietary binaries or online symbol lookup.

## Scope carried from the tech notes

Traceability: `docs/roadmap/tech-notes-coverage.md`. *(added)* = not named here before
that review.

- Sampler (`AXMEM_SAMPLER`): bounded stacks, matched alloc/free events, conservative
  outstanding estimates, no symbolization, demangling, or `backtrace()` on the device,
  no malloc recursion, and an explicit coverage statement (no single mechanism sees every
  allocator, `new`, `mmap`, or SDK hardware buffer). If hooks are unsafe, instrument
  chosen call sites instead.
- Resolution on the workstation with `addr2line`, `llvm-symbolizer`, or `gdb`; a
  build-id mismatch rejects resolution instead of producing wrong symbols.
- Build guidance: frame pointers or preserved unwind metadata in profiling builds, and
  exact unstripped build-id-matched symbols kept off the camera *(added)*.
- Host replay instructions for AddressSanitizer/LeakSanitizer, `heaptrack`, Valgrind
  Massif and DHAT. State that Valgrind cannot reconstruct history from `/proc` snapshots
  or arbitrary dumps *(added)*.

## Delivered

- **Sampler** (`AXMEM_SAMPLER`, an add-on to COUNTERS or LEDGER; refused with DISABLED or
  alone): sampling by bytes with exponential gaps and `1 / P` weights, exact cumulative counters,
  a lock-free table of tracked allocations, matched frees recorded before release, a fixed ring
  flushed by the caller, and bounded output with a reserved closing summary. Every limit is
  counted. API: `native/include/axis_memlab/sampler.h` (inline stubs when not compiled in).
- **`operator new` hook** (`axis_memlab_new_hook`, opt-in object library): all `new`, `new[]`,
  nothrow, and over-aligned forms and every `delete` overload; records the stack before the
  allocation, performs the standard allocation (`new_handler` loop, `bad_alloc`, nothrow,
  alignment, zero size), then attaches the pointer; a failed or throwing allocation leaves no
  sample.
- **Stacks and modules:** bounds-checked frame-pointer walker (Linux x86-64, AArch64),
  `CaptureStackBackTrace` (Windows), call-site-only fallback; module table with base names and
  GNU build-ids; stated in the file header (`unwinder`).
- **Host:** `axis-memlab symbolize` (`symbolization/`): `alloc-samples-v1` loader, defensive ELF
  reader (build-id, `.symtab`/`.dynsym`, ELF32/64 little-endian), build-id-only symbol matching
  with explicit `build_id_mismatch`/`no_symbols` states, optional `llvm-symbolizer`/`addr2line`
  (inlined frames, file and line) and `c++filt`, site aggregation with live and cumulative
  estimates kept apart, confidence tiers, calibration against the exact counter, and a `report-v1`
  output with Markdown rendering. Schema: `schemas/alloc-samples-v1.schema.json`.
- **Documentation:** `docs/12-allocation-sampling.md` (design, usage, build guidance for
  symbols and frame pointers, host replay with AddressSanitizer/LeakSanitizer, heaptrack,
  Massif, DHAT, the Valgrind limitation, perturbation numbers, failure cases).
- **Tests:** stack walker on synthetic stacks, estimator accuracy and determinism, hook
  semantics, multi-thread stress with concurrent flush, limits, ELF reader on synthetic ELF files,
  resolver and tool parsers, report honesty, CLI, and an end-to-end test from the C++ demo through
  the host estimates.

## Open acceptance items

- **Linux is CI-verified only.** The frame-pointer unwinder, `dl_iterate_phdr` module table, and
  ELF resolution of a real GCC/Clang binary (the exit criterion: known synthetic allocations
  resolve to functions on the host) have been exercised on Windows/MSVC with synthetic ELF files,
  and on Linux only through the CI jobs and `test_sites_resolve_to_the_demo_functions`.
- No camera: perturbation (CPU, RSS, throughput) is measured on a laptop only
  (`docs/12`, section 7). 32-bit ARM stacks are not walked (call site only).
- No PE/PDB symbolization; no `gdb` integration (the built-in reader, `llvm-symbolizer`, and
  `addr2line` cover resolution; `gdb` stays a manual alternative).
- Not covered by design: `malloc`, `mmap`, SDK and DMA buffers (use the manual call-site API).
- The hook must be linked into the executable; late-loaded shared libraries are unsupported.

## Stories and status

| Story | Status |
| --- | --- |
| M4-S01 sampler safety design, coverage specification, feature gating | done (`docs/12`, sections 1-2; add-on build flag) |
| M4-S02 bounded stack capture for hooks or call sites | done (hook and manual API; Linux unwinder CI-verified) |
| M4-S03 matched alloc/free with conservative outstanding estimates | done (live and cumulative kept apart, confidence, calibration) |
| M4-S04 build-id tracking, symbol lookup, off-camera demangling | done (ELF); PE not supported |
| M4-S05 sanitizers and heaptrack/Massif instructions | done as documentation (`docs/12`, section 6) |
| M4-S06 CPU/RSS perturbation and failure cases | host numbers and failure tests done; device measurement open |
