# Milestone 0000 — Repository scaffolding for `axis-memory-lab`

> **Implementation instructions for a coding agent.** This milestone comes **before** `0001-discovery-and-collection`. Build the engineering foundation of the toolset, **not** the device diagnostics themselves.
>
> **Status:** specification/instructions; no implementation is implied by the existence of this document.
>
> **Project:** a low-overhead memory-diagnostics toolkit for FF Group CCTV applications running under AXIS OS, with analysis on a remote workstation and optional native C/C++ application instrumentation.

## 0. Agent mission and execution rules

Act as the implementation engineer. Create a clean, reproducible repository named `axis-memory-lab`, or scaffold an existing repository of that name **without overwriting existing files or history**.

1. Start by inspecting repository state, current branch, tracked files, operating-system/toolchain availability, and existing project rules. If the repository does not exist locally, create a *local* repository layout. **Do not create a remote GitHub repository, commit to an unrelated repository, push, or open a pull request unless the execution environment already provides an authorized target and the user has requested such an action.** If working on an existing repository, use a feature branch such as `chore/0000-repository-scaffolding` when appropriate.
2. Read and reconcile the companion specifications: `01_DIAGNOSTIC_PLAYBOOK.md`, `02_TOOLSET_REPOSITORY_SPEC.md`, `03_FIRST_HOUR_COMMANDS.md`, and `configs-default.toml`. The present milestone refines the initial scaffold; the architecture and diagnostic constraints in those documents remain authoritative.
3. Implement **only** the baseline structure, development workflow, contract skeleton, synthetic examples, and tests described below. Do not jump ahead and implement SSH collection, procfs parsers, AXIS OS adapters, video API instrumentation, allocation hooks, trend analysis, or reports.
4. Make the scaffold **actually install, import, build and test**. Do not create a forest of empty files merely to match a tree. A feature not implemented yet should have an intentional, documented boundary, with a deterministic nonzero error for attempted use.
5. Keep the initial build **fully offline-testable** with no camera, no root account, no Axis SDK, no proprietary FF Group source, no SSH server, and no real surveillance material.
6. After implementation, run every documented quality-gate command that the current environment supports. Fix issues before completion. Report **which commands passed, which were not run and why, the final tree, and any decisions/deviations**. Never claim that camera profiling works after M0000.

### In-scope outcome

A developer can clone the repository, create a Python environment, install the host CLI, display help/version, validate example configuration and schemas, execute automated tests, and compile a deliberately disabled native probe integration example. CI exercises these workflows.

### Explicit non-goals

- No connection to an Axis camera; no discovery, procfs sampling, SSH execution, in-camera application lifecycle changes, ACAP packaging, or telemetry transport.
- No functioning allocation tracking, nontrivial native probe implementation, resident-memory attribution, symbolization, graphing, or reports.
- No camera firmware modification, privileged commands, eBPF/ftrace/perf, remote debugger, Valgrind, or camera-side daemon.
- No committed credentials, customer addresses, CCTV frames, license plates, recordings, symbol files, core dumps, real run archives, or production telemetry.
- No invented compatibility assertions for AXIS OS / camera / SoC / VDO / Larod versions.

## 1. Engineering decisions fixed by this milestone

| Topic | Decision | Rationale |
|---|---|---|
| Repository | `axis-memory-lab` (working name) | Separate from proprietary application code |
| Host language | Python **3.11+** | Standard `tomllib`, typed interfaces, portability |
| Python layout | `src/axis_memlab` with `pyproject.toml` | Prevent accidental imports from repository root |
| Host executable | `axis-memlab` | Single entry point for eventual workflows |
| Native integration | C ABI + optional C++17 wrappers | Can be included in a native ACAP application later |
| Native build | CMake **3.20+**, C/C++17 for the C++ targets | Independent of the AXIS SDK at scaffold stage |
| CLI framework | `argparse` from the Python standard library | No hard dependency on an external CLI framework |
| Packaging | PEP 621 + setuptools | Familiar editable installs and wheel builds |
| Configuration | TOML | Read with Python's `tomllib`; explicit safe defaults |
| Telemetry envelope | Versioned JSON Lines / JSON Schema Draft 2020-12 | Works for stream append and offline validation |
| Unit convention | Bytes internally; timestamps explicitly tagged | Prevent `kB`/KiB confusion and false comparisons |
| Baseline tests | `pytest`, `ruff`, `mypy`, `jsonschema` | Basic correctness, format/lint, types, wire contracts |
| Runtime dependencies | Minimize; no camera, network or plotting dependency | Small host footprint; cheap bootstrap |
| Initial license | Preserve any existing valid license; otherwise record licensing as undecided | Do not choose legal terms on behalf of the owner |
| Initial CI | GitHub Actions, Linux host and native builds; Python smoke tests on macOS/Windows where practical | No secrets or hardware needed |

Record any unavoidable change to these decisions in `docs/decisions/0000-bootstrap.md` with motivation and trade-offs. **Do not silently change data names, CLI naming, or safety defaults.**

## 2. Required target directory tree

Use the tree below as the scaffold target. Create functional files where marked `*`; for later milestones, create meaningful `README.md`/`__init__.py` placeholders rather than nonworking imitation implementations.

```text
axis-memory-lab/
├── README.md *
├── CONTRIBUTING.md *
├── SECURITY.md *
├── CHANGELOG.md
├── .editorconfig *
├── .gitignore *
├── pyproject.toml *
├── docs/
│   ├── 00-purpose-safety.md *
│   ├── 01-axis-compatibility.md
│   ├── 02-protocol-and-schema.md *
│   ├── 03-metrics-semantics.md *
│   ├── 04-diagnostic-decision-tree.md
│   ├── 05-collecting-on-axis.md
│   ├── 06-integrating-cpp-probes.md *
│   ├── 07-offline-analysis.md
│   ├── 08-security-privacy.md *
│   ├── 09-customer-escalation.md
│   ├── 10-benchmarking-overhead.md
│   └── decisions/0000-bootstrap.md *
├── configs/
│   ├── default.toml *
│   ├── lightweight.toml *
│   ├── inapp-only.toml *
│   └── stress-lab.toml *
├── schemas/
│   ├── record-v1.schema.json *
│   ├── run-manifest-v1.schema.json *
│   └── report-v1.schema.json *
├── src/axis_memlab/
│   ├── __init__.py *
│   ├── __main__.py *
│   ├── cli.py *
│   ├── config.py *
│   ├── errors.py *
│   ├── capability.py
│   ├── records.py *
│   ├── transport/
│   │   ├── __init__.py
│   │   ├── ssh.py
│   │   ├── telemetry.py
│   │   └── offline.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── proc_status.py
│   │   ├── meminfo.py
│   │   ├── vmstat.py
│   │   ├── smaps.py
│   │   ├── fd.py
│   │   ├── psi.py
│   │   ├── cgroup.py
│   │   └── ddh.py
│   ├── collection/
│   │   ├── __init__.py
│   │   ├── scheduler.py
│   │   ├── identity.py
│   │   ├── run_store.py
│   │   └── triggers.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── trend.py
│   │   ├── phase.py
│   │   ├── classify.py
│   │   ├── compare.py
│   │   └── correlate.py
│   ├── symbolization/
│   │   ├── __init__.py
│   │   ├── stackmap.py
│   │   └── resolve.py
│   └── reporting/
│       ├── __init__.py
│       ├── markdown.py
│       ├── csv.py
│       ├── plots.py
│       └── html.py
├── native/
│   ├── README.md *
│   ├── CMakeLists.txt *
│   ├── include/axis_memlab/
│   │   ├── probe.h *
│   │   ├── probe.hpp *
│   │   ├── counters.hpp
│   │   └── ledger.hpp
│   ├── src/README.md
│   ├── examples/
│   │   ├── c_api.c *
│   │   ├── cpp_raii.cpp *
│   │   ├── vdo_lifecycle/README.md
│   │   └── queue_metrics/README.md
│   └── tests/
│       └── CMakeLists.txt *
├── device-optional/
│   └── README.md
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_cli.py *
│   │   ├── test_config.py *
│   │   └── test_records.py *
│   ├── integration/
│   │   └── test_distribution.py *
│   ├── performance/README.md
│   ├── synthetic-leaks/README.md
│   └── fixtures/
│       ├── README.md *
│       ├── procfs/README.md
│       ├── runs/sample-run/manifest.json *
│       ├── runs/sample-run/records.jsonl *
│       ├── stacks/README.md
│       └── corrupt/invalid-record.json *
├── examples/
│   ├── README.md
│   ├── scenario-matrix.md
│   └── reports/README.md
├── milestones/
│   ├── README.md *
│   ├── 0000-repository-scaffolding.md *
│   ├── 0001-discovery-and-collection.md
│   ├── 0002-trend-analysis-and-reports.md
│   ├── 0003-inapp-profiling.md
│   ├── 0004-allocation-samples-and-symbolization.md
│   └── 0005-axis-advanced-diagnostics.md
└── .github/
    ├── ISSUE_TEMPLATE/bug_report.md
    ├── pull_request_template.md *
    └── workflows/
        ├── python-ci.yml *
        ├── native-ci.yml *
        └── schemas.yml *
```

**Practical file-creation rule:** create placeholder files for future implementation with a short module docstring explaining the owning milestone and intended public boundary. **No stubs returning fabricated metrics, successful empty reports, or zero-filled memory observations.** `README.md` placeholders are preferable for modules not yet useful. Avoid default config values or schema examples that imply real camera support.

## 3. Python packaging and developer workflow

### 3.1 `pyproject.toml`

Implement a valid PEP 621 project using setuptools and package discovery rooted at `src`.

Required properties:

- Distribution name `axis-memory-lab` and package name `axis_memlab`.
- `requires-python = ">=3.11"`.
- Console script: `axis-memlab = "axis_memlab.cli:main"`.
- Internal provisional version `0.0.0` (or a consistent `0.0.0+scaffold` mechanism; do not imply a working release).
- Only genuinely required runtime dependencies, preferably none for initial CLI/config features.
- A `dev` optional-dependency group containing pytest, ruff, mypy, jsonschema and build tooling; put version bounds in a coherent, maintainable style.
- `pytest` config using `tests/` and strict-marker/strict-config behavior.
- `ruff` lint and formatting configuration for project sources and tests.
- Strict or near-strict `mypy` for new code, with documented exceptions only when unavoidable.
- License metadata only after checking the repository's existing licensing decision. Do not invent an MIT/Apache/proprietary license.

Do not add Poetry, Conda, Docker, Poetry lockfiles, binary dependencies or custom code generators merely to bootstrap this project. Any dependency added must have a purpose.

### 3.2 Expected local commands

Make all of the following commands meaningful on a developer machine:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
axis-memlab --version
axis-memlab --help
python -m axis_memlab --help
axis-memlab config check --file configs/default.toml
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src/axis_memlab
python -m build
```

For platforms where the venv activation command differs, document the native equivalent. If a pre-existing dependency or setup constraint prevents some commands, report it rather than quietly excluding that check from documentation.

## 4. CLI scaffold contract

### 4.1 Implemented in milestone 0000

- `axis-memlab --help`: displays the command tree; exit `0`.
- `axis-memlab --version`: displays `axis-memory-lab 0.0.0`; exit `0`.
- `python -m axis_memlab`: same parser as console-script entry point.
- `axis-memlab config check --file <path>`: parses TOML, validates safety values, required configuration sections, types, bounds and contradictions; reports explicit success/failure. **This is host-local and performs no device I/O.**

Prefer an independently testable `build_parser()` and `main(argv: Sequence[str] | None = None) -> int` pattern rather than calling `sys.exit()` deep inside business logic.

### 4.2 Registered but **not implemented** (M0001–M0005)

Create parser groups and meaningful `--help`/usage for the planned top-level commands:

```text
discover   — AXIS OS/process capabilities (M0001)
collect    — time-series collection (M0001)
annotate   — immutable phase/event annotations (M0001)
snapshot   — bounded sparse/deep snapshot request (M0001)
import     — ingest app/device JSONL (M0001)
analyze    — trends and conditional inferences (M0002)
compare    — controlled run comparison (M0002)
symbolize  — offline address-to-symbol resolution (M0004)
report     — evidence report generation (M0002)
```

These commands may accept the planned flags from `02_TOOLSET_REPOSITORY_SPEC.md`, but until implemented **must terminate with an actionable message, not success**. Use a dedicated `FeatureUnavailableError` (or equivalent), exit code `3`, and output such as:

```text
axis-memlab: 'collect' is planned for milestone 0001; no collection was performed.
```

Do not open network sockets, call SSH, read camera paths, make a run folder, or create successful-looking empty reports in these handlers.

### 4.3 Exit-code contract

| Code | Meaning |
|---:|---|
| `0` | Successful supported operation / help / version |
| `2` | Invalid invocation, config, or user input |
| `3` | Known feature not yet implemented |
| `4` | Failed local I/O or validation dependency (when distinguishable) |
| `1` | Unexpected internal error (print diagnosis; don't leak secrets) |

Exception: `argparse` may use code `2` for parse errors as usual. Prevent uncaught tracebacks for ordinary missing configuration files and syntax errors. Do not swallow programmer errors during tests.

## 5. Safe configuration contract

Copy and adapt `configs-default.toml` into `configs/default.toml`. Keep an explicit, consistent schema for all four profiles and validate them using `tomllib`.

### 5.1 Required sections

- `[collection]`: profile, interval(s), `smaps_rollup` interval, per-snapshot byte/time caps, total transient buffer size, deep snapshot cooldown, SSH timeouts.
- `[safety]`: `allow_root`, `allow_deep_snapshot`, `allow_remote_commands_that_mutate`, `capture_image_data`, `capture_plate_text`, `write_camera_flash`, `allow_ptrace`.
- `[analysis]`: warm-up duration, minimum samples, metric and normalization list.
- `[privacy]`: redaction and local-artifact handling flags.

### 5.2 Defaults and profile differentiation

- `default.toml`: conservative profile, values matching original proposal: regular lightweight samples every **15 seconds**, `smaps_rollup` every **120 seconds**, deep snapshots disabled, remote mutations disabled, ptrace disabled, no images/plate strings.
- `lightweight.toml`: same safe profile, optionally lower cost; document how it differs from default.
- `inapp-only.toml`: identifies that future collection uses the application's own counters rather than SSH; no assumption that SSH is available.
- `stress-lab.toml`: lab-friendly intervals/limits but **still no automatically enabled intrusive operations**, privileged commands, ptrace, camera flash writes, or surveillance data capture.

### 5.3 Validation rules

- All counts/timeouts/intervals/byte limits must be numeric in the expected type and strictly positive where appropriate; reject booleans mistaken for integers.
- Accept only documented profile names/field names. Unknown keys must generate a clear error rather than silently changing collection behavior.
- Enforce internal relationships such as transient buffer limits and per-sample maximum, if specified by the configuration model. Make those constraints explicit in docs.
- Dangerous flags must not be accepted as a way to activate device functionality that does not exist yet. At scaffold stage, treat any non-default mutation, raw-data capture, root/ptrace or deep-snapshot permissions as invalid or explicit unsupported capability.
- Configuration errors must identify the file and field without exposing credentials or environment variables.
- No `eval`, shell interpolation, external config includes, or automatic environment-variable expansion at this milestone.

`axis-memlab config check` should validate the syntax and guardrails; it must not create network activity.

## 6. Versioned schema and baseline data model

**Keep wire semantics stable and minimal, but mark M0001 as responsible for completing and freezing the protocol.** Version `1` is a provisional scaffold contract and can be clarified before real collector compatibility exists. Avoid fake protocol stability claims.

### 6.1 `record-v1.schema.json`

Use JSON Schema Draft 2020-12 with `$schema` and a stable `$id` that does not depend on a fictional deployed URL. A relative or project-defined ID is acceptable. It must validate an envelope with:

- `schema_version` integer `1`.
- `record_type` one of `sample`, `event`, `capability`, `artifact`, `error`, `run_start`, `run_stop`.
- `run_id` UUID-formatted string (or documented identifier convention).
- `producer` nonempty string (e.g., `fixture-host`).
- `ts_utc_ns` nonnegative integer; `ts_mono_ns` nonnegative integer or `null`.
- `identity` object containing a pseudonymous `device_id` and optional process fields (`pid`, `process_start_ticks`, `boot_id`), with explicitly documented absence semantics.
- `metrics` map, each metric represented as `{value, unit, source}` **or** `{available:false, reason}`, never using `0` to mean a missing sample.
- Optional `annotations` object and source metadata as documented; no video/image/plate fields.

Define metric names using namespaces such as `system.mem.available_bytes`, `process.rss_anon_bytes`, `process.pss_bytes`, `app.frame.inflight_bytes`. All byte values use the `bytes` unit. Preserve a separation between raw procfs inputs (later) and normalized units.

### 6.2 `run-manifest-v1.schema.json`

Document and validate the preliminary manifest fields: schema version, run ID, created time, pseudonymous device identity, scenario/workload label, privacy classification, initial status, optional software/firmware/build identifiers. **Do not claim hardware/firmware information is present if it was not discovered.** Absent fields should be absent or explicitly unknown, not invented.

### 6.3 `report-v1.schema.json`

Define a minimal future report envelope (schema version, run reference(s), generated timestamp, limitations, findings array). In M0000 this is **schema only**: no report generator, conclusions, suspicion ranking or charts.

### 6.4 Python records

Use typed Python `dataclass` or similarly lightweight structures for basic record/metric construction and JSON serialization. Keep `None`/unavailable distinct from integer `0`. Use a single canonical schema name and consistent key ordering for fixture readability. Do not implement a recorder or importer yet.

### 6.5 Synthetic fixtures

Provide at least:

1. A valid `run_start` event in `tests/fixtures/runs/sample-run/records.jsonl`.
2. Two valid memory samples with different timestamps, representing synthetic private/RSS/PSS values, one genuine zero-valued metric, and one explicitly unavailable metric with a documented reason.
3. A valid `run-manifest-v1` fixture corresponding to the same `run_id`.
4. An intentionally invalid record illustrating a schema error (such as unavailable value without reason or wrong unit/type).

Fixtures must be clearly marked `synthetic`; **never use real camera/customer identifiers or measurements**. Record/manifest samples must validate with the chosen JSON Schema library. Tests must prove the invalid sample fails.

## 7. Native C/C++ skeleton — opt-in no-op only

The native portion is an **API-integration scaffold**, not a working memory profiler.

### 7.1 Public surface

- `native/include/axis_memlab/probe.h`: pure C-compatible proposed API for metrics and resource lifetime hooks, suitable for inclusion in both C and C++ applications.
- `native/include/axis_memlab/probe.hpp`: minimal C++17 convenience API (for example an explicitly disabled `ResourceGuard` demonstration).
- Names suggested by the companion spec:

```c
void axmem_counter_add(const char *name, uint64_t delta);
void axmem_gauge_set(const char *name, uint64_t value);
void axmem_resource_acquire(uint64_t id, uint32_t kind, uint64_t bytes);
void axmem_resource_release(uint64_t id, uint32_t kind);
void axmem_phase_marker(const char *phase);
int  axmem_emit_snapshot(void);
```

An implementer may introduce a version marker such as `AXMEM_ABI_VERSION`, but must not imply the actual instrumentation ABI is frozen at M0000.

### 7.2 Disabled mode

Provide one explicit compile-time mode, **`AXMEM_DISABLED`**, for examples and compile checks. In that mode all calls must compile and have no observable telemetry, network access, allocations or profiler threads. `axmem_emit_snapshot()` should return an unambiguous disabled/unavailable status; document the return convention.

Outside disabled mode, do **not** silently link no-op functions and claim diagnostics work. Enabled modes `AXMEM_COUNTERS`, `AXMEM_LEDGER`, `AXMEM_SAMPLER` belong to M0003/M0004 and should fail clearly if selected before implementation.

### 7.3 CMake build

- Top-level native target(s) must compile with C11/C++17 without Axis headers or proprietary dependencies.
- Build a deliberately named disabled-only interface or library, such as `axis_memlab_probe_disabled`, plus a pure C and C++ example executable.
- Enable CTest with smoke tests ensuring these executables start/exit successfully and do not produce telemetry.
- Verify C ABI header inclusion from C and C++, and `extern "C"` correctness.
- Document the exact native commands:

```bash
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Debug -DAXMEM_DISABLED=ON
cmake --build build/native --parallel
ctest --test-dir build/native --output-on-failure
```

- Prevent accidentally building enabled profiler modes in this milestone. Don't write fake VDO/Larod integrations: their example subdirectories should contain design notes only.

## 8. Documentation deliverables

**`README.md` must be useful on day one.** Include mission, intended two-surface architecture (camera vs host), status table by milestone, limitations, safety warning, one-minute installation, `--help`/configuration example, Python and native test commands, and links to documentation/specifications. State conspicuously that **no actual camera profiling occurs in scaffold milestone 0000**.

Other required docs:

| Document | Minimum content |
|---|---|
| `CONTRIBUTING.md` | Setup, typing/lint/tests, code organization, naming, PR expectations, examples of safe fixtures |
| `SECURITY.md` | No real camera credentials/customer footage, least privilege, reporting/security contacts **only if provided**, sensitive artifacts policy |
| `docs/00-purpose-safety.md` | Use cases, excluded capabilities, conservative defaults, no automatic camera mutations |
| `docs/01-axis-compatibility.md` | **Unverified** matrix template for firmware, SoC, ACAP SDK, SSH/procfs permissions, VDO/Larod; no guessed support |
| `docs/02-protocol-and-schema.md` | Record classes, timestamps, identities, availability vs zero, schema examples, versioning plan |
| `docs/03-metrics-semantics.md` | RSS/PSS/USS distinctions; anonymous/file/shared; unit conventions; unsupported metrics handled explicitly |
| `docs/06-integrating-cpp-probes.md` | Disabled native build today, proposed hook points for M0003, no unconditional ownership assumptions |
| `docs/08-security-privacy.md` | Redaction, no image/plate capture, run-archive protections, secrets not logged |
| `docs/decisions/0000-bootstrap.md` | Architecture decisions, rationale, unresolved items, license decision if pending |
| `milestones/README.md` | M0000–M0005 order and dependencies; no milestone marked complete until its gates pass |

Other requested `docs/*.md` and `milestones/*.md` files can begin as meaningful outlines with goals, owning milestone, dependencies, and acceptance conditions. For the milestones, adapt the stories and exits from `02_TOOLSET_REPOSITORY_SPEC.md`; do not duplicate them as empty TODOs or mark them implemented.

If companion specifications are available as files during agent execution, place them in `docs/reference/` only if the repository owner wants them tracked; otherwise refer to their existing location in the documentation. Do not silently change the source of truth.

## 9. Test suite specification

### 9.1 Python tests

**CLI (`test_cli.py`):**

- Entry point works from editable installation and `python -m axis_memlab`.
- Top-level help/version succeed.
- Each planned subcommand offers help; invoking actual unsupported work exits `3` and cannot create a run/archive.
- Bad arguments exit `2`; stderr is explanatory, not a Python traceback.

**Configuration (`test_config.py`):**

- All four provided configurations parse and validate.
- Missing file, wrong TOML syntax, wrong numeric type, zero/negative interval, unknown key and unsafe flag are rejected with identified field/error.
- Explicitly ensure no config validation contacts a host or executes a subprocess; monkeypatch/block access if suitable.

**Records (`test_records.py`):**

- Every valid synthetic fixture validates against appropriate Draft 2020-12 JSON Schema.
- Invalid fixture fails with appropriate field path.
- Roundtrip serialization preserves timestamps as integers, zero as zero, unavailable as unavailable and schema version.
- Metric units are coherent (`bytes` means bytes).

**Distribution (`test_distribution.py`):**

- Package can be imported from installed distribution without relying on repository working directory.
- CLI entry point is present in wheel metadata; no incidental dependencies on Axis SDK or private modules.

### 9.2 Native tests

- Build C and C++ examples under Linux using an ordinary host compiler.
- Run CTest smoke tests.
- Disabled build performs no I/O, produces no diagnostic output unless explicitly configured for demonstration, and returns documented disabled status where applicable.
- Requesting an unsupported enabled profiler mode fails clearly instead of linking false-success stubs.

### 9.3 Security/regression tests

- No bundled synthetic JSON contains recognizable credential keys with values, video frame payloads, plate strings or real customer IPs.
- `.gitignore` excludes at least `runs/`, temporary symbols, `core`, `*.core`, `*.dmp`, `.env`, `*.pem`, `*.key`, `build/`, `dist/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`.
- No test requires a live network camera or elevated permissions.
- Avoid brittle heuristics as the sole security tests; review the fixtures and ignore policy in addition to programmatic assertions.

## 10. CI workflow specification

Create GitHub Actions workflows that run on pull requests and commits to the main development branch, with **no repository secrets or external hardware**:

1. **`python-ci.yml`**: set up Python 3.11 and at least one newer stable 3.x, install editable `.[dev]`, run `pytest`, `ruff check`, `ruff format --check`, `mypy` and packaging build. At least Linux is required; smoke-test CLI on macOS/Windows where feasible without substantially increasing maintenance burden.
2. **`native-ci.yml`**: Linux GCC and Clang configurations (or an equivalent practical compiler matrix); CMake configure/build/CTest with disabled profiler mode. Optional Windows/macOS native jobs may be added if they require no proprietary SDK and have reliable support.
3. **`schemas.yml`**: validate that all checked-in JSON schemas are themselves valid Draft 2020-12 schemas; validate good fixtures and reject intentionally bad ones; check TOML examples.

Use bounded timeouts and least-privilege GitHub Actions permissions (`contents: read`). Prefer established maintained action versions; avoid steps fetching arbitrary opaque scripts. CI must not attempt to connect to Axis devices, turn on developer access, collect customer diagnostics, or download vendor SDKs.

## 11. Sequenced implementation stories

### M0000-S01 — Initialize the repo and baseline hygiene

Create package metadata, README, contribution and security policies, editor config, Git ignore rules and licensing decision record. Verify clean git status after ordinary local builds.

### M0000-S02 — Establish typed Python package and CLI shell

Implement `argparse` entry points, help/version, `config check`, explicit not-implemented command handling and stable exit codes. Set up `ruff`, `mypy`, `pytest` and packaging.

### M0000-S03 — Establish configuration model and safety validation

Create all four TOML profiles with shared validation. Reject dangerous flags in scaffold mode. Implement configuration unit tests.

### M0000-S04 — Establish provisional telemetry contracts

Write three baseline JSON schemas; implement basic typed records and serialization, synthetic fixtures, schema tests and metric semantics docs.

### M0000-S05 — Establish native C/C++ disabled probe shell

Implement SDK-free disabled headers, CMake, compile examples and CTest. Ensure enabled modes cannot silently operate as no-ops.

### M0000-S06 — Populate architecture documentation and milestone outlines

Write the foundational docs and create useful M0001–M0005 stubs/acceptance gates, preserving the existing specifications as source material.

### M0000-S07 — Create CI and run full bootstrap verification

Implement the three workflows, test locally, inspect changes for secrets/production data and complete the acceptance checklist below.

## 12. Definition of Done — acceptance checklist

Mark M0000 complete **only when every applicable item passes**:

- [ ] `python -m pip install -e '.[dev]'` succeeds on supported host Python.
- [ ] `axis-memlab --help`, `axis-memlab --version`, `python -m axis_memlab --help` succeed.
- [ ] All planned command groups appear in CLI help; executing unimplemented behavior fails explicitly with exit `3` and doesn't produce false data.
- [ ] `axis-memlab config check --file configs/default.toml` succeeds; unsafe/malformed examples fail.
- [ ] All four TOML profiles parse and pass safety checks.
- [ ] Three JSON schemas validate; valid synthetic fixtures pass and invalid fixture fails.
- [ ] `pytest`, `ruff check`, `ruff format --check`, `mypy`, and Python packaging build succeed.
- [ ] `cmake -S native -B build/native -DAXMEM_DISABLED=ON`, build, and CTest succeed with C and C++ examples.
- [ ] No camera, Axis SDK, root account, privileged Linux feature, external SSH target, frame payload or production telemetry is required for any default test.
- [ ] README truthfully distinguishes scaffolded and unimplemented capabilities.
- [ ] Workflow YAML exists for Python, native and schema checks, with no secrets, device hardware or privileged runtime needed.
- [ ] No real credentials, raw surveillance data or customer-identifying artifacts are committed; `.gitignore` shields local outputs.
- [ ] Licensing is either explicitly determined from existing repository policy or recorded as an open decision, not invented.
- [ ] Planned M0001–M0005 interfaces have documented ownership and no fake successful implementations.
- [ ] Final agent report contains commands run, test outcomes, files created, any deferred item with reason, and recommended first M0001 story.

## 13. Completion response format for the implementing agent

When done, return a concise implementation report under these headings:

```text
1. Branch / commit / PR (only if actually created)
2. Repository structure created
3. Working commands and actual outputs (help, version, config check)
4. Quality-gate results (with command and pass/fail/skipped)
5. Explicitly not implemented yet
6. Decisions and compatibility assumptions
7. Recommended next milestone: 0001 — discovery, protocol refinement, and safe collection
```

Do **not** state that memory leaks have been found, that an Axis camera has been profiled, or that the diagnostic collector is operational as a result of the scaffolding milestone.

---

### Context carried into later milestones

- The toolkit must distinguish application RSS, PSS/USS/private memory, file/shared memory, system memory and kernel/video-buffer growth; these are not equivalent.
- The device may expose only restricted permissions; missing metrics carry explicit reasons rather than zeros.
- Camera-side instrumentation and storage must be bounded; expensive processing belongs on a remote workstation.
- Native lifecycle instrumentation must obey the real Axis VDO/Larod SDK version's ownership contracts, and should not guess release semantics.
- Procfs snapshots **cannot** be fed into Valgrind later to reconstruct historical allocation stacks; allocation-site tracing, if needed, must occur during execution and be symbolized off-device.
- Versions, process identity (`boot_id` + PID + start ticks when available), phases and reproducibility information are essential to sound longitudinal analysis.
