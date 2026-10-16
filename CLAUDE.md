# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: milestone 0000 scaffold

This repo is a deliberately inert scaffold for future AXIS OS memory diagnostics. No collection, discovery, analysis, reporting, symbolization, or device I/O exists yet. Most modules under `src/axis_memlab/{analysis,collection,sources,reporting,symbolization,transport}` are empty placeholders for milestones 0001–0005 (see `milestones/`). Only `cli.py`, `config.py`, `records.py`, and `errors.py` contain behavior.

**Do not implement future-milestone behavior as a successful placeholder.** Unimplemented features must fail loudly (e.g. planned CLI commands exit 3; native CMake rejects anything but `AXMEM_DISABLED=ON`). Tests, fixtures, and examples must stay synthetic and offline — no real credentials, customer/camera identifiers, footage, or device measurements.

## Commands

```bash
python -m pip install -e '.[dev]'          # Python 3.11+, runtime deps are empty (stdlib only)
pytest                                      # all tests
pytest tests/unit/test_config.py::test_name # single test
ruff check . && ruff format --check .       # line length 100
mypy src                                    # strict mode
python -m build
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Debug -DAXMEM_DISABLED=ON
cmake --build build/native --parallel && ctest --test-dir build/native --output-on-failure
python -m jsonschema --instance tests/fixtures/runs/sample-run/manifest.json schemas/run-manifest-v1.schema.json
```

CI (`.github/workflows/`) runs the Python checks on 3.11 and 3.13, the native build with gcc and clang, and a schema/config subset of tests (`test_records.py`, `test_config.py`).

## Architecture

Three independent surfaces that meet only through shared contracts:

- **`src/axis_memlab/`** — host-side Python CLI (`axis-memlab`, entry `cli:main`). `cli.build_parser()` builds the command tree without I/O. Only `config check` works; commands in `_PLANNED` map to their owning milestone and return exit code 3. Exit codes: 0 ok, 2 invalid config, 3 planned/not implemented, 4 unreadable file.
- **`native/`** — SDK-free C ABI (`probe.h`) plus C++17 RAII wrapper (`probe.hpp`, `counters.hpp`, `ledger.hpp`), compiled only in disabled mode. The CMake `reject_unimplemented_counters` test is `WILL_FAIL` by design — it asserts that `AXMEM_COUNTERS` etc. are refused.
- **`schemas/`** — provisional JSON Schema Draft 2020-12 wire formats (`record-v1`, `report-v1`, `run-manifest-v1`). `records.py` is the Python mirror of `record-v1`; keep the two in sync. M0001 owns protocol refinement; no stability is promised.

### Config safety model (`config.py`)

`load_config` is a strict, hand-written validator (no schema library at runtime): exact section set (`collection`, `safety`, `analysis`, `privacy`), exact field set per section (unknown *and* missing fields are errors), positive ints, and `transient_buffer_bytes >= max_snapshot_bytes`. The key invariant: **every `[safety]` flag must be `false` and every `[privacy]` flag must be `true`** — enabling root, deep snapshots, mutating commands, ptrace, image/plate capture, or camera-flash writes is rejected. Adding a config field means updating `_ALLOWED`, the validation, all four profiles in `configs/` (`default`, `lightweight`, `inapp-only`, `stress-lab`), and the tests.

### Record conventions (`records.py`)

Timestamps are integer nanoseconds. A `Metric` is either available (value + unit + source) or explicitly unavailable with a reason — **never represent unavailable values with zero**. Use explicit units in metric names. Serialization uses `sort_keys=True` and `allow_nan=False` (non-finite values are rejected).

## Tests

`tests/unit` (cli, config, records), `tests/integration/test_distribution.py`; `tests/performance` and `tests/synthetic-leaks` are placeholders for later milestones. Fixtures live in `tests/fixtures/` (`runs/sample-run`, `corrupt`, `procfs`, `stacks`).

## Docs

`docs/` holds numbered design docs (protocol/schema in `02`, metric semantics in `03`, native integration in `06`); `docs/decisions/` records decisions. PRs should state scope, safety implications, tests run, and schema/compatibility assumptions (`CONTRIBUTING.md`).
