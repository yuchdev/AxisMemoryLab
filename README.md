# Axis Memory Lab

**Nothing in this repository has been run against a real AXIS camera.** Host
collection (milestone 0001), offline analysis (0002), and an in-application probe
(0003) are implemented and tested on synthetic data and fixtures only. Running them
against a device needs the external requirements listed below and an explicitly
authorized device. No Axis SDK, root account, or surveillance material is needed.

Axis Memory Lab is intended to help investigate memory behavior in applications
running under AXIS OS. It has two deliberately separate surfaces: an optional,
low-impact native probe in an application, and a host-side Python CLI for safe
collection and offline analysis. Neither has been run on a camera yet.

## Status

| Milestone | Scope                                                     | Status                      |
|-----------|-----------------------------------------------------------|-----------------------------|
| 0000      | Safe scaffold, schemas, CLI contract, disabled native API | Scaffolded; gates must pass |
| 0001      | Discovery, protocol refinement, safe collection           | Implemented; fixture only   |
| 0002      | Trend analysis and reports                                | Implemented; synthetic only |
| 0003      | In-application profiling                                  | Implemented; host-tested    |
| 0004      | Allocation samples and symbolization                      | Implemented; host-tested    |
| 0005      | Advanced AXIS diagnostics                                 | Planned                     |

See the [roadmap](docs/roadmap/README.md), the [tech-notes coverage matrix](docs/roadmap/tech-notes-coverage.md),
[purpose and safety](docs/00-purpose-safety.md), and the
[bootstrap decisions](docs/decisions/0000-bootstrap.md).

## Install and try

Python 3.11+ is required. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
axis-memlab --help
axis-memlab --version
axis-memlab config check --file configs/default.toml
```

Commands: `config check`, `discover`, `collect`, `annotate`, `snapshot`, `import`,
`purge` (milestone 0001), and `analyze`, `compare`, `report` (milestone 0002).
`symbolize` is planned and exits with status 3. Everything that touches a device is
read-only and opt-in; the runbook is in [collecting on AXIS](docs/05-collecting-on-axis.md),
and a no-device walk-through is in [examples/demo-run](examples/demo-run/README.md).

The `lightweight` profile samples less often and caps snapshots/buffers at half
the default profile's byte limit. `inapp-only` selects future application-owned
counters and does not require SSH. `stress-lab` uses shorter intervals and
larger bounded limits but does not enable intrusive operations.

## External requirements

What must exist outside this repository before each part can be used. Nothing below is
installed or configured by the package itself.

**Always (host CLI, analysis, reports, offline demo)**

| Requirement | Detail |
| --- | --- |
| Python | 3.11 or newer; no runtime dependencies (standard library only) |
| `pip` | To install the package; development extras add `build`, `jsonschema`, `mypy`, `pytest`, `ruff` |
| Operating system | Windows, macOS, or Linux for the host tools |

**Reading a real device over SSH (`discover`, `collect`, `snapshot`)**

| Requirement | Detail |
| --- | --- |
| OpenSSH client | An `ssh` executable on `PATH` (Windows: the optional "OpenSSH Client" feature; checked against OpenSSH 10.2). The tool starts it without a shell and never weakens its options |
| Known host key | The device's host key must already be in your `known_hosts` (or a file given with `--ssh-known-hosts`), verified out of band. Connections to unknown or changed keys are refused, by design |
| Key-based login | A non-interactive key (`--ssh-identity`); password prompts are disabled |
| SSH enabled on the device | SSH is off by default on AXIS OS. From AXIS OS 12 it needs a non-root account with restricted privileges; Developer Mode (AXIS OS 11.11 and later) gives access as an ACAP application's user, with release-specific steps. See the [Axis documentation](https://developer.axis.com/acap/get-started/set-up-developer-environment/set-up-device-advanced/) |
| Readable `/proc` | The account must be able to read the files in the [read-only allowlist](docs/05-collecting-on-axis.md#3-what-is-read). Missing or denied files are reported, not worked around (for example, cross-account `/proc/PID` entries may be unreadable; use the in-app probe then) |
| A device you are allowed to measure | An approved development camera, with a consent or incident reference recorded in the manifest (`--consent-reference`). Do not use production cameras for experiments |
| Device facts | Camera model, SoC, AXIS OS version, application build and ACAP SDK generation, entered by you (`--camera-model`, `--soc`, `--firmware-version`, ...); the tool does not guess them |
| Local disk | Space for the run archive (`records.jsonl` grows with duration; `--compress` and `purge` help). Runs are stored locally only |
| A pseudonym policy | `--device-id` must be a label you chose; serial numbers, MAC and IP addresses are refused |

**Allocation sampling and symbolization (`symbolize`, optional `AXMEM_SAMPLER`)**

| Requirement | Detail |
| --- | --- |
| Nothing extra to read a sample file | `axis-memlab symbolize` is plain Python; it resolves ELF function names with its own reader |
| Unstripped binaries off the camera | Build the profiled application with `-g -fno-omit-frame-pointer` and `-Wl,--build-id`; keep the unstripped binaries and libraries (or separated debug files) on the workstation. Symbols are matched to the device's modules by the build-id inside the file, never by name |
| Optional: `llvm-symbolizer` or `addr2line` (binutils) | Adds source file and line and inlined frames; used only if found on `PATH` |
| Optional: `c++filt` (binutils) | Demangles C++ names; without it names stay mangled and the report says so |
| Development build only | The sampler replaces the global `operator new`; link `axis_memlab_new_hook` into the executable of a development build, never a production one |
| Linux target for stacks and ELF symbols | Frame-pointer unwinding (x86-64, AArch64) and the ELF module table are Linux code paths; on other targets stacks are shallow or unresolved. PE (Windows) binaries are not symbolized |
| Optional workstation replay tools | AddressSanitizer/LeakSanitizer (GCC or Clang), `heaptrack`, Valgrind (Massif, DHAT), for replaying a workload off the camera (`docs/12-allocation-sampling.md`, section 6); none is used by the repository itself |

**In-application probe (`native/`)**

| Requirement | Detail |
| --- | --- |
| CMake | 3.20 or newer |
| C++17 compiler | GCC, Clang, or MSVC (developed with Visual Studio 2022; CI builds GCC and Clang on Linux) |
| Threads library | `pthread` on Linux (found by CMake) |
| Your application's build | The probe is SDK-free. To run inside an ACAP application you build it with your own toolchain and the Axis ACAP Native SDK; this repository neither includes nor requires the SDK |
| Linux target for `/proc` metrics | On other platforms the probe still works, and process-memory metrics are reported as unavailable |

**Not required today:** root access, the Axis SDK, cloud services, any network access other
than SSH to the device, or any online symbol lookup. Later milestones will add optional
tools (symbolizers, sanitizers, heap profilers, `gdbserver`) on a workstation or lab unit;
none is used yet.

## Development checks

```bash
pytest
ruff check .
ruff format --check .
mypy src
python -m build
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Debug -DAXMEM_LEDGER=ON   # or AXMEM_DISABLED / AXMEM_COUNTERS
cmake --build build/native --parallel
ctest --test-dir build/native --output-on-failure
```

With Visual Studio generators add `--config Debug` to the build and `-C Debug` to
`ctest`. The native integration test in `pytest` is skipped when CMake or a C++
compiler is missing.

Schema and TOML fixtures can also be validated with
`python -m jsonschema --instance tests/fixtures/runs/sample-run/manifest.json schemas/run-manifest-v1.schema.json`
when the development dependencies are installed.

## Lab Tools

What is in the repository, how to use it, and how it helps an investigation. The
recommended order of use is in the [investigation workflow](docs/11-investigation-workflow.md).

- **Host collection** (`discover`, `collect`, `annotate`, `snapshot`, `import`, `purge`;
  [runbook](docs/05-collecting-on-axis.md))
  - Reads an allowlisted set of `/proc` and cgroup files over SSH (one connection per
    cycle) or from a saved tree; records what the account cannot read as explicit
    capability states; appends to a local run archive that is never rewritten; stops on
    memory pressure, bounds, or repeated connection failures.
  - *Effect:* a reproducible, low-impact evidence stream with the collector's own cost and
    errors included, and no way to run arbitrary commands on the device.
- **Safety profiles** (`configs/*.toml`, `axis-memlab config check`)
  - Four profiles (`default`, `lightweight`, `inapp-only`, `stress-lab`) validated strictly:
    every risky flag (root, deep snapshots, mutation, ptrace, image or plate capture,
    flash writes) must be off and every privacy flag on.
  - *Effect:* a run plan can be reviewed and rejected before anything touches a device.
- **Run archive and record format** (`schemas/`, `docs/02-protocol-and-schema.md`)
  - One JSON object per line with explicit units, sources, and "unavailable, with reason"
    instead of zero; a manifest records camera, SoC, firmware, SDK, workload, and test case.
  - *Effect:* evidence from different tools and days is comparable and auditable.
- **In-application probe** (`native/`, `docs/06-integrating-cpp-probes.md`)
  - Counters, gauges, and resource lifetimes declared by the application, written as
    records; modes: disabled (default), counters (lock-free), ledger (development, exact
    in-flight bytes and oldest live resources). Needs no SDK, root, or network.
  - Examples: a synthetic pipeline with injectable defects, a bounded-queue pattern, a
    VDO-shaped lifecycle pattern (stand-in types), and a host micro-benchmark.
  - *Effect:* separates "memory held by a queue", "buffers never released", and
    "allocator retention" when `/proc` alone cannot, and works when the SSH account cannot
    read the application's process.
- **Allocation sampler and symbolizer** (`native/` `AXMEM_SAMPLER`, `axis-memlab symbolize`;
  [guide](docs/12-allocation-sampling.md))
  - A replacement for the global C++ `operator new`/`delete` that samples allocations by bytes,
    records size, kind, thread, time and a bounded raw call stack for each sample, remembers
    sampled allocations until they are freed, then performs the standard allocation. Statistical
    weights make the totals unbiased; an exact cumulative counter calibrates them. Nothing is
    symbolized on the device.
  - On the host, `symbolize` maps program counters to functions (and files and lines when a tool
    is available) strictly by build-id, ranks call sites by estimated **live** and **cumulative**
    bytes with sample counts and confidence, and lists every limitation.
  - *Effect:* turns "memory grows" into "these call sites requested the memory that is still
    live", without a heap profiler on the camera.
- **Offline analysis** (`axis-memlab analyze | compare | report`, `docs/07-offline-analysis.md`)
  - Splits a run at restarts and phase markers, computes warm-up-aware robust trends,
    normalizes growth per counter (frames, detections, reconnects), compares controlled
    runs, and lists hypotheses to test with alternatives and the next experiment.
  - Output as JSON, Markdown, escaped HTML, or unit-labelled CSV; limitations always
    listed; never claims a leak from a regression alone.
  - *Effect:* turns raw samples into a ranked list of what to try next.
- **Investigation workflow** (`docs/11-investigation-workflow.md`)
  - Stages from planning to escalation with gates, a workload matrix, per-hypothesis
    experiments with refutation criteria, and a runnable synthetic walk-through.
  - *Effect:* a repeatable procedure instead of ad hoc measurements.
- **Roadmap and coverage** (`docs/roadmap/`)
  - Milestones 0001–0005 and a matrix tracing every tool in the tech notes to its owner.
  - *Effect:* nothing proposed is silently dropped; open items are explicit.
- **Not yet available:** deep captures (`snapshot --level deep` is refused by the safety
  model), any measurement on a real device, differential `smaps` reports (0002), device
  overhead numbers and real VDO/Larod adapters (0003), PE/PDB symbolization and sampling of
  `malloc`/`mmap` (0004), advanced AXIS diagnostics (0005).

## Limitations and safety

The JSON schemas and record types are provisional scaffold contracts; M0001
owns protocol refinement. The native probe writes only to a local size-capped
file chosen by the application; it opens no network connection and starts no
thread. The host collector is read-only, allowlisted, and bounded; it never restarts
the application or captures `deep` data. Allocation samples hold raw code addresses only and are resolved on the host, never on the
device. Nothing
has been measured on a camera. Do not add real credentials, customer identifiers, footage, or
device measurements to fixtures or issues. The defaults disable root access,
mutations, deep snapshots, ptrace, image/plate capture, and camera-flash writes.

## Documentation

- [Compatibility matrix template](docs/01-axis-compatibility.md)
- [Protocol and schemas](docs/02-protocol-and-schema.md)
- [Metric semantics](docs/03-metrics-semantics.md)
- [Collecting on AXIS (runbook)](docs/05-collecting-on-axis.md)
- [Native probe integration](docs/06-integrating-cpp-probes.md)
- [Allocation sampling and symbolization](docs/12-allocation-sampling.md)
- [Overhead measurement](docs/10-benchmarking-overhead.md)
- [Investigation workflow](docs/11-investigation-workflow.md)
- [Security and privacy](docs/08-security-privacy.md)
- [Contribution guide](CONTRIBUTING.md) and [security policy](SECURITY.md)
