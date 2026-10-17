# Milestone 0004 — Allocation samples and symbolization

**Owner:** M0004. **Depends on:** M0003. **Status:** planned.

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
