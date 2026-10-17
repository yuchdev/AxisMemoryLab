# Milestone 0003 — In-app profiling

**Owner:** M0003. **Depends on:** M0000 and M0001. **Status:** implemented and host-tested (MSVC); device acceptance open (see below).

Implement opt-in application counters and lifecycle hooks with measured
overhead and explicit ownership boundaries. Acceptance requires SDK-independent
tests, documented integration constraints, disabled default behavior, and no
unconditional VDO/Larod ownership assumptions.

## Planned work from the memory-growth playbook

Generic `app.<name>` counters and an opt-in lifetime ledger as described in
`docs/06-integrating-cpp-probes.md`; VDO/Larod counters only as examples.
Measure overhead per `docs/10-benchmarking-overhead.md`.

## Delivered

- ABI v2 (`native/include/axis_memlab/probe.h`): exactly one of `AXMEM_DISABLED`,
  `AXMEM_COUNTERS`, `AXMEM_LEDGER` per build; combining modes, selecting none, or
  requesting `AXMEM_SAMPLER` fails at configure time. Disabled mode is header-only
  no-ops.
- Counters and gauges by handle (relaxed atomics, no lock, no allocation) or by name;
  names validated as `app.[a-z0-9_.]+`; resource kinds with per-kind acquired, released,
  and in-flight totals; LEDGER mode adds exact in-flight bytes, high-water mark,
  duplicate-acquire and unmatched-release counts, overflow accounting with a `degraded`
  flag, and the oldest live ids in `annotations.ledger`.
- `record-v1` JSON Lines output (file sink, size cap, never partial lines), phase
  markers, process memory from `/proc/self` (`status`, opt-in `smaps_rollup` and fd
  count), `boot_id` and start ticks in the identity, optional glibc `mallinfo2`, and probe
  self-metrics (`app.probe.*`).
- Tests: parser, registry, snapshot, output cap, ledger (including concurrency and a
  model-checked overflow/wrap-around test), examples, and an end-to-end test that feeds
  the simulator's output through the Python analysis (`tests/integration/test_native_probe.py`).
- Design record: `docs/decisions/0001-tech-notes-reconciliation.md`. Usage:
  `docs/06-integrating-cpp-probes.md`. Overhead method and host numbers:
  `docs/10-benchmarking-overhead.md`.

## Open acceptance items

- Nothing has run on a camera: device overhead (CPU, peak RSS, throughput) and the
  < 1 MiB counter-only goal are unmeasured on hardware.
- Linux builds with gcc and clang are exercised only by CI; local development used MSVC,
  so the `/proc` reads were tested through parsers on synthetic text, not live.
- Real VDO and Larod adapters need the SDK and the application's ownership rules; only
  SDK-free patterns and stand-in examples exist (M3-S04, M3-S05).
- `malloc_info()` XML export (development only), ledger release latency and caller
  stage, optional sampling for very large populations, and `mmap`-region count.
- A stage-isolation guide (switches for acquisition, conversion, inference, results,
  upload, diagnostics; queue caps; test-triggered drain) in `docs/06` *(added)*.
- Decision pending: an optional emitter helper (low-priority thread) or outbound
  telemetry; the library currently has neither by design.

## Stories and status

| Story | Status |
| --- | --- |
| M3-S01 C ABI, RAII wrappers, off/counters/ledger modes | done |
| M3-S02 procfs self-sampling, bounded JSONL, no frame-path I/O | done |
| M3-S03 bounded ledger, overflow accounting, optional sampling | done except sampling |
| M3-S04 VDO adapter | pattern and stand-in example only |
| M3-S05 Larod adapter | pattern only |
| M3-S06 queues, images, recognition, network, workers | done as generic gauges/counters and `queue_metrics` example |
| M3-S07 overhead measurement and defect simulator | simulator and host benchmark done; device measurement open |
