# Milestone 0002 — Trend analysis and reports

**Owner:** M0002. **Depends on:** M0001. **Status:** implemented offline on the provisional record contract;
acceptance is open (see below).

Implement trend/phase analysis, controlled comparisons, and evidence reports
with explicit limitations. Acceptance requires synthetic validation, documented
metric semantics, and no unsupported conclusions or fabricated observations.

## Planned work from the memory-growth playbook

Piecewise trends before and after warm-up, named normalizers, controlled-phase
comparison per `docs/07-offline-analysis.md`, and the hypothesis table in
`docs/04-diagnostic-decision-tree.md`. Reports never claim a leak from a
regression alone.

## Delivered

`axis-memlab analyze | compare | report` read a local run archive and produce a
`report-v1` JSON document, Markdown, escaped HTML, or unit-labelled CSV. Trends are
Theil-Sen fits per segment, before and after the declared warm-up, with span, sample
count, start/end and min/max. Hypotheses follow `docs/04-diagnostic-decision-tree.md`
and are worded as observations to test. Hypotheses with no automated rule
(reconnect, detection-linked) are emitted as `not_evaluated`. Differential `smaps`
and fd reports, PNG plots, and the customer escalation bundle are **not** delivered.

## Open acceptance items

- Depends on M0001, which is not implemented. The phase/segment event convention
  (`docs/02-protocol-and-schema.md`) is provisional until M0001 freezes it.
- Validated on synthetic traces only; no real-device data has been analysed, and the
  direction thresholds in `analysis/trend.py` are untuned.
- Frame/detection normalization works only on counters present in the records; no
  collector or in-app probe produces them yet (M0001, M0003).

## Remaining scope from the tech notes

Traceability: `docs/roadmap/tech-notes-coverage.md`. *(added)* = not named here before
that review.

- Differential `smaps` mapping-group and fd inventory reports (M2-S03; needs M0001
  triggered snapshots).
- Attribution rules D (slab/`SUnreclaim` grows while the app is flat) and E (fd or DMA
  handle count grows monotonically) *(added)*; refine B with `app.allocator.*` arena
  growth and C with `Shmem`/other-process trends.
- Evaluate `H-RECONNECT` and `H-DETECTION`, now possible with counters from M0003.
- Step detection (reconnect) and sawtooth-queue handling *(added)*.
- Machine-readable `estimated_uncertainty`, `is_reliable` with reasons, a confidence band
  where there are enough points, and thresholds moved from constants in
  `analysis/trend.py` into configuration *(added)*.
- Time-to-exhaustion estimate that refuses to extrapolate across a plausible plateau or
  insufficient data *(added)*.
- Report header with device, firmware, and build identity, a timeline, suspected
  subsystem, confidence, and the next test; findings list the intervals used and any
  contradicting evidence *(added)*.
- Optional PNG plots (`reporting/plots.py`).
- CLI parity with the design contract: `analyze --warmup … --compare-phase A:B --json`,
  `compare --normalize`, and `report --run` *(added)*; the current flags are documented
  in `docs/07-offline-analysis.md`.
- Synthetic traces still to add: stepwise reconnect, sawtooth queues, random outliers,
  collector outage gaps, fps-change normalization, false correlation between independent
  metrics, DMA handles growing without RSS growth *(added)*.
- The redacted escalation bundle moved to M0005 (`docs/decisions/0001-tech-notes-reconciliation.md`).

## Stories and status

| Story | Status |
| --- | --- |
| M2-S01 trend engine, warm-up aware robust rates | done (synthetic) |
| M2-S02 phase comparison, normalization by event count | done (synthetic) |
| M2-S03 differential `smaps`/fd reports | open |
| M2-S04 conservative classification with uncertainty | partial: conservative wording and alternatives done; uncertainty fields open |
| M2-S05 Markdown/CSV/HTML reports; PNG; escalation bundle | Markdown, CSV, HTML, JSON done; PNG open; bundle moved to M0005 |
| M2-S06 synthetic traces | partial: see the list above |
