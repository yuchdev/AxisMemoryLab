# Offline analysis (planned)

**Owner:** M0002. **Status:** implemented for local archives (synthetic validation).

Future analysis will consume validated local run archives without requiring
network access. It must distinguish unavailable data from zero and preserve
traceability to source records and limitations.

Planned scenario matrix (M0002): camera baseline without the application, idle,
constant load, high-activity load, repeated reconnect, recovery after draining
queues, long steady duration, and cross-firmware comparison. Fix firmware,
build, configuration, scene, codec, resolution, and frame rate within a paired
comparison; repeat decisive runs at least twice; normalize per hour and per
1,000 frames, results, or reconnects once the application counters exist.

## Commands (M0002)

```bash
axis-memlab analyze --run RUN_DIR --config configs/default.toml [--correlate A:B] [--out report.json]
axis-memlab compare --baseline RUN_A --candidate RUN_B --config configs/default.toml [--phase T2]
axis-memlab report  --input report.json --format markdown|html|csv [--out FILE]
```

`--out` refuses to overwrite an existing file. Exit codes: 0 ok, 2 invalid config or
arguments, 4 unreadable or invalid run/report input. Skipped or malformed record lines
are listed in the report's limitations, never dropped silently.

- **Segments.** A run is split at `phase_start` / `segment_boundary` events and at changes
  of `pid`, `process_start_ticks`, or `boot_id`. Nothing is fitted across a boundary.
- **Windows.** Each segment gets a warm-up window (first `warmup_seconds`) and a
  post-warm-up window; conclusions use the latter.
- **Normalization.** `[analysis].normalization` entries other than `elapsed_seconds` name a
  counter metric; growth per 1,000 counter units is reported when the counter rises.
  Slopes per hour are always reported.
- **Comparison.** Uses the segment with most samples per side. Firmware, build, model, SoC,
  SDK, libc, and workload must match and be recorded, else a limitation is added. One run
  per side is always flagged: decisive comparisons need at least two repetitions.
- **Correlation.** Spearman rank correlation of interval changes (not levels); association
  only.
