# Demo run (no device needed)

Exercises every milestone-0001 command against the synthetic procfs tree in
`tests/fixtures/procfs/basic` (a made-up process `synthetic_app`, pid 4242). Nothing here
touches a camera, a network, or `ssh`. Values are constant, so analysis reports "flat" or
"too little data"; the point is the workflow and the files it produces. The same flow is
exercised by `tests/integration/test_cli_device.py`.

```bash
FIX=tests/fixtures/procfs/basic
OUT=$(mktemp -d)          # PowerShell: $OUT = Join-Path $env:TEMP "axmem-demo"

# 1. What can be read?
axis-memlab discover --procfs-root $FIX --app synthetic_app

# 2. Collect 12 samples without waiting between cycles (offline demos only)
axis-memlab collect --procfs-root $FIX --app synthetic_app \
  --config configs/default.toml --out $OUT \
  --device-id demo-device-1 --scenario offline-demo --privacy-classification synthetic \
  --max-samples 12 --no-wait
RUN=$(ls -d $OUT/*/)      # PowerShell: $RUN = (Get-ChildItem $OUT).FullName

# 3. Annotate, take a sparse snapshot, see that deep captures are refused
axis-memlab annotate --run $RUN --phase T2 --note "steady state"
axis-memlab snapshot --procfs-root $FIX --pid 4242 --run $RUN --config configs/default.toml
axis-memlab snapshot --procfs-root $FIX --pid 4242 --run $RUN --config configs/default.toml --level deep   # exits 3

# 4. Analyze and render
axis-memlab analyze --run $RUN --config configs/default.toml --out $OUT/report.json
axis-memlab report  --input $OUT/report.json --format markdown

# 5. Retention (dry run)
axis-memlab purge --root $OUT --older-than-days 30
```

Look at `$RUN/manifest.json` (identity, config hash, status) and `$RUN/records.jsonl`: the
first lines are `capability` records, then `run_start`, then `sample` records with explicit
units and sources, and a final `run_stop`.

To see unavailable-metric handling, copy the fixture, delete `proc/pressure/memory` or
`proc/4242/smaps_rollup`, and collect again: the affected metrics become unavailable with
`reason_code` `missing`, one `error` record is written, and the run still completes.
