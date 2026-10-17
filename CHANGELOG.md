# Changelog

## Unreleased — Milestone 0005

Evidence-gated advanced diagnostics and escalation. `axis-memlab advanced list | evidence | check |
import-ddh`: a catalog of 12 Level 3-4 diagnostics, a compatibility evidence record
(`compat-evidence-v1`) and a fail-closed per-firmware gate (deep captures never allowed), a
mapping-driven Device Data Hub importer. Analysis: shared-buffer, DMA-buffer-handle, kernel-slab,
and cgroup-charge hypotheses. `axis-memlab bundle`: minimal, scanned, redacted, hash-verified
escalation bundles with server-report handling. Guides: `docs/13`, `docs/09`, decision 0003
(deep captures stay blocked). New `axis_memlab_virtual_camera` (synthetic CCTV pipeline with five
injectable defects) and the Orange Pi 5 virtual-board deployment (`docs/device-optional/`, Tier 1
confined process, Tier 2 QEMU VM) with dry-run-tested scripts. `collect --run-id`; Linux live
`/proc` test; the repository root `CMakeLists.txt` (with `enable_testing()`) is now the CMake entry
point. README gains requirements for the new tools and a refreshed Lab Tools chapter. No
advanced diagnostic has run on a device.

## Unreleased — Milestone 0004

Allocation sampling and offline symbolization. Native: `AXMEM_SAMPLER` add-on (byte-interval
Poisson sampling with unbiased weights, exact cumulative counters, tracked-sample/free
matching, bounded ring/table/output, frame-pointer and `CaptureStackBackTrace` unwinders, module
table with build-ids) and the opt-in `axis_memlab_new_hook` that replaces global
`operator new`/`new[]`/`delete` with standard semantics. Host: `axis-memlab symbolize` with a
defensive ELF reader, build-id-only symbol matching, optional `llvm-symbolizer`/`addr2line`/
`c++filt`, live-versus-cumulative site ranking with confidence, and an `alloc-samples-v1` schema.
Guide `docs/12`; sanitizer/heaptrack/Massif replay instructions; host overhead numbers.
README gains external requirements for sampling. Linux paths are CI-verified only.

## Unreleased — Milestone 0001

Host collection: read-only allowlisted `/proc` and cgroup parsers, local and SSH readers
(system `ssh`, host keys verified, batched reads), capability discovery, append-only run
store with gzip and retention, scheduler with sparse cadence, triggers, memory-pressure
skip/abort and backoff, and the commands `discover`, `collect`, `annotate`, `snapshot`
(sparse only), `import`, `purge`. Contract additions: `reason_code`, capability/error/event
shapes, `collector.*` namespace, manifest fields. README gains external requirements; new
runbook (`docs/05`), metric registry (`docs/03`), demo run. Fixture-tested only; deep
captures stay blocked.

## Unreleased — Milestone 0003

Native probe: `AXMEM_COUNTERS` and `AXMEM_LEDGER` modes (ABI v2), JSON Lines snapshots
that validate against `record-v1`, `/proc/self` process memory, identity ledger with
overflow accounting, examples, host benchmark, and an end-to-end test from the C++
simulator into the Python analysis. Investigation workflow (`docs/11`), tech-notes
coverage matrix, and a decision record. Host-tested with MSVC only; no device
measurements.

## Unreleased — Milestone 0002

`analyze`, `compare`, and `report` commands: segment/phase-aware robust trends, normalized
growth, controlled comparison, correlation, hypothesis findings, and Markdown/HTML/CSV/JSON
reports. Offline and synthetic-validated; depends on the not-yet-implemented M0001.

## 0.0.0 — Scaffold

Initial host CLI, safety-checked example configurations, provisional schemas,
synthetic fixtures, and disabled-only native API.
