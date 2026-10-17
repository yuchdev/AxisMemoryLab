# Collecting on AXIS OS (runbook)

**Owner:** M0001. **Status:** implemented and tested against fixtures and a simulated `ssh`;
**not yet run on a real camera.** Compatibility with any firmware is unverified
(`docs/01-axis-compatibility.md`). Use only an approved development device.

## 1. Before you start

1. External requirements are in the README ("External requirements"): OpenSSH client, a
   known host key, a key-based non-root account, readable `/proc`, a device you are allowed
   to measure.
2. Choose a **pseudonym** for the device (`--device-id`). Serial numbers, MAC and IP
   addresses are refused.
3. Pick a profile (`configs/*.toml`) and run `axis-memlab config check --file <profile>`.
   Profiles can only be conservative: every risky flag is off, every privacy flag is on.
4. Decide the question, phases, warm-up, duration, repetitions, and stop condition first
   (`docs/11-investigation-workflow.md`, S0).

SSH setup is yours to do and is not automated: enable SSH as the Axis documentation
describes for your AXIS OS release, create a dedicated least-privilege account and key, and
connect once manually to verify the host key against a trusted source so it is in
`known_hosts`. The tool refuses unknown or changed host keys.

## 2. Procedure

```bash
# 1. What can this account read? (read-only, no data stored)
axis-memlab discover --ssh svc@camera --app my_app --json

# 2. Collect a bounded run. One of --duration-seconds / --max-samples is required.
axis-memlab collect --ssh svc@camera --ssh-identity ~/.ssh/axmem_ed25519 --app my_app \
  --config configs/default.toml --out runs/ \
  --device-id cam-a --scenario T2-steady --test-case-id T2 \
  --camera-model "<model>" --soc "<soc>" --firmware-version "<AXIS OS version>" \
  --sdk-generation "<ACAP SDK>" --build-id "<app build>" \
  --workload-resolution 1920x1080 --workload-fps 15 --workload-codec h264 \
  --consent-reference "<approved id>" --duration-seconds 3600

# 3. Mark phases from another shell while it runs (appends events; never edits history)
axis-memlab annotate --run runs/<run_id> --phase T3 --note "more detections"
axis-memlab annotate --run runs/<run_id> --segment-boundary "config change"

# 4. One extra sparse capture at a moment you care about
axis-memlab snapshot --ssh svc@camera --app my_app --run runs/<run_id> --config configs/default.toml

# 5. Bring in the in-app probe's output (validated line by line)
axis-memlab import --input records.jsonl --run runs/<run_id>

# 6. Analyze, compare, report
axis-memlab analyze --run runs/<run_id> --config configs/default.toml --out report.json
axis-memlab report  --input report.json --format markdown --out report.md

# 7. Retention: list, then delete, runs older than N days
axis-memlab purge --root runs/ --older-than-days 30
axis-memlab purge --root runs/ --older-than-days 30 --confirm
```

`--pid N` can be used instead of `--app` (`--app` matches the kernel command name, truncated
to 15 characters; an ambiguous name is refused). Use `--procfs-root DIR` instead of `--ssh`
to read a saved tree, or `/` on a live local Linux host. `--no-wait` (offline only) skips
the sleeps between cycles for demos.

## 3. What is read

Only these paths, only through `cat` / `ls -l` templates; nothing else is ever sent to the
device, and no text you type reaches the remote shell.

| Path                                                     | Used for                                             | Cadence                                |
|----------------------------------------------------------|------------------------------------------------------|----------------------------------------|
| `/proc/meminfo`, `/proc/vmstat`, `/proc/pressure/memory` | device-wide memory, reclaim, PSI                     | every cycle                            |
| `/proc/PID/status`, `/proc/PID/stat`                     | per-process residency, CPU, faults, start ticks      | every cycle                            |
| `/proc/PID/smaps_rollup`                                 | PSS, private/shared, anonymous                       | sparse interval or trigger             |
| `/proc/PID/fd` (`ls -l`)                                 | descriptor count and classes (targets are discarded) | sparse interval or trigger             |
| `/proc/PID/cgroup`, cgroup `memory.*` files              | cgroup charge, limit, OOM kills                      | sparse interval or trigger             |
| `/proc/<n>/comm` (all visible processes)                 | resolving `--app` to a pid                           | at start, and when the process is lost |
| `/proc/sys/kernel/osrelease`, `.../random/boot_id`       | facts and run segmentation                           | at start                               |

Never read: `cmdline`, `environ`, `maps`, `smaps`, `/proc/version` (it can contain build host
names), logs, or the file system outside this list.

## 4. How a cycle behaves

- **One connection per cycle** for the regular reads (a single batched command), one more for
  the fd listing and one for sparse files when due. Connection setup is the dominant cost on a
  constrained device; measure it (`collector.cycle_duration_ns`, `docs/10-benchmarking-overhead.md`).
- **Unreadable sources** become unavailable metrics with a `reason_code` plus one `error`
  record when they first fail and one `source_recovered` event when they return. The
  collector keeps going.
- **Memory pressure.** Below `trigger_mem_available_below_bytes` the sparse reads (page-table
  walk, fd listing) are skipped and a `sparse_skipped` event says so. Below
  `abort_mem_available_below_bytes` the run records `abort_memory_pressure` and ends as
  `incomplete`. Neither threshold changes anything on the device.
- **Triggers** (`trigger_pss_growth_bytes`, low memory) record a `trigger_fired` event and, when
  allowed, one sparse snapshot. A cooldown (`deep_snapshot_cooldown_seconds`) limits repeats.
- **Process restarts and disappearance** are events (`process_restart`, `process_missing`);
  the identity (`boot_id`, `pid`, `process_start_ticks`) changes, so analysis starts a new
  segment. With `--app` the process is looked up again.
- **Connection failures** back off exponentially (2, 4, 8, 16 s) and end the run as `failed`
  after five in a row. A failed start leaves a `failed` manifest and no samples.
- **Ctrl-C** ends the run as `incomplete` after writing a `run_stop` record.

## 5. Exit codes

0 ok; 2 invalid arguments, configuration, or request (unbounded run, identifying device id,
in-app profile used for host collection, ambiguous process); 3 planned or refused feature
(`symbolize`, `snapshot --level deep`); 4 unreadable or invalid file or run; 5 transport
failure (unreachable device, rejected host key, repeated connection failures); 6 run ended
early but safely (interrupt or memory pressure).

## 6. Run archive

`runs/<run_id>/manifest.json` and `records.jsonl` (`records.jsonl.gz` with `--compress`;
compressed runs are read-only). Records are only appended, one line per write; a crash can
leave one torn last line, which the next writer starts after and readers report. The
manifest changes only its `status`. The archive contains no host name, username, key path,
command line, environment, fd target, or image data; the pseudonym, consent reference, and
config hash are in the manifest. Treat it as sensitive until reviewed
(`--privacy-classification`, default `sensitive`).

## 7. Troubleshooting

| Symptom                                 | Likely cause and next step                                                                                               |
|-----------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| Exit 5, "Host key verification failed"  | Host key not in `known_hosts` or changed. Verify it out of band and add it; do not disable checking                      |
| Exit 5, "Permission denied (publickey)" | Wrong key or account; password login is disabled                                                                         |
| `process_status` capability `denied`    | The account cannot read that process. Use the in-app probe and `import`                                                  |
| `--app` finds nothing                   | The account cannot see the process, or the name differs (`comm` is 15 characters). Use `--pid`                           |
| `process_smaps_rollup` `missing`        | Kernel lacks it or it is hidden; RSS categories from `status` carry the analysis. The tool does not fall back to `smaps` |
| Many `timeout` errors                   | Raise `ssh_command_timeout_seconds`, or reduce the interval; check `collector.cycle_duration_ns`                         |
| `snapshot --level deep` exits 3         | Deep captures are blocked by the safety model; see `docs/08-security-privacy.md`                                         |

## 8. Not provided

Deep captures (full `smaps`, allocator reports), restarting or changing the application, root
or `ptrace` use, reading logs or the Axis device server report, scheduling, and any network
listener. Later milestones may add some of these behind separate reviews.

## 9. Levels 3 and 4

Triggered sparse snapshots are part of `collect` (section 4). Anything beyond them (`strace`,
`gdbserver`, `perf`, `ftrace`/eBPF, slab and DMA-BUF accounting, DDH, core dumps) is **not** part
of a collection: it is gated by verified evidence per firmware and described in
`docs/13-advanced-diagnostics.md`. Deep captures are blocked
(`docs/decisions/0003-advanced-diagnostics.md`).
