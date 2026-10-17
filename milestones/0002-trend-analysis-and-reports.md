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
