# Axis Memory Lab

**Milestone 0000 is a repository scaffold only. It does not profile an AXIS
camera or collect device data.** No camera, Axis SDK, SSH connection, root
account, or surveillance material is needed or used.

Axis Memory Lab is intended to help investigate memory behavior in applications
running under AXIS OS. Its future design has two deliberately separate surfaces:
an optional, low-impact native probe in an application, and a host-side Python
CLI for safe collection and offline analysis. Neither surface is operational
for device profiling yet.

## Status

| Milestone | Scope | Status |
| --- | --- | --- |
| 0000 | Safe scaffold, schemas, CLI contract, disabled native API | Scaffolded; gates must pass |
| 0001 | Discovery, protocol refinement, safe collection | Planned |
| 0002 | Trend analysis and reports | Planned |
| 0003 | In-application profiling | Planned |
| 0004 | Allocation samples and symbolization | Planned |
| 0005 | Advanced AXIS diagnostics | Planned |

See [milestones](milestones/README.md), [purpose and safety](docs/00-purpose-safety.md),
and the [bootstrap decisions](docs/decisions/0000-bootstrap.md).

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

The CLI only performs host-local configuration checks. Planned commands such as
`collect` display their milestone and exit without doing work.

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
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Debug -DAXMEM_DISABLED=ON
cmake --build build/native --parallel
ctest --test-dir build/native --output-on-failure
```

Schema and TOML fixtures can also be validated with
`python -m jsonschema --instance tests/fixtures/runs/sample-run/manifest.json schemas/run-manifest-v1.schema.json`
when the development dependencies are installed.

## Limitations and safety

The JSON schemas and record types are provisional scaffold contracts; M0001
owns protocol refinement. The C/C++ interface compiles only in explicitly
disabled mode and emits no telemetry. No collection, device discovery,
symbolization, analysis, report generation, or camera integration is
implemented. Do not add real credentials, customer identifiers, footage, or
device measurements to fixtures or issues. The defaults disable root access,
mutations, deep snapshots, ptrace, image/plate capture, and camera-flash writes.

## Documentation

- [Compatibility matrix template](docs/01-axis-compatibility.md)
- [Protocol and schemas](docs/02-protocol-and-schema.md)
- [Metric semantics](docs/03-metrics-semantics.md)
- [Native probe integration](docs/06-integrating-cpp-probes.md)
- [Security and privacy](docs/08-security-privacy.md)
- [Contribution guide](CONTRIBUTING.md) and [security policy](SECURITY.md)
