# Protocol and schemas

The Draft 2020-12 files in `schemas/` describe a provisional M0000 contract;
M0001 owns refinement and freezing compatibility. JSON Lines uses one record
envelope per line. `run_id` is a UUID in this scaffold. UTC and monotonic
timestamps are integer nanoseconds; a missing monotonic clock is `null`.

Identity uses a pseudonymous `device_id`; optional process identity fields are
absent when undiscovered. A metric is `{value, unit, source}` when observed or
`{available:false, reason}` when unavailable. Zero is a real measured value,
never a missing marker. Metric names are namespaced, for example
`system.mem.available_bytes`, `process.rss_anon_bytes`,
`process.pss_bytes`, and `app.frame.inflight_bytes`; byte values use `bytes`.
Optional `annotations` and `source_metadata` are objects; identity details that
were not discovered are omitted rather than invented.
No image, video, or plate fields are part of this schema.

Provisional phase convention used by M0002 analysis (M0001 to confirm): an `event`
record with `annotations` `{"event":"phase_start","phase":"T2"}` opens a named phase, and
`{"event":"segment_boundary","reason":"..."}` marks a restart or configuration change.
`report-v1` findings each carry a `type` of `segment`, `trend`, `hypothesis`,
`comparison`, or `correlation`.

Fixtures in this repository are synthetic. Schema version 1 is preliminary and
does not imply deployed protocol stability.

## Records written by the in-app probe (M0003)

The C++ probe emits `record-v1` lines with `producer` `axmem-probe`: `sample` records
(`metrics`, plus `annotations.ledger` in LEDGER mode) and `event` records for phase
markers (`annotations` `{"event":"phase_start","phase":"..."}`). Identity carries
`device_id`, `pid`, `process_start_ticks`, and `boot_id` when readable. Absent or
unreadable values are `{available:false, reason}`, never zero. See
`docs/06-integrating-cpp-probes.md` for the metric names.

## Contract additions in M0001

- **Reason codes.** An unavailable metric may carry `reason_code`, one of `missing`,
  `permission_denied`, `timeout`, `parse_error`, `unsupported`, `not_collected`, next to the
  free-text `reason`. The host collector always sets it; the in-app probe still writes
  free text only.
- **Namespaces.** Metric names start with `system.`, `process.`, `app.`, or `collector.`
  (the collector's own cost and errors).
- **Record shapes** (enforced by the schema):
  `capability` needs `annotations.capability` and `annotations.state` (`available`,
  `denied`, `missing`, `timeout`, `unsupported`, `unknown`);
  `error` needs `annotations.source` and `annotations.reason_code`;
  `event` needs `annotations.event`. Events in use: `phase_start` (`phase`),
  `segment_boundary` (`reason`), `trigger_fired`, `sparse_skipped`, `source_recovered`,
  `process_restart`, `process_missing`, `snapshot`, `abort_memory_pressure`. `run_start` and
  `run_stop` bracket a collection (`run_stop` carries `status` and `reason`).
- **Identity.** `device_id` is a pseudonym; `boot_id`, `pid`, and `process_start_ticks`
  identify a process instance and drive segmentation.
- **Manifest** gains `consent_reference`, `redaction_status`, `config_sha256`, and
  `collector_version`. The manifest `status` is the only field that changes after creation.
- **Freezing.** Schema version 1 is now used by three producers (collector, probe,
  importer). Changes are additive; a breaking change needs `schema_version` 2.

## Allocation samples (M0004)

The sampler writes a separate JSON Lines file, `alloc-samples-v1`
(`schemas/alloc-samples-v1.schema.json`): `header`, `modules`, `alloc`, `free`, and `summary`
records, with raw program counters, module base names and build-ids, and statistical weights.
It is not part of `records.jsonl`; `axis-memlab symbolize` turns it into a `report-v1`
document (`allocation_summary` and `allocation_site` findings). Format and semantics:
`docs/12-allocation-sampling.md`.

## Compatibility evidence and bundles (M0005)

`schemas/compat-evidence-v1.schema.json` describes what was verified on one device and firmware
and drives the gate for advanced diagnostics. `axis-memlab bundle` writes a directory with a
`BUNDLE.json` descriptor (files, SHA-256, redaction counts, review status). Neither is part of a
run's `records.jsonl`. See `docs/13-advanced-diagnostics.md` and `docs/09-customer-escalation.md`.
