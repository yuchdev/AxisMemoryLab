# Axis Memory Lab

**This repository does not yet profile an AXIS camera or collect device data
from the host.** Offline analysis (milestone 0002) and an in-application probe
(milestone 0003) exist and are tested on synthetic data only; host collection
(milestone 0001) is not implemented. No camera, Axis SDK, SSH connection, root
account, or surveillance material is needed or used.

Axis Memory Lab is intended to help investigate memory behavior in applications
running under AXIS OS. It has two deliberately separate surfaces: an optional,
low-impact native probe in an application, and a host-side Python CLI for safe
collection and offline analysis. Neither has been run on a camera yet.

## Status

| Milestone | Scope                                                     | Status                      |
|-----------|-----------------------------------------------------------|-----------------------------|
| 0000      | Safe scaffold, schemas, CLI contract, disabled native API | Scaffolded; gates must pass |
| 0001      | Discovery, protocol refinement, safe collection           | Planned (not implemented)   |
| 0002      | Trend analysis and reports                                | Implemented; synthetic only |
| 0003      | In-application profiling                                  | Implemented; host-tested    |
| 0004      | Allocation samples and symbolization                      | Planned                     |
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

The CLI works on local files only: `config check`, `analyze`, `compare`, and
`report`. Planned commands such as `collect` display their milestone and exit
without doing work.

The `lightweight` profile samples less often and caps snapshots/buffers at half
the default profile's byte limit. `inapp-only` selects future application-owned
counters and does not require SSH. `stress-lab` uses shorter intervals and
larger bounded limits but does not enable intrusive operations.

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
- **Not yet available:** host collection and discovery (0001), differential `smaps`
  reports (0002), device overhead measurements and real VDO/Larod adapters (0003),
  allocation sampling and symbolization (0004), advanced AXIS diagnostics (0005).

## Limitations and safety

The JSON schemas and record types are provisional scaffold contracts; M0001
owns protocol refinement. The native probe writes only to a local size-capped
file chosen by the application; it opens no network connection and starts no
thread. Host collection, device discovery, symbolization, and camera integration
are not implemented, and nothing has been measured on a camera. Do not add real credentials, customer identifiers, footage, or
device measurements to fixtures or issues. The defaults disable root access,
mutations, deep snapshots, ptrace, image/plate capture, and camera-flash writes.

## Documentation

- [Compatibility matrix template](docs/01-axis-compatibility.md)
- [Protocol and schemas](docs/02-protocol-and-schema.md)
- [Metric semantics](docs/03-metrics-semantics.md)
- [Native probe integration](docs/06-integrating-cpp-probes.md)
- [Overhead measurement](docs/10-benchmarking-overhead.md)
- [Investigation workflow](docs/11-investigation-workflow.md)
- [Security and privacy](docs/08-security-privacy.md)
- [Contribution guide](CONTRIBUTING.md) and [security policy](SECURITY.md)
