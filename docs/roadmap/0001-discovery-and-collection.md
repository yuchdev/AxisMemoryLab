# Milestone 0001 — Discovery and collection

**Owner:** M0001. **Depends on:** M0000. **Status:** implemented and tested on fixtures and a simulated `ssh`; device acceptance open.

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

## Delivered

- Parsers (`sources/`) for `meminfo`, `vmstat`, PSI, process `status`/`stat`, `smaps_rollup`,
  fd listings, and cgroup v1/v2, with kernel-variation tests, zero preserved, unit
  conversion at parse time, and a closed `reason_code` set; the metric registry is in
  `docs/03-metrics-semantics.md` and a test keeps it complete.
- Read-only readers (`transport/`): one allowlist shared by a local reader (saved tree or live
  host) and an SSH reader that drives the system `ssh` (host keys verified, no shell, no
  forwarding, bounded time and size, batched reads, option-injection safe). Verified against
  `ssh -G` for option acceptance.
- `capability` records and discovery; append-only run store (atomic manifest, torn-line safe,
  gzip, retention); pseudonymous identity checks; manifest fields for consent, redaction, and
  config hash.
- Scheduler with sparse cadence, triggers with cooldown, memory-pressure skip and abort,
  restart/missing-process events, exponential backoff, bounded runs, and collector
  self-metrics.
- Commands: `discover`, `collect`, `annotate`, `snapshot --level sparse`, `import`, `purge`.
  `snapshot --level deep` exits 3 by design.
- Fixture-only demo: `examples/demo-run/README.md`.

## Open acceptance items

- No real device: compatibility evidence (`docs/01-axis-compatibility.md`), SSH overhead,
  one hour of valid metrics from an authorized camera, and the 24-hour collector soak.
- Not implemented: deep captures (blocked by the safety model; a separate review is needed),
  `fdinfo` and `Private_Hugetlb`, an all-process summary, reading Axis logs (`journalctl`,
  syslog), a separate SSH audit log, and the optional `tiny-probe`.
- The in-app probe still writes free-text unavailable reasons without `reason_code`
  (M0003 follow-up).
- Reconciliation of profile names with the reference `lightweight`/`standard`/`lab` set and
  separate deep-snapshot caps (`docs/roadmap/tech-notes-coverage.md`, section 6).
- Frozen protocol: version 1 is used by three producers and now changes only additively; a
  formal freeze waits for device evidence.

## Stories (revised status)

| Story | Status |
| --- | --- |
| M1-S01 compatibility matrix | procedure written; rows need device evidence |
| M1-S02 schemas and unit semantics | done (additive v1) |
| M1-S03 parsers | done |
| M1-S04 SSH transport, process selection via `/proc` | done (simulated and `ssh -G`); device untested |
| M1-S05 scheduler, bounded snapshots, append-only archive | done |
| M1-S06 annotations, segmentation, CSV export | done |
| M1-S07 install, security, runbook | done (`README`, `docs/05`, `docs/08`) |
