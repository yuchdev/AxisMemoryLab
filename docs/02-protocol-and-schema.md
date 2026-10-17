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
