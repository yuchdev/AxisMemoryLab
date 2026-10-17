# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: milestones 0001-0005 implemented against fixtures; nothing run on a real device

This repo is a set of AXIS OS memory-diagnostic tools that has only been exercised on synthetic data. Host collection over a read-only allowlist (M0001), offline analysis and reporting (M0002), the in-app probe (M0003, file output only), the allocation sampler with offline symbolization (M0004), and the evidence-gated advanced-diagnostics toolkit (M0005: gate, evidence record, DDH import, platform rules, evidence bundle) exist; no code has run against a real device, so every advanced diagnostic is blocked until evidence is recorded. `docs/roadmap/tech-notes-coverage.md` maps every item of the tech notes to its owner.

**Do not implement future-milestone behavior as a successful placeholder.** Unimplemented features must fail loudly (e.g. planned CLI commands exit 3; native CMake rejects zero or multiple base modes and `AXMEM_SAMPLER` without COUNTERS/LEDGER). Tests, fixtures, and examples must stay synthetic and offline — no real credentials, customer/camera identifiers, footage, or device measurements.

## Commands

```bash
python -m pip install -e '.[dev]'          # Python 3.11+, runtime deps are empty (stdlib only)
pytest                                      # all tests
pytest tests/unit/test_config.py::test_name # single test
ruff check . && ruff format --check .       # line length 100
mypy src                                    # strict mode
python -m build
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Debug -DAXMEM_LEDGER=ON   # from the REPO ROOT; or AXMEM_DISABLED / AXMEM_COUNTERS (+ AXMEM_SAMPLER)
cmake --build build/native --parallel && ctest --test-dir build/native --output-on-failure   # VS generators: add --config Debug / -C Debug
python -m jsonschema --instance tests/fixtures/runs/sample-run/manifest.json schemas/run-manifest-v1.schema.json
```

CI (`.github/workflows/`) runs the Python checks on 3.11 and 3.13, the native build with gcc and clang, and a schema/config subset of tests (`test_records.py`, `test_config.py`). `tests/integration/test_native_probe.py` (marker `native`) builds the ledger mode with CMake and is skipped when CMake or a C++ compiler is missing.

## Architecture

Three independent surfaces that meet only through shared contracts:

- **`src/axis_memlab/`** — host-side Python CLI (`axis-memlab`, entry `cli:main`). `cli.build_parser()` builds the command tree without I/O. `config check`, `discover`, `collect`, `annotate`, `snapshot`, `import`, `purge` (`cli_device.py`), `symbolize` (`cli_symbolize.py`), `advanced` and `bundle` (`cli_advanced.py`) and `analyze`, `compare`, `report` work; commands in `_PLANNED` (now empty) would return exit code 3, as does `snapshot --level deep`. Exit codes: 0 ok, 2 invalid config/arguments/request (also a refused bundle), 3 planned or refused (also `advanced check` finding a blocked diagnostic), 4 unreadable or invalid file/run/report, 5 transport failure, 6 run ended early but safely.
- **`native/`** — SDK-free C ABI (`probe.h`, ABI v2) plus C++17 wrappers (`probe.hpp`, `counters.hpp`, `ledger.hpp`). Exactly one of `AXMEM_DISABLED` / `AXMEM_COUNTERS` / `AXMEM_LEDGER` must be set; none, several, `AXMEM_SAMPLER` alone, or `AXMEM_SAMPLER` with `DISABLED` is refused at configure time by the `WILL_FAIL` `reject_*` tests. `AXMEM_SAMPLER=ON` (an add-on to COUNTERS/LEDGER) adds `sampler.h`, the sampler engine, and the opt-in `axis_memlab_new_hook` object library that replaces global `operator new/delete`. Enabled modes write `record-v1` JSON Lines from caller-driven snapshots (no threads, no network). Details in `docs/06` and `docs/decisions/0001-tech-notes-reconciliation.md`.
- **`schemas/`** — provisional JSON Schema Draft 2020-12 wire formats (`record-v1`, `report-v1`, `run-manifest-v1`). `records.py` is the Python mirror of `record-v1`; keep the two in sync. M0001 owns protocol refinement; no stability is promised.

### Config safety model (`config.py`)

`load_config` is a strict, hand-written validator (no schema library at runtime): exact section set (`collection`, `safety`, `analysis`, `privacy`), exact field set per section (unknown *and* missing fields are errors), positive ints, and `transient_buffer_bytes >= max_snapshot_bytes`. The key invariant: **every `[safety]` flag must be `false` and every `[privacy]` flag must be `true`** — enabling root, deep snapshots, mutating commands, ptrace, image/plate capture, or camera-flash writes is rejected. Adding a config field means updating `_ALLOWED`, the validation, all four profiles in `configs/` (`default`, `lightweight`, `inapp-only`, `stress-lab`), and the tests.

### Record conventions (`records.py`)

Timestamps are integer nanoseconds. A `Metric` is either available (value + unit + source) or explicitly unavailable with a reason — **never represent unavailable values with zero**. Use explicit units in metric names. Serialization uses `sort_keys=True` and `allow_nan=False` (non-finite values are rejected).

### Collection (`transport/`, `sources/`, `collection/`)

Everything a collector may read is the allowlist in `transport/__init__.py` (`is_allowed_file`); both readers enforce it, and `SshReader` only ever sends fixed `cat` / `ls -l` / one read-loop template with allowlisted paths, using the system `ssh` without a shell and with `StrictHostKeyChecking=yes`. **Do not add a path, a command, or a weaker SSH option casually**: `cmdline`, `environ`, `maps`, `smaps`, and logs are deliberately excluded, and `deep` snapshots are blocked by the config safety model. Parsers in `sources/` are pure (text in, `Metric` dict out); unreadable data is `unavailable(code, detail)` with a closed reason code, never zero, and a test keeps `docs/03-metrics-semantics.md` complete. `RunStore` is append-only (one `write` per line, atomic manifest, only `status` changes); `Collector` takes an injected clock so tests never sleep. `--no-wait` is only for offline `--procfs-root` demos. Fixtures: `tests/fixtures/procfs/basic` (fd data via `fd.ls`).

### Advanced diagnostics, bundle, virtual board (`advanced/`, `bundle/`, `sources/ddh.py`, `docs/device-optional/`)

The gate in `advanced/evidence.py` **fails closed**: a diagnostic is allowed only with a recorded `verified_available` result *with a stated method*, for the *exact* firmware, on a declared lab unit where the catalog says so; `deep_smaps` is never allowed (decision 0003). The toolset never runs these diagnostics, enables Developer Mode, or changes a device; keep it that way. `advanced/catalog.py` is the single list that the CLI, the gate, and `docs/13` are checked against (a test fails if a catalog entry is undocumented). DDH import hard-codes no payload shape (operator mapping file). Bundles (`bundle/build.py`) must stay minimal: scan every text file with `bundle/redact.py` and **refuse** (naming file and kind, never the text) rather than write identifying content; no core dumps; sensitive runs need `--reviewed`. Platform rules live in `analysis/classify.py` and are hypotheses, not diagnoses. The Orange Pi 5 scripts under `docs/device-optional/opi5/` must stay POSIX `sh` with LF endings (`.gitattributes`), key-only SSH, loopback-only forwarding, no passwords, and a working `--dry-run`; `tests/unit/test_opi5_scripts.py` checks this. The virtual board is **not** AXIS evidence. Never put a phase marker at every reconnect (it splits the analysis).

### Allocation sampler (`native/src/sampler*.cpp`, `new_hook.cpp`, `stack.cpp`, `modules.cpp`; `symbolization/`)

Rules that must keep holding: **no heap allocation, stdio, locks beyond the short ring mutex, or symbolization on the allocation path**; samples are queued in a fixed ring and written only by `axmem_sampler_flush()`; the hook records the stack *before* the standard allocation and attaches the pointer only if it succeeded; `sampler_free` runs *before* the memory is released; tracked samples equal recorded samples; every limit is counted (`dropped_*`), never silent. The unwinder only reads frame records inside the thread's stack bounds. On the host, frames resolve **only** against a symbol file whose build-id equals the module's (by content, not name); mismatches are reported, unresolved frames are never guessed, and **live and cumulative estimates must never be relabelled as each other**. Tools are run without a shell. Fixtures: `tests/elf_builder.py` (synthetic ELF) and `tests/sample_files.py`.

### Analysis (`analysis/`, `reporting/`)

Reads local run archives only (`load.py` is tolerant and reports defects as limitations). `phase.py` segments; `trend.py` does Theil-Sen windows; `classify.py` emits hypotheses, never diagnoses. **Report wording must not claim a leak or cause**; tests assert this. Segment/phase events are a provisional convention until M0001.

## Tests

`tests/synthetic_traces.py` generates deterministic synthetic run archives. `tests/unit` (cli, config, records, analysis, reporting, sources, transport, collection), `tests/integration/test_cli_device.py` (CLI end to end, including a fake `ssh`), `tests/integration/test_native_sampler.py` (builds COUNTERS+SAMPLER, runs the demo, checks estimates against known allocations; ELF symbol resolution runs on Linux only), `tests/integration/test_virtual_camera.py` (injected defects seen through probe, ledger, sampler, analysis), `tests/integration/test_live_procfs.py` (Linux only: the collector against the real `/proc`), `tests/integration/test_distribution.py`; `tests/performance` and `tests/synthetic-leaks` are placeholders for later milestones. Fixtures live in `tests/fixtures/` (`runs/sample-run`, `corrupt`, `procfs`, `stacks`).

## Docs

`docs/` holds numbered design docs (protocol/schema in `02`, metric semantics in `03`, native integration in `06`); `docs/decisions/` records decisions. PRs should state scope, safety implications, tests run, and schema/compatibility assumptions (`CONTRIBUTING.md`).
