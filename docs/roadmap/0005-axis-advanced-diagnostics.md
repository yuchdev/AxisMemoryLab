# Milestone 0005 — AXIS advanced diagnostics

**Owner:** M0005. **Depends on:** M0001–M0004 and verified compatibility. **Status:** implemented as a gate, importers, rules, a bundle, and guides, tested on synthetic
data; **acceptance open: no device evidence exists**.

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

## Delivered

- **Evidence-gated diagnostics** (`src/axis_memlab/advanced/`): a catalog of 12 Level 3-4
  diagnostics (what each shows, what it cannot, risks, lab and Developer Mode requirements), a
  compatibility evidence record (`schemas/compat-evidence-v1.schema.json`, created from a run with
  `axis-memlab advanced evidence`), and a fail-closed gate (`advanced check`): per exact firmware,
  verified-available only, a stated method, lab-unit and Developer Mode where required, and never
  for deep captures. `advanced list` prints the catalog.
- **DDH adapter, generic** (`sources/ddh.py`, `advanced import-ddh`): mapping-driven import of
  captured Device Data Hub messages as `system.ddh.*`, with topic and maturity as provenance and
  explicit unavailable states. No payload shape is assumed.
- **Platform correlation** (`analysis/classify.py`): `H-SHARED-BUFFERS`, `H-DMABUF-HANDLES`
  (rule E), `H-KERNEL-SLAB` (rule D), `H-CGROUP-CHARGE`, each with alternatives and the next
  comparison, and lab-only follow-ups routed through the gate. Closes M0002 rules D and E.
- **Root-cause pack / escalation bundle** (`bundle/`, `axis-memlab bundle`): minimal, scanned,
  redacted, hash-listed, verifiable; server-report handling; sensitive-run review gate. Docs:
  `docs/09-customer-escalation.md`.
- **Guides** (`docs/13-advanced-diagnostics.md`): Device Data Hub, server report, scoped `strace`,
  `gdbserver` and Developer Mode (manual only), `perf`, `ftrace`/eBPF, slab and DMA-BUF debugfs,
  core dumps (with the Valgrind limitation), the kernel-attribution rule, and one list of what is
  unsupported or unverified.
- **Deep-capture safety review** (`docs/decisions/0003-advanced-diagnostics.md`): decision to keep
  them blocked, with the conditions for revisiting.
- **Virtual CCTV board:** `axis_memlab_virtual_camera` (synthetic pipeline with five injectable
  defects, instrumented with the probe, ledger, and sampler) and the Orange Pi 5 deployment guide
  and scripts (`docs/device-optional/`), tested by dry runs and static checks; Tier 1 (confined
  process) and Tier 2 (QEMU VM).
- **Also:** `collect --run-id` (so application records can be imported into a collection run), a
  Linux live-`/proc` test, and the local reader no longer counts its own directory handle.

## Open acceptance items

- **No firmware/SoC/SDK evidence exists.** The record format, the gate, and the procedures are
  ready; the first evidence needs an authorized lab unit. Every diagnostic is therefore blocked
  today. Bounded overhead of any advanced diagnostic is unmeasured.
- Not implemented, needs a device: a firmware-specific DDH mapping; which of `ptrace`,
  `perf_event`, tracefs, debugfs, BPF, and root-only files are reachable on AXIS OS 12;
  vendor-approved `perf`/`ftrace`/eBPF recipes; the server report in a machine-readable form.
- "Platform services" correlation (memory of *other* Axis services) needs the all-process summary
  that M0001 still lists as open.
- Deep captures and the M0002-S03 differential `smaps`/fd reports stay blocked (decision 0003).
- The Orange Pi 5 scripts have not been run on a board; the guide's verification log is empty.
- Items that need a camera attached to the board or a real camera are listed as Optional/TODO in
  `docs/device-optional/README.md`, section 11.

## Stories and status

| Story | Status |
| --- | --- |
| M5-S01 Device Data Hub adapter | generic mapping importer done; firmware-specific mapping needs a device |
| M5-S02 Developer Mode / `gdbserver` guide, no automatic activation | done (guide and gate); nothing run |
| M5-S03 platform service, cgroup, shared-buffer correlation with capability checks | rules and gate done; other-service memory needs the M0001 all-process summary |
| M5-S04 vendor-approved `perf`/`ftrace`/eBPF guides | generic guide and gate done; vendor recipes need a lab image |
| M5-S05 root-cause pack | bundle, evidence, and server-report handling done |
