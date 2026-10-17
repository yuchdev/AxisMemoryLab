# Changelog

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
