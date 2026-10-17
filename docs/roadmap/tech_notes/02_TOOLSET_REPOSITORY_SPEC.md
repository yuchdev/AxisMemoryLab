# Repository specification — `axis-memory-lab`

**Purpose:** Build a minimal-overhead, reproducible memory-diagnostics toolkit for FF Group CCTV analytics applications running under AXIS OS. It must attribute physical-memory growth to a memory category/subsystem as far as ordinary AXIS OS permissions allow, and generate evidence sufficient to direct a source-level fix or a vendor escalation.

**Suggested repo name:** `axis-memory-lab` (working title; no remote repository has been created).

**Outputs of the future implementation:** executable collector CLI on workstation, optional self-monitor C/C++ library, analysis/report commands, structured run archives, synthetic tests, firmware capability checks, a reproducible customer-facing report. A separate optional device probe can be added only if agentless SSH and in-app monitoring are insufficient.

## 1. Scope and exclusions

### Must provide

1. Resource discovery and ability/capability checks without requiring root.
2. Long-running low-intrusion collection of system/process metrics and application telemetry.
3. Sparse `smaps_rollup` and bounded trigger-only full `smaps` / fd map capture.
4. Support for app self-profiling when non-root SSH cannot inspect its process.
5. A complete immutable experiment record including software/hardware versions, workloads and test phase transitions.
6. Trend analyses for device memory, private resident memory, PSS, process I/O/FD/thread counts, and app-specific counters.
7. In-app ownership instrumentation helpers for frame buffers, queues, Larod tensors/jobs, event queues and connections.
8. Offline stack symbolization if the app supplies allocation samples; never claim reconstruction from memory maps alone.
9. Machine-readable summary and readable Markdown/HTML report; graph generation optional until M2.
10. Explicit tracking of missing fields, permission denials and collector overhead.

### Non-goals for initial release

- Real-time memory heap inspection through unrestricted debugger attachment.
- Root privileges, kernel rebuilds, firmware modifications, eBPF or ftrace as mandatory dependencies.
- Running Valgrind on the camera or recovering historical heap stacks from `smaps`.
- Collecting raw surveillance images, recognized plates, customer credentials, or network payloads.
- Universal compatibility with all ACAP SDK/AXIS OS revisions; use detected capabilities and explicit supported-version matrix.
- Independently recreating AXIS OS video buffer / SDK internals.

## 2. Design principles / constraints

- **Two deployment surfaces, one data model:** Python 3.11+ workstation tools; portable C/C++17 in-app library, with C ABI where needed. Native C or C++ app support is an engineering assumption to validate.
- **Default agentless:** obtain safe procfs readings with SSH from workstation when permissions allow. Optional on-device self-monitor uses `/proc/self/...`, process-owned counters and outbound client connection (or authorized host polling).
- **No camera-side database.** Short bounded memory buffer only; write to host. No high-rate writes to internal flash.
- **Read-only first.** All mutation, application restart, developer features and heavy sampling require explicit opt-in.
- **No silent privilege escalation.** Fail with capability status and a remediation path, not a fabricated measurement.
- **Deterministic workloads:** allow external phase annotations and stable scenario identifiers.
- **Bounded overhead:** fixed-size allocations, rate limits, deadlines, byte caps, and graceful degradation.
- **Typed units and provenance:** represent KB/kB/KiB conversions unambiguously and preserve original source lines where needed.
- **Source-level correctness:** in-app counters update on resource ownership boundaries, not arbitrary stages that may double count.

## 3. Architecture

```text
 AXIS camera (ACAP / restricted Linux)
 ├─ FF Group CCTV process
 │  ├─ standard procfs (/proc/self/status, smaps_rollup)
 │  ├─ optional C/C++ library (counters, queue gauges, ownership ledger)
 │  └─ optional outbound diagnostic endpoint; no frame payloads
 ├─ permitted OS procfs metrics (system wide /proc/meminfo, vmstat, PSI)
 └─ optional one-shot device probe (only if available/approved)
                      |
                  SSH / TLS
                      |
 Remote workstation
 ├─ axis-memlab discover / collect / snapshot / annotate
 ├─ adapters: ssh-procfs, inapp-jsonl, optional DDH, offline import
 ├─ typed normalizer / schema validator
 ├─ compressed run store (append-only JSONL + artifact manifest)
 ├─ analyze: deltas, phase splits, slopes, correlation and suspicion ranking
 ├─ symbolize: build-ID matched allocation stack samples (if present)
 └─ report: Markdown, CSV, optional plots and HTML
```

`memlab` does not need a deployed continuous on-camera daemon for M1. SSH polling overhead must be benchmarked on the device; if login/crypto cost is too high, prefer a single short-lived remote collection command that returns multiple procfs readings, a persistent authenticated connection, or in-app outbound snapshots.

## 4. Repository structure (proposed)

```text
axis-memory-lab/
├── README.md
├── LICENSE
├── pyproject.toml
├── docs/
│   ├── 00-purpose-safety.md
│   ├── 01-axis-compatibility.md
│   ├── 02-protocol-and-schema.md
│   ├── 03-metrics-semantics.md
│   ├── 04-diagnostic-decision-tree.md
│   ├── 05-collecting-on-axis.md
│   ├── 06-integrating-cpp-probes.md
│   ├── 07-offline-analysis.md
│   ├── 08-security-privacy.md
│   ├── 09-customer-escalation.md
│   └── 10-benchmarking-overhead.md
├── configs/
│   ├── default.toml
│   ├── lightweight.toml
│   ├── inapp-only.toml
│   └── stress-lab.toml
├── schemas/
│   ├── record-v1.schema.json
│   ├── run-manifest-v1.schema.json
│   └── report-v1.schema.json
├── src/axis_memlab/
│   ├── cli.py
│   ├── capability.py
│   ├── records.py
│   ├── transport/{ssh.py,telemetry.py,offline.py}
│   ├── sources/{proc_status.py,meminfo.py,vmstat.py,smaps.py,fd.py,psi.py,cgroup.py,ddh.py}
│   ├── collection/{scheduler.py,identity.py,run_store.py,triggers.py}
│   ├── analysis/{trend.py,phase.py,classify.py,compare.py,correlate.py}
│   ├── symbolization/{stackmap.py,resolve.py}
│   └── reporting/{markdown.py,csv.py,plots.py,html.py}
├── native/
│   ├── include/axis_memlab/{probe.h,probe.hpp,counters.hpp,ledger.hpp}
│   ├── src/{probe.cpp,counters.cpp,ledger.cpp,proc_self.cpp,emitter.cpp}
│   ├── examples/{c_api.c,cpp_raii.cpp,vdo_lifecycle.cpp,queue_metrics.cpp}
│   ├── tests/
│   └── CMakeLists.txt
├── device-optional/
│   ├── README.md
│   └── tiny-probe/             # only after verified need
├── tests/
│   ├── fixtures/{procfs/,runs/,stacks/,corrupt/}
│   ├── unit/
│   ├── integration/
│   ├── synthetic-leaks/
│   └── performance/
├── examples/
│   ├── demo-run/
│   ├── reports/
│   └── scenario-matrix.md
├── milestones/
│   ├── 0001-discovery-and-collection.md
│   ├── 0002-trend-analysis-and-reports.md
│   ├── 0003-inapp-profiling.md
│   ├── 0004-allocation-samples-and-symbolization.md
│   └── 0005-axis-advanced-diagnostics.md
└── .github/workflows/{python-ci.yml,native-ci.yml,schemas.yml}
```

The files listed above are target structure, not a claim that an implementation exists. Prefer `src/` layout for Python package and a separate native library. Avoid making the toolset dependent on any single FF Group product-specific API.

## 5. CLI contract

The future CLI executable is `axis-memlab`. Command examples below are **design contracts**, not executable commands at present:

```text
axis-memlab discover --ssh user@camera --app ff_app_name --json
axis-memlab collect --ssh user@camera --app ff_app_name \
  --config configs/lightweight.toml --scenario T2 --out runs/2026-10-16-cameraA-T2/
axis-memlab annotate --run RUN_DIR --phase "recognition-enabled" --note "constant FPS"
axis-memlab snapshot --run RUN_DIR --level sparse
axis-memlab snapshot --run RUN_DIR --level deep --confirm-intrusive
axis-memlab import --input telemetry.jsonl --run RUN_DIR
axis-memlab analyze --run RUN_DIR --warmup 10m --compare-phase A:B --json
axis-memlab compare --baseline BASE_RUN --candidate FIXED_RUN --normalize frames
axis-memlab symbolize --run RUN_DIR --symbols /build/symbols/
axis-memlab report --run RUN_DIR --format markdown --out report.md
```

Contract requirements:

- `discover`: list firmware / CPU architecture / process selectors, available procfs paths, permission probes, SSH identity, optional tools and missing capabilities. May inspect command name and binary path, but must never assume `pidof` or `pgrep` exists. Never print secrets.
- `collect`: fixed bounded interval scheduler, dynamic PID discovery, reconnect/SSH error handling, atomic append of data, markers, backpressure and graceful Ctrl-C; **no implicit app restarts**.
- `annotate`: add immutable event record to log; never rewrite historical time samples.
- `snapshot`: force sparse/deep capture, honoring permissions and deadlines. The `deep` option requires explicit confirmation.
- `import`: ingest device-generated JSONL plus optional bounded artifacts; preserve source-specific precision and missingness.
- `analyze`: reports memory rates and confidence, not a categorical leak judgment.
- `compare`: equivalence checks for device/firmware/config/workload; flags invalid comparisons.
- `symbolize`: only resolve stacks in a trace that actually includes allocation program counters; never infer stacks from procfs pages.
- `report`: output self-contained report with figures/tables, exposure/caveat labels and referenced artifacts.

## 6. Collection and data contracts

### Run identity

A `run_id` (UUID), `device_id` (operator-defined pseudonym), `boot_id` (if readable), `process_id`, `process_start_ticks`, `clock` (monotonic ns plus UTC ns), application build ID, hardware model, firmware, workload/config hash, scenario/phase tags.

Do not identify a running app solely by PID: detect restarted processes with `boot_id + PID + start_ticks`. On restart, close a segment and create a new segment. Samples must not be joined across segments into one false upward/downward trend.

### Versioned record protocol

Each line is an independent JSON object; required keys:

- `schema_version`: `1`.
- `record_type`: `sample`, `event`, `capability`, `artifact`, `error`, `run_start`, `run_stop`.
- `run_id`, `producer`, `ts_utc_ns`, `ts_mono_ns` (may be `null` for imported legacy data).
- `identity`: device pseudonym, PID and start ticks when applicable.
- `metrics`: map of metric name to typed `{value, unit, source}` objects; omit unknown values or set `{available:false, reason}`.
- `annotations`: scenario phase and other declared context (optional).

No imaging/personal data; no raw environment variables, credentials or addresses in uploaded public reports. Allow local technical artifacts (mapping path names, process args, debugging symbols) only in separate guarded diagnostic archive, redacted for external sharing.

### Metrics naming

Use explicit namespaces: `system.mem.available_bytes`, `system.mem.slab_unreclaim_bytes`, `system.mem.shmem_bytes`, `system.psi.memory_some_avg10`, `process.rss_bytes`, `process.rss_anon_bytes`, `process.pss_bytes`, `process.private_clean_bytes`, `process.private_dirty_bytes`, `process.fd_count`, `process.threads_count`, `app.frame.inflight_bytes`, `app.queue.<name>.bytes`, `app.larod.tensor_count`.

All size metrics normalized to bytes; input `kB` from procfs interpreted as 1024 bytes. Never divide resident page data by total RAM to infer individual allocation site counts. Measurement absence must retain reason (`missing`, `permission_denied`, `timeout`, `parse_error`, `unsupported`, `not_collected`) distinct from `0`.

### Sampling profiles

| Profile | Process/status/system metrics | `smaps_rollup` | Mapping/fd inventories | app counters |
|---|---:|---:|---|---:|
| `lightweight` (default) | 15 s | 120 s | Manual or event-triggered | 15 s |
| `standard` | 10 s | 60 s | At phase boundaries | 10 s |
| `lab` | 2–5 s | 30 s* | Explicit bounded probes | 2–5 s |

`*` Lab frequencies subject to device overhead measurement. Production uses lightweight profile initially. `smaps_rollup` absent must not silently fall back to continuous full `smaps`. Limits in configuration: max bytes/interval, max elapsed read budget, max artifacts, trigger cooldown, maximum remote data queue, and total test duration. Apply exponential backoff on repeated SSH failures.

## 7. In-application library contracts

### C ABI

```c
/* Suggested API; implementation and exact ABI to be defined */
void axmem_counter_add(const char *name, uint64_t delta);
void axmem_gauge_set(const char *name, uint64_t value);
void axmem_resource_acquire(uint64_t id, uint32_t kind, uint64_t bytes);
void axmem_resource_release(uint64_t id, uint32_t kind);
void axmem_phase_marker(const char *phase);
int  axmem_emit_snapshot(void);
```

### C++ wrapper

- No global allocator replacement by default; no dependency on exceptions or RTTI when integrating if the app disables them.
- RAII `ResourceGuard` optional, pairing acquire/release only when aligned with third-party API ownership.
- Nonblocking fixed-capacity counters; no dynamic allocations on hot video path after initialization; `noexcept` where appropriate.
- Atomic operations or well-defined single-writer ownership; ledger metrics with explicit consistency notes.
- Leak-safe failure paths, no recursive logger dependence, and thread-safe shutdown.
- Compile-time `AXMEM_DISABLED`, `AXMEM_COUNTERS`, `AXMEM_LEDGER`, `AXMEM_SAMPLER` features. Disabled build must optimize away hooks and have benchmarkable negligible overhead.
- JSONL telemetry records generated on a separate low-priority task; on overflow, drop and increment telemetry drops; never backpressure frame processing.
- Self-procfs snapshots must respect app sandbox and only read `/proc/self` or documented accessible paths.

### Per-subsystem integration adapter points

1. **VDO**: count stream start/stop, frame/buffer acquisition/release, bytes in flight and stream/session IDs. Audit exceptional, timeout and early-return branches. Use the actual API-specific free/unref sequence.
2. **Larod/inference**: tensors created/destroyed/tracked, model instances, jobs submitted/completed, buffer byte sizes, imported FDs, early cancel/reconnect conditions. Different SDK generations have different destruction semantics; adapt per API generation.
3. **Image processing / decoding**: temporary RGB/YUV images, resized images, GPU/CPU memory operations, allocator/pool high-water marks.
4. **Recognition/metadata**: result objects, work queues, caches and retry buffers, high-water marks, age distribution of oldest objects.
5. **Networking/event delivery**: pending sends, reconnect attempts, socket count, retry queue retention; log/distribution queues.
6. **Thread lifecycle**: worker count, TLS caches and shutdown state when measurable.

### Optional stack sampler (M4)

- Off by default. Sample only a bounded fraction of specified allocations, capture raw program counters/build-ID mapping, allocation size, category and event ID; matched sampled free events required to estimate surviving sampled allocations.
- Cumulative allocation volume must never be mislabeled live outstanding bytes.
- No device-side symbolization, demangling, uncontrolled `backtrace()` in allocation hooks or malloc-recursive operations.
- Portability and coverage documented: all libc allocators/new overloads/mmap/SDK hardware buffer allocations **cannot** be assumed intercepted by one mechanism.
- If malloc hooks are too risky, instrument selected application allocation sites instead; do not ship unstable interposition as required feature.

## 8. Analysis algorithms

### Trend analysis

- Group by run segment, app build, scenario and phase.
- Validate sampling gaps, warm-up exclusion, constant workload and monotonic counters.
- Compute start/end deltas, per-hour and workload-normalized deltas; also robust regression (e.g., Theil–Sen slope) and confidence band when sufficient points.
- Detect stepping (reconnect) and plateau behavior; do not extrapolate exhaustion if there is a plausible cap/plateau or insufficient samples.
- For a machine-readable result, store `slope_bytes_per_hour`, `sample_count`, `window_seconds`, `estimated_uncertainty` and `is_reliable` with reasons. Thresholds configurable by scenario and RAM budget, never hard-coded into measurement itself.

### Attribution assistant (heuristic, not definitive)

- Rule A: app PSS and private dirty grow, app object/queue bytes grow ⇒ likely app retention.
- Rule B: app RSS/anonymous grows; app live bytes stable; allocator heap/arenas grow ⇒ allocator caching/fragmentation or uninstrumented native allocations.
- Rule C: process app metrics stable, camera `Shmem`/other service resident grows ⇒ investigate platform video buffers or other services.
- Rule D: `SUnreclaim`/slab grows while app RSS stable ⇒ investigate kernel allocations but state that allocator and owner are unconfirmed.
- Rule E: fd/anon DMA buffer handles monotonically grow ⇒ resource handle lifecycle suspect; ownership must still be verified.
- Rule F: growth per reconnect ⇒ initialization/teardown lifecycle suspect.

Every finding must list supporting metric names, time intervals, contradictory evidence and outstanding tests; report language should say *suspected* until confirmed by live-resource counts, stack traces, code audit, a reproducing minimum case, or a fix.

## 9. Safety, security and privacy

- Use dedicated least-privilege SSH identity and keys; no plaintext passwords in run archives or command logs.
- Validate host keys; preserve access audit records; close sessions cleanly.
- Allow outbound TLS only if authenticated and feasible; never open a public diagnostic endpoint on the camera by default.
- `deep` captures potentially sensitive `cmdline`, memory mapping names and open-file paths: local-only, restricted by default.
- In application, forbid logging frame payload, image pixels, plate strings, recognition text, credentials, TLS key material, and customer IPs in public reports.
- Enforce device memory overhead target **< 1 MiB steady-state added memory for counter-only mode** as a design goal, not a guaranteed result. For extra samplers, budgets must be configured per camera model.
- Enforce host storage retention and purge tooling; each run has a `privacy_level`, `consent` or approved incident identifier, and redaction status in manifest.
- No background reboot, ACAP install/upgrade, developer-mode toggling or firmware change without explicit operator action.

## 10. Tests and quality gates

### Parser tests

- Linux kernels with absent `smaps_rollup`, missing `MemAvailable`, different status field order, older/newer `smaps` keys and inconsistent whitespaces.
- Procfs kB-to-byte conversion; empty/missing/error values; `0` preserved as real measurement.
- More than one same-name process, PID reuse, PID disappearance between reads, process zombie, fast restart, `boot_id` missing and clock drift.
- FD symlinks failing/vanishing, deleted mappings, shared mappings, anonymous GPU DMA handles, permission denied.
- Malformed truncated snapshots, JSONL partial final line, UTF-8/path oddities, large mapping lists.
- Cgroups v1/v2 detection, enabled/disabled PSI, memory swap disabled.

### Analysis tests (synthetic traces)

- Constant baseline; warm-up and plateau; truly linear growth; stepwise reconnect leak; cyclic sawtooth queues; random outliers; process restart; collector outage.
- Simulated heap growth with stable file cache; growing DMA handles without RSS growth; changing FPS normalizations; false correlation between two independent metrics.
- Trend calculations normalized per hour/frame/recognition; invalid warm-up duration; insufficient samples.
- Build-ID mismatch rejects stack resolution rather than producing false symbols.

### Integration / acceptance

1. A permitted non-root Axis SSH account can run discovery without privileged commands; unsupported data clearly reported.
2. Collector can operate for 24h on representative test device with no unbounded host memory growth, bounded process count and valid JSONL after abrupt disconnect.
3. Counter-only app mode adds minimal and measured CPU/RSS overhead; record baseline/device measurements rather than relying on generic threshold claims.
4. Synthetic FF-like camera pipeline leaking one frame per 500 frames is identified by resource-ledger imbalance, even if `smaps` is unavailable.
5. Synthetic retained recognition queue is detected and its growth per recognition is distinct from growth per frame.
6. A test with stable process PSS but decreasing `MemAvailable` does not get classified as a confirmed app heap leak.
7. A repeatable `T4` reconnect leak is evident in phase report and fix comparison.
8. Reports must include all missing-capability reasons, device and build IDs, timeline, graph/sparkline or data table, suspected subsystem, confidence and next test.
9. No telemetry payload or customer report contains a test plate string, image bytes or sample credential.
10. All parser and schema tests run offline on standard Linux CI; integration with actual cameras is an optional gated hardware job.

## 11. Milestones and story decomposition

### 0001 — Device discovery, data schema and safe collection

Stories:
- M1-S01: Establish compatibility/capability matrix for AXIS OS generations and SoCs (manual fixture driven).
- M1-S02: Define versioned run and record JSON schemas, unit semantics and source provenance.
- M1-S03: Implement robust parsers for `status`, `meminfo`, `vmstat`, `stat`, `smaps_rollup` and PSI.
- M1-S04: Implement SSH transport with host-key verification, timeout and process selection via `/proc`.
- M1-S05: Implement low-overhead scheduler, bounded snapshots and append-only run archive.
- M1-S06: Implement phase annotations, PID/start-time segmentation and export to CSV.
- M1-S07: Document installation, security and customer runbook.

**Exit:** a real camera (where authorized) yields 1h valid metrics, or a fixture-only demo demonstrates all behavior without device access.

### 0002 — Comparison, interpretation and reporting

Stories:
- M2-S01: Implement trend engine and warm-up-aware robust growth rates.
- M2-S02: Implement segment/phase comparisons and normalization by frame/detection event count.
- M2-S03: Implement differential `smaps` mapping-group and fd inventory reports.
- M2-S04: Implement conservative evidence-based classification with uncertainty and no false definitive leak language.
- M2-S05: Generate Markdown/CSV/optional PNG/HTML reports and customer escalation bundle.
- M2-S06: Build synthetic test traces for leak, fragmentation, shared-memory and platform-growth patterns.

**Exit:** datasets yield a useful report that ranks next steps rather than generic plots alone.

### 0003 — C/C++ in-app diagnostics and FF Group adapter points

Stories:
- M3-S01: Implement stable C ABI and C++ RAII wrappers with compile-time off/counters/ledger modes.
- M3-S02: Provide procfs self-memory sampling and bounded JSONL telemetry; no frame-path I/O.
- M3-S03: Implement bounded resource lifetime ledger with overflow accounting and optional sampling.
- M3-S04: Instrument VDO video frame acquisitions, transfers and releases behind a versioned adapter.
- M3-S05: Instrument Larod tensor/job lifecycles and buffer/Fd ownership per SDK generation.
- M3-S06: Instrument queues, images, recognition events, network retry buffers and worker counts.
- M3-S07: Measure overhead and test simulator against injected lifecycle defects.

**Exit:** app reports the exact stage whose live resource count increases on an artificial leak, with no mandatory privileged access.

### 0004 — Allocation samples and offline stack attribution (development-only)

Stories:
- M4-S01: Profile sampler safety design, coverage specification and feature gating.
- M4-S02: Implement bounded stack capture for chosen allocation sites or allocation hooks.
- M4-S03: Implement matched alloc/free sampling with conservative outstanding allocation estimates.
- M4-S04: Build-ID tracking, symbol lookup and off-camera demangling.
- M4-S05: Integrate sanitizers and heaptrack/Massif instructions for host replay/compatible lab environment.
- M4-S06: Validate CPU/RSS perturbation and failure cases.

**Exit:** known synthetic heap allocations resolve to source locations and stack traces on host, not camera.

### 0005 — Advanced AXIS OS and platform escalation (optional)

Stories:
- M5-S01: Firmware-specific DDH adapter for CPU/memory utilization when supported.
- M5-S02: Restricted SSH Developer Mode / `gdbserver` support guide, no automatic activation.
- M5-S03: Platform service/cgroup and shared-buffer/camera-driver correlation with capability checks.
- M5-S04: Vendor-approved perf/ftrace/eBPF guides for supported lab images; no baseline dependency.
- M5-S05: Root-cause pack: correlate repro, platform version, app counters, memory maps, symbols and Axis server report.

**Exit:** an escalation to Axis or FF Group can reproduce and classify unresolved OS/library/resource leaks with clear permission boundaries.

## 12. Implementation order and decisions to record

Prioritize **M1 + M2** before instrumenting the app; this establishes whether the growing memory is even in the app process. In parallel, audit documented VDO/Larod library ownership semantics. Then implement M3 counters for the specific growing stage. M4 is justified only if live-resource counters and comparisons cannot identify source-level ownership. M5 only if evidence indicates another Axis service, kernel driver or hardware/shared allocator.

**Open technical decisions (do not block M1):** exact camera family, ACAP SDK and library versions, SSH access available, whether the FF Group app is native C/C++ or containerized, whether reproducible video input exists, whether device owner permits developer mode or firmware comparison, and how frequently RAM exhaustion occurs. The repo's capability model must accommodate each without hard-coding an answer.
