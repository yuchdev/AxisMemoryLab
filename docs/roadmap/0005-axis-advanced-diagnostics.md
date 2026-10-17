# Milestone 0005 — AXIS advanced diagnostics

**Owner:** M0005. **Depends on:** M0001–M0004 and verified compatibility. **Status:** planned.

Add only evidence-backed platform diagnostics after compatibility validation.
Acceptance requires documented firmware/SoC/SDK evidence, least privilege,
bounded overhead, and explicit unsupported cases.

## Planned work from the memory-growth playbook

Level 3 and 4 diagnostics (`docs/05-collecting-on-axis.md`) are gated on
verified per-firmware capabilities, including which `ptrace`, `debugfs`,
`perf`, and eBPF facilities AXIS OS 12 actually permits. Device Data Hub topics
are alpha maturity and supplementary only.

## Scope carried from the tech notes

Traceability: `docs/roadmap/tech-notes-coverage.md`. *(added)* = not named here before
that review.

- Scoped `strace` (mmap/munmap/brk and fd syscalls; not a source of `malloc` sites) on a
  lab unit where ptrace is permitted *(added)*.
- Kernel slab accounting and DMA-BUF debugfs as lab-only evidence, with the capability
  check first *(added)*.
- Guidance for process core dumps and full memory dumps: intrusive, large, and likely to
  contain private CCTV data, so not ordinary telemetry *(added)*.
- State the kernel-attribution rule: `kmalloc` and page-allocation events do not identify
  userspace `malloc` sites or object types, and a PID on such an event is not proof of
  long-term ownership *(added)*.
- Axis device server report: ingestion procedure and redaction (M5-S05).
- The redacted escalation bundle (manifests, reports, plan, reproducer, unreadable-source
  list) is owned here with `docs/09-customer-escalation.md`; it moved from the tech
  notes' M2-S05.
- Safety review for `deep` captures: full `/proc/PID/smaps`, full fd classification beyond
  counts, and allocator reports. Today `allow_deep_snapshot=true` is rejected and
  `snapshot --level deep` exits 3. Enabling them needs an explicit change to the configuration
  safety model, a size and time budget, a refusal under memory pressure, and local-only
  handling of mapping names and paths. M0002-S03 differential reports depend on this.
