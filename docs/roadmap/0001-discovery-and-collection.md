# Milestone 0001 — Discovery and collection

**Owner:** M0001. **Depends on:** M0000. **Status:** planned.

Refine and freeze the record protocol; discover capabilities without assuming
firmware, permissions, or procfs availability; implement bounded, read-only
collection and immutable annotations. Acceptance requires explicit capability
and unavailable states, safe timeouts, synthetic tests, and verified platform
compatibility. Device work must remain opt-in and least-privileged.

## Planned work from the memory-growth playbook

- Extend the run manifest with camera model, SoC, SDK generation, libc, workload
  (resolution, FPS, codec), and a test-case identifier; keep `device_identity`
  pseudonymous.
- Define the `capability` record payload and an event/annotation convention for
  phase markers and run-segment boundaries.
- Add trigger thresholds and a memory-pressure abort setting to configuration.
- Publish a metric-name registry in `docs/03-metrics-semantics.md`.
- Record collector self-timing and read errors.
- Populate `docs/01-axis-compatibility.md` from device evidence only.

## Scope carried from the tech notes

Traceability: `docs/roadmap/tech-notes-coverage.md`. Items marked *(added)* were not named
here before that review.

- Host parsers for `meminfo`, `vmstat`, `stat`, `status`, `smaps_rollup`, PSI; `SwapPss`
  and private hugetlb fields *(added)*; conditional cgroup v1/v2 source *(added)*.
- Triggered inventories: `fd` targets and `fdinfo` *(added)*, `maps`/`smaps` once per
  trigger, and an accessible-process summary that never assumes `pidof`/`pgrep`
  *(added)*. The `deep` path needs an explicit opt-in and confirmation; the config
  currently rejects `allow_deep_snapshot` and must keep doing so until then. Full `smaps`
  is never a fallback for a missing `smaps_rollup`.
- Read-only access to the Axis application log / `journalctl` for lifecycle markers
  *(added)*; operator-exported device server report procedure in the runbook *(added)*.
- Typed absence reasons (`missing`, `permission_denied`, `timeout`, `parse_error`,
  `unsupported`, `not_collected`) as a closed set in the record protocol *(added)*.
- SSH transport: dedicated key, host-key validation, connect and command timeouts,
  exponential backoff, audit record, clean close; benchmark SSH overhead on a device and
  compare a single multi-read command with a persistent connection.
- Run store: atomic append, valid after abrupt disconnect, compressed, with retention
  and purge tooling *(added)*; manifest gains `privacy_level`, consent or incident id,
  redaction status, and workload/config hash *(added)*.
- Reconcile configuration with the reference profile set (`lightweight`, `standard`,
  `lab`) and its separate deep-snapshot caps; see the table in the coverage matrix
  *(added)*.
- `examples/demo-run`: a fixture-only run that exercises every command without a device
  *(added)*; optional gated hardware CI job.
- `device-optional/tiny-probe` only if agentless SSH and the in-app probe prove
  insufficient.

## Stories and status

| Story | Status |
| --- | --- |
| M1-S01 compatibility/capability matrix | open (needs device evidence) |
| M1-S02 versioned schemas and unit semantics | partial: schemas exist; the in-app probe already follows them; freezing is open |
| M1-S03 parsers (`status`, `meminfo`, `vmstat`, `stat`, `smaps_rollup`, PSI) | open for the host; the same fields are parsed in C++ by the probe (`native/src/self_proc.cpp`) |
| M1-S04 SSH transport | open |
| M1-S05 scheduler, bounded snapshots, append-only archive | open |
| M1-S06 annotations, segmentation, CSV export | partial: segmentation and CSV export exist in analysis/reporting; `annotate` is open |
| M1-S07 install/security/runbook | open |

The phase and segment event convention used by M0002 and written by the probe
(`{"event":"phase_start","phase":...}`) is provisional until this milestone confirms it.
