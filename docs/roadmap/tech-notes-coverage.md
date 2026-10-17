# Tech-notes coverage matrix

Traceability from every tool, technique, and requirement in the three documents in
`tech_notes/` to what the repository does about it today. Source documents:

- **PB** = `tech_notes/01_DIAGNOSTIC_PLAYBOOK.md`
- **SP** = `tech_notes/02_TOOLSET_REPOSITORY_SPEC.md`
- **FH** = `tech_notes/03_FIRST_HOUR_COMMANDS.md`
- `tech_notes/configs-default.toml` is covered in section 6.

**Status legend**

| Mark | Meaning |
| --- | --- |
| **Done** | Implemented and covered by tests in this repository (synthetic/host only; nothing here has run on a camera) |
| **Docs** | Delivered as procedure/documentation; no code is needed or possible without a device |
| **Partial** | Part implemented; the remainder is named in the milestone shown |
| **M000x** | Not implemented; owned by that milestone, which lists it |
| **M000x (added)** | Was **not** named in any milestone document before this review; added to the milestone shown |
| **Declined** | A non-goal in SP §1 or a deliberate design deviation recorded in `docs/decisions/` |

Milestone owners: M0001 discovery/collection, M0002 analysis/reports, M0003 in-app
probe, M0004 allocation sampling/symbolization, M0005 advanced AXIS diagnostics.

A summary of what remains open is at the end (section 7). No item in the three notes is
left without an owner.

## 1. Data sources on the camera (PB §1, §5; FH §2–3; SP §6)

| Item | Status | Where |
| --- | --- | --- |
| `/proc/meminfo` (`MemAvailable`, `MemFree`, `Cached`, `Shmem`, `Slab`, `SReclaimable`, `SUnreclaim`) | M0001 | host parser + collector |
| `/proc/vmstat` | M0001 | host parser |
| `/proc/pressure/memory` (PSI) | M0001 | host parser; absent PSI is an explicit unavailable state |
| `/proc/PID/status` (`VmSize`, `VmRSS`, `RssAnon`, `RssFile`, `RssShmem`, `VmSwap`, threads) | Done (in-app, `/proc/self`); M0001 (host, other PID) | `native/src/self_proc.cpp` |
| `/proc/PID/stat` (start ticks) | Done (in-app); M0001 (host) | probe identity `process_start_ticks` |
| `/proc/PID/smaps_rollup` (`Pss`, `Private_*`, `Anonymous`, `Swap`) | Done (in-app, opt-in, `include_smaps_rollup`); M0001 (host) | probe; page-table scan cost documented |
| `/proc/PID/fd` count | Done (in-app, opt-in, `include_fd_count`); M0001 (host) | probe |
| `/proc/PID/fd` target classes (socket, `anon_inode:dmabuf`, …) and `fdinfo` | M0001 (added) | triggered inventory; analysis in M0002 |
| `/proc/PID/maps`, `/proc/PID/smaps` (triggered, once) | M0001 (collect, added: opt-in `deep` path with explicit confirmation; today `allow_deep_snapshot` is rejected by config), M0002 (differential report, added) | |
| `SwapPss`, private hugetlb | M0001 (added) | parser field list |
| Boot id for segmentation | Done (in-app `identity.boot_id`; analysis segments on it); M0001 (host) | |
| Cgroup memory (`/sys/fs/cgroup`, v1/v2 detection) | M0001 (added) | conditional source `sources/cgroup.py`; correlation use in M0005-S03 |
| Cross-process summary (`ps`/`top`-like, accessible PIDs only) | M0001 (added) | part of `discover` and triggered snapshot; never assumes `pidof`/`pgrep` |
| Axis app log / `journalctl` / syslog markers | M0001 (added) | low-frequency, read-only; apps use syslog for lifecycle markers, never per-frame logs |
| Axis device server report | M0005 (M5-S05), procedure in M0001 runbook (added) | exported by an authorized operator; never fetched automatically |
| Device Data Hub CPU/memory topics | M0005 (M5-S01) | alpha maturity, supplementary only; `sources/ddh.py` stays a placeholder until then |
| `ps` / `top` as convenience | Declined as a source of truth | PB §5 says convenience only |

## 2. Collection policy and host tooling (PB §2, §7, §8; SP §3, §5, §6, §9)

| Item | Status | Where |
| --- | --- | --- |
| Level 0 device facts and capability probing | M0001 | `discover`, `capability` record |
| Level 1 regular samples (10–15 s) | M0001 (host), Done (in-app snapshots) | |
| Level 2 sparse snapshots (60–300 s) | M0001 | |
| Level 3 triggered snapshot, cooldown, size/time budget, abort under memory pressure | M0001 | trigger/abort settings already in config |
| Level 4 development-only probes | M0005 | gated by verified compatibility |
| `discover`, `collect`, `annotate`, `snapshot`, `import` commands | M0001 | exit 3 until implemented |
| SSH transport: dedicated key, host-key validation, timeouts, exponential backoff, clean close, audit record | M0001 | |
| One short-lived remote command for many reads vs persistent connection (SSH overhead) | M0001 (benchmark on device) | `docs/10-benchmarking-overhead.md` |
| Atomic append run store, abrupt-disconnect safe, graceful Ctrl-C, no implicit restart | M0001 | |
| Compressed run store, retention and purge tooling | M0001 (added) | |
| Immutable annotations / phase markers | Done (convention + in-app marker); M0001 (`annotate`) | `docs/02-protocol-and-schema.md` |
| Collector self-timing and read errors | Done (in-app `app.probe.*`); M0001 (host) | |
| Typed absence reasons (`missing`, `permission_denied`, `timeout`, `parse_error`, `unsupported`, `not_collected`) | M0001 (added) | today `reason` is free text; define a code set |
| Sampling profiles `lightweight` / `standard` / `lab` and byte/time/artifact/queue limits | M0001 (added) | see section 6 for the profile-name mismatch |
| `smaps_rollup` absent must not fall back to continuous full `smaps` | M0001 | rule enforced by the scheduler |
| No `smaps`/allocator reports during a memory-pressure emergency | M0001 | abort threshold |
| Process identity `(boot_id, pid, start_ticks)`; restart closes a segment | Done (analysis); M0001 (collector) | |
| Monotonic clock for slopes, UTC for coordination | Done | |
| Collector outage must not block the pipeline; bounded on-device buffer | Done (probe drops and counts; no backpressure); M0001 (host side) | |
| Manifest: `privacy_level`, consent or incident id, redaction status, workload/config hash | M0001 (added) | manifest has `privacy_classification` only |
| Local-only guarded archive for `cmdline`, mapping names, open-file paths | M0001 (added) | redaction before external sharing |
| No reboot, ACAP install/upgrade, developer-mode toggle, firmware change | Done (not implemented anywhere; config rejects mutating flags) | |
| Compatibility matrix from device evidence | M0001 | `docs/01-axis-compatibility.md` |
| Optional one-shot device probe (`device-optional/tiny-probe`) | M0001 (only if agentless SSH and in-app are insufficient) | evidence-driven |
| Fixture-only demo run (`examples/demo-run`) | M0001 (added) | the M1 exit allows it without a device |

## 3. Analysis and reporting (PB §1, §3, §8; SP §8, §10; FH §5–6)

| Item | Status | Where |
| --- | --- | --- |
| Piecewise trends before/after warm-up; start/end, min/max, span, sample count | Done | `analysis/trend.py` |
| Robust (Theil–Sen) slope; no leak claim from a regression alone | Done | tests assert wording |
| Rates per hour; per 1,000 frames/recognitions/reconnects (counter-based) | Done | `[analysis].normalization` |
| Segmentation at restarts, boot change, phase and configuration markers | Done | `analysis/phase.py` |
| Controlled comparison with equivalence checks and repetition warning | Done | `analysis/compare.py` |
| Correlation without causal claims | Done | interval changes, Spearman |
| Markdown / HTML / CSV / JSON report | Done | |
| Optional PNG plots, sparkline or graph | M0002 (open) | `reporting/plots.py` placeholder; a data table exists |
| Rule A application retention | Done (`H-RETENTION`) | |
| Rule B allocator caching/fragmentation | Partial (`H-ALLOCATOR` uses ledger bytes) | M0002: also use `app.allocator.*` arena growth |
| Rule C shared / other-service memory | Partial (`H-NOT-IN-PROCESS`) | M0002: use `Shmem` and other-process trends once collected |
| Rule D `SUnreclaim`/slab grows while app is flat | M0002 (added) | needs M0001 `meminfo` data |
| Rule E fd / DMA handle count monotonic growth | M0002 (added) | needs `process.fd_count` (probe has it now) |
| Rule F growth per reconnect | M0002 (`H-RECONNECT`, currently `not_evaluated`) | evaluable now with a reconnect counter |
| Growth tracks detections, not frames | M0002 (`H-DETECTION`, currently `not_evaluated`) | evaluable now with counters |
| Plateau detection | Done (`H-PLATEAU`) | |
| Step detection (reconnect), sawtooth queues | M0002 (added) | |
| Confidence band, `estimated_uncertainty`, `is_reliable` with reasons, configurable thresholds | M0002 (added) | thresholds are constants in `analysis/trend.py` today |
| Time-to-exhaustion estimate with plateau/insufficient-data guard | M0002 (added) | PB §8 step 2; never extrapolate across a plausible plateau |
| Findings list intervals, contradictory evidence, outstanding tests | Partial | next comparison and alternatives are present; time intervals and contradictions are not |
| Report carries device/build IDs, timeline, suspected subsystem, confidence, next test | Partial → M0002 (added) | manifest facts are not yet copied into the report |
| Differential `smaps` mapping-group and fd inventory reports | M0002 (M2-S03) | needs M0001 triggered snapshots |
| Redacted escalation bundle | M0005 (M5-S05; `docs/09`) | SP lists it under M2-S05; ownership moved, see `docs/decisions/0001-tech-notes-reconciliation.md` |
| CLI parity with SP §5 (`analyze --warmup --compare-phase A:B --json`, `compare --normalize`, `report --run`) | M0002 (added) | current flags differ; reconciled in the decision record |
| Synthetic traces: constant, warm-up/plateau, linear, restart, platform decline, allocator | Done | `tests/unit/test_analysis.py` |
| Synthetic traces: stepwise reconnect, sawtooth, outliers, collector outage, fps-change normalization, independent-metric false correlation, DMA handles without RSS growth | M0002 (added) | |
| Leak of one frame per 500 found by ledger imbalance without `smaps` | Done | `test_native_probe.py` |
| Queue growth distinguished per recognition vs per frame | Done | `test_native_probe.py` |
| Stable PSS with falling `MemAvailable` is not called an app leak | Done | |

## 4. In-application probe (PB §4; SP §7)

| Item | Status | Where |
| --- | --- | --- |
| C ABI (counter, gauge, resource, phase marker, snapshot) | Done | `native/include/axis_memlab/probe.h` |
| C++ RAII (`ResourceGuard`) and handle wrappers | Done | `probe.hpp`, `counters.hpp`, `ledger.hpp` |
| Compile-time `AXMEM_DISABLED`, `AXMEM_COUNTERS`, `AXMEM_LEDGER` | Done | exactly one per build |
| `AXMEM_SAMPLER` | M0004 | configure rejects it |
| Relaxed-atomic counters; no hot-path allocation or I/O | Done | counters mode takes no lock |
| Counter set: acquired/released/in-flight, queue depth/bytes/high-watermark/drops, sessions, reconnects, workers, stage timings, allocation failures | Done (generic `app.<name>` names; the application chooses them) | |
| `RssAnon`/`RssFile`/`RssShmem`, `Pss`/private from `/proc/self`; fd count; thread count | Done | opt-in for `smaps_rollup` and fd count |
| mmap-region count (optional) | M0003 (open, optional) | |
| Lifetime ledger: fixed capacity, generation/sequence, aggregates, oldest live ids, `events_dropped`, degraded flag | Done | LEDGER mode |
| Ledger release latency and caller-defined stage | M0003 (open) | one `ResourceKind` per stage covers "stage" today; latency not exported |
| Optional sampling of very large populations | M0003 (open) | overflow is counted, not sampled |
| Age distribution of oldest objects | Partial | oldest 8 with age; no distribution |
| `mallinfo2` allocator stats (glibc, feature-detected) | Done | opt-in |
| `malloc_info()` XML (development-only) | M0003 (open) | |
| `malloc_trim` experiment | Docs | procedure in `docs/11-investigation-workflow.md`; deliberately not in the library |
| Stage-by-stage isolation switches, queue caps and test-triggered drain | M0003 (added: pattern guide in `docs/06`; the toggles live in the application) | |
| JSONL emission on a separate low-priority task | Declined: caller-driven snapshots, no library thread | `docs/decisions/0001-tech-notes-reconciliation.md`; an optional helper stays open in M0003 |
| Outbound telemetry endpoint (TLS) | Declined for now: file sink only | host transport in M0001 `transport/telemetry.py` |
| Self-reads limited to `/proc/self` | Done | |
| < 1 MiB steady-state memory for counter-only mode | Partial | static footprint is a few tens of KiB by construction; measure on a device (M0003 open) |
| Overhead on the smallest supported device | M0003 (open, needs hardware) | host microbenchmark in `docs/10` |
| VDO integration adapter | Partial: pattern + SDK-free example (`examples/vdo_lifecycle.cpp`); a versioned real adapter needs the SDK (M0003 open) | |
| Larod integration adapter (SDK-generation specific) | Partial: same, pattern in `docs/06` (M0003 open) | |
| Queue / image / recognition / network / thread adapters | Done as patterns (`examples/queue_metrics.cpp`) | generic gauges and counters |
| Library avoids exceptions/RTTI in headers | Done for headers; `.cpp` uses `std::string`/`std::mutex` off the hot path | documented limitation |
| Thread-safe shutdown | Done | |
| No payload, pixel, plate, credential, or address in probe output | Done | validated names only; no free text |
| Linux build verified with gcc/clang | M0003 (open): developed and tested with MSVC; CI runs gcc and clang | |

## 5. Tools and techniques beyond collection (PB §4.3, §5, §6; SP §7, §10)

| Tool / technique | Status | Where |
| --- | --- | --- |
| Allocation sampler with bounded stacks, matched alloc/free, no device-side symbolization | M0004 (M4-S01…S03, S06) | |
| `addr2line`, `llvm-symbolizer`, `gdb` symbol resolution; build-id check rejecting mismatches | M0004 (M4-S04) | |
| Frame pointers / unwind metadata in profiling builds; unstripped build-id-matched symbols kept off-camera | M0004 (added) | build guidance |
| AddressSanitizer / LeakSanitizer | M0004 (M4-S05) | workstation/lab replay |
| `heaptrack`, Valgrind Massif, DHAT | M0004 (M4-S05) | replay only; Valgrind cannot work from `/proc` snapshots (restated in the M0004 doc, added) |
| Core / full memory dumps | M0005 (added): guidance only, with the privacy warning; never ordinary telemetry | |
| `gdbserver` (lab, supported Axis tooling) | M0005 (M5-S02) | no automatic activation |
| `strace` (scoped syscalls, lab) | M0005 (added) | |
| `perf` / ftrace / eBPF (vendor-approved lab images) | M0005 (M5-S04) | |
| Slab accounting, DMA-BUF debugfs | M0005 (added; M5-S03 names only shared buffers) | |
| Kernel-attribution rule: `kmalloc` events do not identify userspace `malloc` sites | Docs | stated in `docs/11` and kept in the tech notes; repeated in the M0005 doc (added) |
| Platform/service correlation with capability checks | M0005 (M5-S03) | |

## 6. Configuration (`tech_notes/configs-default.toml`)

The reference file and `configs/*.toml` differ. The repository profiles are authoritative
for M0000 and are validated strictly; the differences are carried to M0001.

| Reference setting | Repository | Disposition |
| --- | --- | --- |
| `profile = "lightweight"`; profiles `lightweight`/`standard`/`lab` (SP §6) | profiles `default`, `lightweight`, `inapp-only`, `stress-lab` | M0001 reconciles names and documents the mapping |
| `lightweight_interval_seconds` | `sample_interval_seconds` | renamed; same meaning |
| `phase_inventory_only`, `clock_monotonic` | absent | M0001 decides (monotonic is always recorded) |
| `max_sample_bytes`, `max_sample_elapsed_ms` | `max_snapshot_bytes`, `max_snapshot_seconds` | coarser units; revisit in M0001 |
| `max_deep_snapshot_bytes`, `max_deep_snapshot_elapsed_ms`, `deep_snapshot_cooldown_seconds = 900` | cooldown 3600; no separate deep caps | M0001 adds separate deep caps when the deep path exists |
| `ssh_timeout_seconds`, `max_transient_buffer_bytes` | `ssh_connect_timeout_seconds`, `ssh_command_timeout_seconds`, `transient_buffer_bytes` | split connect/command timeouts |
| `warmup_seconds = 600`, `minimum_valid_samples = 15` | 60 and 10 | placeholders; set from observed start-up behaviour (workflow S0) |
| `trend_metric`, `normalize_by = ["time", "app.frame.processed_total", …]` | `metrics`, `normalization = ["elapsed_seconds", <counter names>]` | the repository form is a list of metrics and counter names |

## 7. What remains open, by owner

| Owner | Open items |
| --- | --- |
| **M0001** | Everything in sections 1–2 marked M0001; typed reason codes; profile/config reconciliation; deep-snapshot path; retention/purge; manifest privacy fields; fixture demo; real-device compatibility evidence |
| **M0002** | Plots; rules D, E (and refinements of B, C); `H-RECONNECT`, `H-DETECTION`; step and sawtooth detection; uncertainty and reliability fields; configurable thresholds; time-to-exhaustion estimate; richer report header; CLI parity; remaining synthetic traces; differential `smaps`/fd reports |
| **M0003** | Device overhead and < 1 MiB measurement; real VDO/Larod adapters (need the SDK); `malloc_info`; ledger latency/stage; large-population sampling; optional emitter helper; Linux (gcc/clang) verification; stage-isolation guide |
| **M0004** | All of section 5 sampler/symbolization/sanitizer items |
| **M0005** | DDH, `gdbserver`, `strace`, `perf`/ftrace/eBPF, slab/DMA-BUF debugfs, core-dump guidance, server report ingestion, escalation bundle |
