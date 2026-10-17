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
| `/proc/meminfo` (`MemAvailable`, `MemFree`, `Cached`, `Shmem`, `Slab`, `SReclaimable`, `SUnreclaim`) | Done (M0001) | `sources/meminfo.py`; missing `MemAvailable` is explicit |
| `/proc/vmstat` | Done (M0001) | `sources/vmstat.py` |
| `/proc/pressure/memory` (PSI) | Done (M0001) | absent PSI is an explicit `missing` state |
| `/proc/PID/status` (`VmSize`, `VmRSS`, `RssAnon`, `RssFile`, `RssShmem`, `VmSwap`, threads) | Done (host any readable PID; in-app `/proc/self`) | |
| `/proc/PID/stat` (start ticks, CPU, faults) | Done (host and in-app start ticks) | |
| `/proc/PID/smaps_rollup` | Done (host and in-app, sparse) | no fallback to `smaps` |
| `/proc/PID/fd` count and target classes (socket, pipe, `dmabuf`, file, …) | Done (host and in-app count) | targets are classified and discarded |
| `/proc/PID/fdinfo`, `Private_Hugetlb` | M0001 (open) | not parsed or collected yet |
| `/proc/PID/maps`, `/proc/PID/smaps` (triggered, once) | M0005 (added): needs a separate safety review | `deep` is refused: `snapshot --level deep` exits 3 and `allow_deep_snapshot=true` is rejected; M2-S03 differential reports depend on it |
| `SwapPss` | Done (M0001) | |
| Boot id for segmentation | Done (host, in-app, analysis) | |
| Cgroup memory (v1/v2) | Done (M0001, conditional) | `sources/cgroup.py`; correlation use in M0005-S03 |
| Cross-process summary (accessible PIDs) | M0001 (open) | `discover` resolves the target by command name only |
| Axis app log / `journalctl` / syslog | M0001 (open): needs a different, reviewed allowlist; log text may be sensitive | |
| Axis device server report | M0005 (M5-S05), runbook mentions the export | exported by an authorized operator |
| Device Data Hub CPU/memory topics | M0005 (M5-S01) | `sources/ddh.py` stays a placeholder until then |
| `ps` / `top` | Declined as a source of truth | PB §5: convenience only; discovery does not execute tools |

## 2. Collection policy and host tooling (PB §2, §7, §8; SP §3, §5, §6, §9)

| Item | Status | Where |
| --- | --- | --- |
| Level 0 device facts and capability probing | Done (M0001) | `discover`, `capability` records; tool presence must be checked by hand |
| Level 1 regular samples | Done (host); Done (in-app snapshots) | |
| Level 2 sparse snapshots | Done (M0001) | `smaps_rollup`, fd inventory, cgroup at `smaps_rollup_interval_seconds` |
| Level 3 triggered snapshot, cooldown, abort under memory pressure | Partial: trigger → sparse snapshot with cooldown, skip under low memory, abort below threshold are Done; the `smaps` part is blocked (deep) | |
| Level 4 development-only probes | M0005 | gated by verified compatibility |
| `discover`, `collect`, `annotate`, `snapshot`, `import`, `purge` | Done (M0001), fixture and simulated-`ssh` tested; not run on a device | `cli_device.py` |
| SSH transport: key file, host-key verification, timeouts, exponential backoff, no shell, option-injection safe | Done | `transport/ssh.py`; option acceptance checked with `ssh -G` |
| Separate audit record of SSH sessions | M0001 (open) | the device's own logs only |
| One multi-read command vs persistent connection | Done: one batched command per cycle; persistent connection not implemented; device benchmark open | `docs/10` |
| Atomic append run store, abrupt-disconnect safe, graceful Ctrl-C, no implicit restart | Done | `collection/run_store.py` |
| Compressed run store, retention and purge | Done | `--compress`, `purge` (dry run unless `--confirm`) |
| Immutable annotations / phase markers | Done | `annotate`, in-app marker |
| Collector self-timing and read errors | Done (host `collector.*`, in-app `app.probe.*`) | |
| Typed absence reasons (`missing`, `permission_denied`, `timeout`, `parse_error`, `unsupported`, `not_collected`) | Done (host and schema); in-app probe still free text | M0003 follow-up |
| Sampling profiles `lightweight` / `standard` / `lab` and limits | Partial: repository profiles and byte/time/interval limits exist; reconcile names (section 6) | M0001 (open) |
| `smaps_rollup` absent must not fall back to full `smaps` | Done | tested |
| No heavy reads during a memory-pressure emergency | Done | `sparse_skipped` event, abort |
| Process identity `(boot_id, pid, start_ticks)`; restart closes a segment | Done | collector events + analysis segments |
| Monotonic clock for slopes, UTC for coordination | Done | |
| Collector outage must not block the pipeline; bounded buffer | Done (probe drops and counts; host collector reads only) | |
| Manifest: privacy classification, consent reference, redaction status, config hash | Done | `--consent-reference`, `--redaction-status`, `config_sha256` |
| Local-only guarded archive for `cmdline`, mapping names, open-file paths | Done by omission: those are never read or stored | |
| No reboot, ACAP install/upgrade, developer-mode toggle, firmware change | Done (not implemented anywhere) | |
| Compatibility matrix from device evidence | M0001 (open): procedure written, rows need a device | `docs/01` |
| Optional one-shot device probe (`device-optional/tiny-probe`) | M0001 (only if SSH and in-app are insufficient) | evidence-driven |
| Fixture-only demo run | Done | `examples/demo-run` |
| 24 h collector soak on a device; one hour of valid device metrics | M0001 (open, needs hardware) | the milestone exit allows the fixture demo meanwhile |

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
| `AXMEM_SAMPLER` | Done (M0004) as an add-on to COUNTERS/LEDGER | configure rejects it alone or with DISABLED |
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
| Allocation sampler with bounded stacks, matched alloc/free, no device-side symbolization | Done (M0004; Linux paths CI-verified, no device run) | `docs/12`, `native/src/sampler.cpp` |
| `addr2line`, `llvm-symbolizer` symbol resolution; build-id check rejecting mismatches | Done (M0004) | `symbolization/resolve.py`; built-in ELF reader as fallback |
| `gdb` for symbol resolution | Declined: the three resolvers above cover it; `gdb` stays a manual alternative | |
| Off-camera demangling | Done (`c++filt`, optional) | names stay mangled and the report says so when absent |
| Frame pointers / unwind metadata in profiling builds; unstripped build-id-matched symbols kept off-camera | Done (M0004) | `docs/12`, section 4; `axis_memlab_sampler_flags` |
| AddressSanitizer / LeakSanitizer | Done as documentation (M0004-S05) | `docs/12`, section 6; workstation replay |
| `heaptrack`, Valgrind Massif, DHAT | Done as documentation (M0004-S05) | replay only; the Valgrind limitation is stated in `docs/12`, section 6 |
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
| **M0001** | `fdinfo` and `Private_Hugetlb`; all-process summary; Axis log access; SSH audit record; profile/config reconciliation; `tiny-probe` if needed; everything that needs a real device (compatibility rows, SSH overhead, 1 h and 24 h runs) |
| **M0002** | Plots; rules D, E (and refinements of B, C); `H-RECONNECT`, `H-DETECTION`; step and sawtooth detection; uncertainty and reliability fields; configurable thresholds; time-to-exhaustion estimate; richer report header; CLI parity; remaining synthetic traces; differential `smaps`/fd reports |
| **M0003** | Device overhead and < 1 MiB measurement; real VDO/Larod adapters (need the SDK); `malloc_info`; ledger latency/stage; large-population sampling; optional emitter helper; Linux (gcc/clang) verification; stage-isolation guide |
| **M0004** | Linux verification in CI and on a real binary; device perturbation; 32-bit ARM unwinding; PE/PDB symbolization (not planned) |
| **M0005** | Safety review for `deep` captures (`smaps`, allocator reports); DDH, `gdbserver`, `strace`, `perf`/ftrace/eBPF, slab/DMA-BUF debugfs, core-dump guidance, server report ingestion, escalation bundle |
