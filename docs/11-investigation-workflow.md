# Investigation workflow (proposed)

**Status:** proposed procedure. It combines the diagnostic playbook
(`docs/roadmap/tech_notes/01_DIAGNOSTIC_PLAYBOOK.md`), the first-hour checklist
(`.../03_FIRST_HOUR_COMMANDS.md`), the offline analysis of M0002, and the in-app probe of
M0003. Nothing here has been run on a real camera. Thresholds are starting points to be
revised with device evidence.

**Question this workflow answers:** *where is physical memory growing while the application
processes video, what workload drives it, and which owner (application code, a library,
another service, the kernel) should be examined next?* It does not try to prove a leak. It
narrows the search and produces evidence good enough to choose the next experiment or to
escalate with a reproducible case.

## 0. Ground rules

1. **Authorized, least-privileged, read-only first.** Use an approved development camera
   and a non-root account. Never work around Axis access controls; if another account's
   `/proc` entry is denied, measure from inside the application with `/proc/self`.
2. **Predeclare before measuring:** the question, the phases, the warm-up window, the
   run duration, the repetition count, and the stop condition (an abort threshold on
   `MemAvailable`, see `abort_mem_available_below_bytes`). Changing these after looking at
   the data invalidates the comparison.
3. **One variable at a time.** Within a paired comparison hold firmware, application
   build, configuration, scene, codec, resolution, frame rate, and network conditions
   fixed.
4. **Repeat decisive runs at least twice.** One run per side can suggest, not decide.
5. **Unavailable is not zero.** Record why a metric could not be read. A measured zero is
   a real value.
6. **Segment, never fit across a discontinuity.** Process restarts, reconnect storms
   treated as a phase, configuration changes, and reboots start a new segment.
7. **Keep it synthetic in the repository.** Real measurements stay out of git; share only
   redacted, pseudonymous evidence (`docs/08-security-privacy.md`).
8. **Instrumentation is a variable too.** Measure its overhead (§6.4) and keep a
   run with it disabled as a control for any conclusion that depends on it.

## 1. What exists today

| Capability | State | Use in this workflow |
| --- | --- | --- |
| `axis-memlab config check` | implemented (M0000) | Validate the safety profile before any run |
| `axis-memlab analyze / compare / report` | implemented (M0002), synthetic-validated | Stages 3, 4, 7 |
| C++ probe, `COUNTERS` and `LEDGER` modes | implemented (M0003), host-tested, **not yet run on a camera** | Stage 5 |
| `discover`, `collect`, `annotate`, `snapshot`, `import`, `purge` | implemented (M0001), fixture-tested, **not yet run on a camera** | Stages 1, 2, 5 |
| Allocation sampling, symbolization, sanitizers, heap-profiler replay | not implemented (M0004) | Stage 8 (escalation) |
| Vendor-assisted kernel/driver inspection (`gdbserver`, `strace`, `perf`, slab/DMA-BUF), device server report | not implemented (M0005) | Stage 8 (escalation) |

Every tool and technique in the tech notes has an owner; see
`docs/roadmap/tech-notes-coverage.md`.

Host-side samples are collected with `axis-memlab collect` (runbook:
`docs/05-collecting-on-axis.md`; external requirements in the README). The in-app probe
writes `record-v1` directly and is brought in with `axis-memlab import`, so a run can
combine both sources. `snapshot --level deep` and anything beyond the allowlisted reads
remain unavailable.

A run archive is a directory with `manifest.json` and `records.jsonl`
(`docs/02-protocol-and-schema.md`). Phase markers are `event` records with
`{"event":"phase_start","phase":"T2"}`; the probe writes them for you with
`axmem_phase_marker("T2")`.

## 2. Overview

```text
 S0 Plan ──► S1 Identify ──► S2 Baseline matrix ──► S3 Locate growth ──► S4 Discriminate by workload
                                                          │                        │
                                                          ▼                        ▼
                                                  G1: no growth?            G3: which driver?
                                                  stop / lengthen                  │
                                                                                   ▼
                          S8 Escalate ◄── S7 Report ◄── S6 Targeted experiments ◄── S5 Instrument
```

| Stage | Output | Gate to leave the stage |
| --- | --- | --- |
| S0 Plan | Written test plan | Plan reviewed; stop condition set |
| S1 Identify | Completed manifest, capability list | Model, SoC, firmware, SDK, build known |
| S2 Baseline matrix | Runs for T0–T2 (+T5/T6 as needed) | Each run complete, ≥ 2 repetitions of decisive ones |
| S3 Locate growth | Report per run with segments and trends | G1 and G2 answered |
| S4 Discriminate | Paired comparisons and normalized growth | G3 answered or declared unanswerable without counters |
| S5 Instrument | Probe in the app, overhead measured | Counters track the stage under suspicion |
| S6 Targeted experiments | Prediction vs outcome per experiment | One hypothesis survives, or all are refuted |
| S7 Report | Evidence report with limitations | Reviewer can reproduce the claim |
| S8 Escalate | Reproducible case for vendor or maintainers | Only if S6 leaves an unowned remainder |

## 3. Stage 0 — Plan

1. Write the **question** in one sentence, for example "Does private anonymous memory of
   the analytics process keep growing after a 10-minute warm-up under constant 1080p15
   H.264 input?"
2. Choose the **phases** from the matrix in S2 that can answer it; do not run all of them
   by default.
3. Declare **warm-up** (the config's `[analysis].warmup_seconds`; the default of 60 s is a
   placeholder: set it from the application's real start-up behaviour), **duration**
   (long enough that the smallest growth worth caring about exceeds sample noise;
   estimate from a pilot run), **repetitions**, and **abort condition**.
4. Pick the **profile** (`configs/default.toml`, `lightweight`, `inapp-only`, `stress-lab`)
   and run `axis-memlab config check --file <profile>`. `stress-lab` is for a lab unit
   only, never a production camera.
5. Decide where data lands: a host disk you control. Avoid frequent writes to camera
   flash.

**Exit:** a plan another engineer could execute unchanged.

## 4. Stage 1 — Identify the device and what can be read

Record (manifest fields in parentheses): camera model (`camera_model`), SoC (`soc`),
AXIS OS version (`firmware_version`), ACAP package and build (`build_id`,
`software_version`), SDK generation (`sdk_generation`), libc/allocator (`libc`),
workload (`workload.resolution/fps/codec`), test case (`test_case_id`), total RAM, kernel
version, whether the app is native or containerized, and how the process is run (dynamic
user, Developer Mode).

Then discover, read-only and one command at a time, which sources respond
(`.../03_FIRST_HOUR_COMMANDS.md` §2): `/proc/meminfo`, `/proc/vmstat`,
`/proc/pressure/memory`, `/proc/PID/status`, `/proc/PID/stat`, `/proc/PID/smaps_rollup`,
`/proc/PID/fd`. Note each as *available*, *denied*, *missing*, or *timed out*. Missing
sources shape the plan: if `smaps_rollup` is denied, PSS is unavailable and RSS
categories from `status` carry the analysis, with the limitation stated.

Check platform facts that change the hypothesis list before any measurement:
- Firmware in the range Axis documents for the `vdo_buffer_get_data` leak
  (`docs/01-axis-compatibility.md`): plan a firmware comparison early.
- Larod API generation: buffer lifetime rules differ; do not reuse release logic across
  generations.
- Whether the SSH user can read the application's `/proc/PID`. If not, S5 (in-app) is the
  only per-process source, so schedule it sooner.

**Exit:** manifest complete; capability list written; first suspects ranked.

## 5. Stage 2 — Baseline and workload matrix

Run the smallest subset that discriminates. Phase markers separate the phases inside one
run when the application stays up; use separate runs when a restart is needed.

| ID | Phase | Holds constant | Tells you |
| --- | --- | --- | --- |
| T0 | Camera up, application stopped | Default Axis services | Platform baseline and drift |
| T1 | Application loaded, video processing off | Same services | Start-up and idle behaviour |
| T2 | Constant steady video processing | Scene, fps, codec | Frame-rate-linked growth |
| T3 | More detections/objects, same fps | T2 settings | Result-driven growth |
| T4 | Repeated reconnect or stream/inference re-init | T2 settings | Lifecycle cleanup defects |
| T5 | Processing off, queues drained, process kept | T2 settings | Backlog vs retained memory |
| T6 | Long steady run after warm-up | T2 settings | Persistent slope vs plateau |
| T7 | Same test on other firmware/device | Everything else | Platform-specific regression |

**Sampling (starting points from the default profile):** regular samples every 10–15 s
(`sample_interval_seconds`), `smaps_rollup` every 1–5 min if readable
(`smaps_rollup_interval_seconds`). Always capture system and process readings in the same
sample so they can be compared. Include a monotonic and a UTC timestamp, the PID and
process start ticks, and the boot id so restarts are detectable.

**Per run:** fixed order of actions; announce every phase boundary with a marker; stop at
the declared duration or when the abort threshold trips; mark the manifest `complete`,
`incomplete`, or `failed` honestly.

**Exit:** each planned run exists as a run archive; decisive ones repeated.

## 6. Stage 3 — Locate the growth

For each run:

```bash
axis-memlab analyze --run RUN_DIR --config configs/default.toml --out report.json
axis-memlab report  --input report.json --format markdown --out report.md
```

Read the report in this order: **limitations → segments → trends → hypotheses**.

1. *Limitations and segments first.* Skipped lines, absent metrics, short windows, and
   restarts change what you may conclude. A segment with too little post-warm-up data
   gets no growth statement; extend the run rather than interpreting noise.
2. *Trends.* Look at the post-warm-up window only. Compare direction, slope per hour,
   span, sample count, and min/max.

**Gate G1 — Is there sustained growth after warm-up?**

| `system.mem.available_bytes` | process anon RSS / PSS | Reading | Go to |
| --- | --- | --- | --- |
| falling | rising | Growth is in the process (device-wide effect follows) | G2 |
| falling | flat | Not in the monitored process: other service, shared/driver memory, or page cache | G2b |
| flat | rising | Process grows but system compensates (reclaim/cache): check `Cached`, `Shmem`, PSI | G2 |
| flat | flat | No reproduction in this window | Lengthen the run (T6), vary the workload (T3/T4), or conclude "not reproduced under these conditions" |

**Gate G2 — Which memory class inside the process?** Use `RssAnon`, `RssFile`,
`RssShmem`, and `smaps_rollup` private/shared categories (never `VmSize`, never summed
RSS).

| Observation | Prioritize |
| --- | --- |
| `RssAnon` and private dirty rise together | Application heap, queues, caches, object retention |
| `RssShmem`/shared mappings rise; fd count rises | Video/inference buffer ownership (shared or DMA buffers) |
| `RssFile` rises | Mapped files, libraries, model files; usually bounded |
| Everything rises at start-up, then plateaus | High-water mark, not necessarily a leak (H-PLATEAU) |

**Gate G2b — System falls, process flat.** This is *not* evidence of a kernel leak. Next:
list other accessible processes and compare against T0; look at `Cached`, `Shmem`,
`Slab`/`SUnreclaim`, and PSI; repeat with analytics off (T1) to see whether the decline
needs the application at all. Escalation to vendor-supported inspection is S8.

## 7. Stage 4 — Discriminate by workload

Pairwise comparisons answer "what drives the growth":

```bash
axis-memlab compare --baseline T1_RUN --candidate T2_RUN --config configs/default.toml
axis-memlab compare --baseline T2_RUN --candidate T3_RUN --config configs/default.toml --phase T3
```

Read the report's comparability notes first: any controlled field that differs or is not
recorded weakens the pair. Then:

| Comparison | If slope differs | If slope is similar |
| --- | --- | --- |
| T1 vs T2 | Growth needs video processing | Growth is in start-up/idle behaviour |
| T2 vs T3 | Growth tracks detections/results | Growth is frame-rate linked |
| T2 vs T5 | Drained queues release memory → backlog; no release → retention | n/a |
| T4 per cycle | Per-reconnect growth → lifecycle cleanup defect | n/a |
| T2 on firmware A vs B | Platform regression; check the VDO range first | Application-side |

**Normalization.** Raw slope per hour is always available. If the application exports
counters (S5), list them in `[analysis].normalization` to get growth per 1,000 frames,
detections, or reconnects. Per-frame growth that is stable across fps settings points to
per-frame retention; growth that follows wall-clock time regardless of fps points
elsewhere (timers, caches, other services).

**Gate G3 — Which driver?** Pick the dominant one: frames, results/detections,
reconnect cycles, wall-clock time, or "unknown". "Unknown" is a legitimate result; it
sends you to S5.

Use `--correlate A:B` to check whether interval changes of two metrics move together
(for example `process.pss_bytes:app.queue.depth_count`). This is association only;
confirm by experiment.

## 8. Stage 5 — Instrument the application

Go here when host-side metrics cannot separate the hypotheses, or the SSH user cannot read
the process. Prefer the lowest mode that answers the question.

### 8.1 Choose the mode

| Mode | Cost on hot path | Use for |
| --- | --- | --- |
| `AXMEM_DISABLED` (default) | none (inline no-ops) | Shipping builds; the control run |
| `AXMEM_COUNTERS` | relaxed atomics | Always-on-capable counters: totals, queue depths, per-kind in-flight **counts** |
| `AXMEM_LEDGER` | one mutex per acquire/release | Lab/development: exact in-flight **bytes**, duplicate/unmatched detection, oldest live ids |

Build and test: `cmake -S native -B build/native -DAXMEM_COUNTERS=ON` (or
`-DAXMEM_LEDGER=ON`), then `ctest`. Exactly one mode must be selected; combining modes or
requesting the sampler is a configure-time error.

### 8.2 Place the hooks (application decides ownership)

1. Register counters, gauges and resource kinds **once at start-up**, keep the handles.
2. Call `acquire` where the application *takes ownership* and `release` where it
   *gives it up*, on **every** exit path including errors. `ResourceGuard` fits scope-bound
   ownership only; for cross-thread or queued ownership, call the two functions at the
   real boundaries.
3. Gauge each queue's depth and bytes; use `watermark` for high-water marks.
4. Add phase markers from the test driver at phase boundaries.
5. Call `axmem_emit_snapshot()` from an existing timer or control thread (10–15 s), never
   from a frame path. Snapshots are file I/O.
6. Do not make the probe own, extend, or reorder any resource release. Do not assume how
   VDO or Larod objects are owned: the placement examples in
   `native/examples/vdo_lifecycle/README.md` are patterns to verify against your SDK
   generation, not drop-in code.

### 8.3 Choose metrics for the hypothesis under test

| Hypothesis | Minimum instrumentation |
| --- | --- |
| Unbounded queue/retention | Per-queue depth (count) and bytes gauges |
| Missed release | `ResourceKind` for each lifetime-managed resource (frames, tensors, buffers); compare `in_flight_count` with throughput |
| Allocator retention | `LEDGER` in-flight bytes **and** `include_allocator_stats` (glibc only); compare with `process.rss_anon_bytes` |
| Reconnect cleanup | A reconnect counter plus per-kind in-flight count before/after each cycle |
| Result accumulation | Result-cache entries/bytes gauges and a detections counter |

### 8.4 Measure the overhead (control for the instrument)

1. Build the app three ways: disabled, `COUNTERS`, `LEDGER`.
2. Run the same T2 workload on each; compare throughput/latency and the memory trend
   (see `docs/10-benchmarking-overhead.md`). Host microbenchmarks
   (`axis_memlab_overhead_bench`) only bound the per-call cost on the machine they ran on.
3. If the probe changes the trend, report that; use `COUNTERS` for the main runs and
   `LEDGER` only for short confirmatory runs.

### 8.5 Ingest

Place the probe output as `records.jsonl` beside a `manifest.json` and run S3/S4 again;
`app.*` metrics are analyzed automatically. In `LEDGER` mode the newest snapshot's
`annotations.ledger.oldest_live` lists the oldest still-live resources with ids and ages:
those ids are where to look in the application's own logs.

Treat these as data-quality flags: `app.ledger.degraded = 1` (ledger overflowed; in-flight
numbers are no longer trustworthy), `app.ledger.unmatched_release_count > 0` or
`duplicate_acquire_count > 0` (hook placement is wrong or ids are not unique), and
`app.probe.snapshots_dropped_count > 0` (output cap reached).

## 9. Stage 6 — Targeted experiments

Each experiment states a **prediction that could be wrong**, the change, the control, and
the refutation criterion, before it is run.

| Hypothesis | Experiment | Supports if | Refutes if |
| --- | --- | --- | --- |
| Queue retention | Cap or drain the queue (T5-style) | Post-warm-up slope drops toward zero and queue gauge is bounded | Slope unchanged with bounded queue |
| Missed release | Fix or stub the suspect release path on a lab build | `in_flight_count` stops rising; process slope drops | In-flight flat before and after, slope persists |
| Allocator retention | Development-only allocator experiment (for example a trim call at a quiet point, or a different allocator build) | RSS drops while tracked bytes were flat | No change |
| Reconnect cleanup | N identical start/stop cycles | Step per cycle, flat in between | No per-cycle step |
| Result accumulation | Disable or cap result publication | Slope tracks detections and disappears | Slope unchanged |
| Platform regression | Same build on firmware A vs B | Slope differs across firmware | Same slope |
| Not in process | Stop analytics (T1) while watching system memory | Decline continues | Decline stops |

A trim or allocator change that lowers RSS shows retention, not that a leak did or did
not exist. One surviving hypothesis is a candidate cause; confirm by a fix that removes
the growth and by a repeat. Validate a fix under the same workload including reconnect
cycles, and with a long soak (for example 24 h) if the memory budget permits.

## 10. Stage 7 — Report

Produce `report.json`, `report.md` (and CSV if needed) for each decisive run and
comparison. A report that others can rely on includes:

- the question and plan, plus any deviation from it;
- manifest facts and the capability list (what could not be read);
- per-segment trends for the post-warm-up window with span, sample count, min/max;
- paired comparisons with their comparability notes and repetition count;
- the hypotheses that were observed, those refuted by experiments, and those not
  evaluated (reconnect and detection hypotheses need counters);
- the limitations list, unedited.

**Do not write:** "there is a leak" from a regression alone; "the kernel leaks" from
falling `MemAvailable` with flat process memory; conclusions from a single run; or any
claim about firmware not tested.

## 11. Stage 8 — Escalate

Escalate only when S6 leaves a remainder the application does not own.

| Remainder | Next step | Owner |
| --- | --- | --- |
| Growth only in application private memory, source unclear | Off-camera sanitizer or heap profiling with a replay of the workload; allocation sampling (M0004) | Application team |
| Growth in shared/DMA buffers tied to VDO/Larod calls | Minimal reproducer against the exact SDK generation; compare with the vendor's documented buffer lifetime | Application team, then vendor |
| System memory falls, process flat, analytics-dependent | Vendor-supported inspection of other services and drivers (M0005); firmware A/B | Vendor |
| Platform regression across firmware | Evidence bundle of the paired runs and manifests | Vendor |

Bundle contents (after approved redaction, `docs/09-customer-escalation.md` is still an
outline): manifests, redacted reports, the test plan, the reproducer, and the list of
sources that were unreadable. No images, footage, plate text, credentials, addresses, or
serial numbers.

## 12. Quick reference: observation → action

| You see | Do next |
| --- | --- |
| Post-warm-up window too short | Extend the run; do not interpret |
| Process flat, system falling | Stage 3 G2b: compare T1/T0, other processes, cache/shared |
| Anon RSS and PSS rising, no counters | Stage 5 with `COUNTERS`: queues and in-flight counts |
| In-flight count rising with frames | Hook audit of release paths (all exit paths) |
| In-flight flat, anon RSS rising | `LEDGER` bytes + allocator stats; allocator experiment |
| Growth per reconnect only | T4 cycle test with counters before/after each cycle |
| Plateau after warm-up | Verify bound with longer T6 and heavier T3 before closing |
| Ledger degraded or unmatched releases | Fix hook placement; discard that run's in-flight numbers |
| Result differs between repetitions | Fix uncontrolled variables; do not average away a disagreement |

## 13. Worked example (synthetic, runnable)

The repository ships a synthetic pipeline with injected defects. It uses no camera SDK
and demonstrates the S5 → S3 loop end to end.

```bash
cmake -S native -B build/native-ledger -DAXMEM_LEDGER=ON
cmake --build build/native-ledger --config Release --target axis_memlab_lifecycle_simulator
SIM=build/native-ledger/Release/axis_memlab_lifecycle_simulator   # path varies by generator
mkdir -p /tmp/sim-leak && $SIM /tmp/sim-leak/records.jsonl leak
# Add a manifest.json (see tests/integration/test_native_probe.py), then:
axis-memlab analyze --run /tmp/sim-leak --config configs/default.toml --out leak.json
axis-memlab report  --input leak.json --format markdown
```

Expected reading: `app.resource.frame.in_flight_count` and `..._bytes` rise in `leak`
mode while the acquired/released totals both keep growing, so only the *difference*
exposes the defect; in `queue` mode the queue-depth gauge rises while frames stay
balanced; in `ok` mode both are flat. This is how the three defect classes separate in a
real run, subject to the real application's noise.
