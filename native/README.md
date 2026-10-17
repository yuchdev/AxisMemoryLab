# Native probe

SDK-free C ABI (`include/axis_memlab/probe.h`) with a C++17 wrapper. Select exactly one
base mode when configuring (no mode is on by default); `AXMEM_SAMPLER` (M0004) may be added to
`COUNTERS` or `LEDGER`, and is refused with `DISABLED` or alone.

Configure from the **repository root**: `native/` is a subdirectory of the root `CMakeLists.txt`
and cannot be configured on its own.

```bash
cmake -S . -B build/native -DAXMEM_DISABLED=ON    # inline no-ops, nothing to link
cmake -S . -B build/native -DAXMEM_COUNTERS=ON    # lock-free counters, snapshots
cmake -S . -B build/native -DAXMEM_LEDGER=ON      # + identity ledger (development)
cmake --build build/native --parallel && ctest --test-dir build/native --output-on-failure
```

With Visual Studio generators add `--config Debug` to the build and `-C Debug` to ctest.

- Library: `src/probe.cpp`, `src/self_proc.cpp` (internal `/proc` parsers).
- Wrappers: `probe.hpp`, `counters.hpp`, `ledger.hpp`.
- Examples: `c_api.c` and `cpp_raii.cpp` (disabled mode); `lifecycle_simulator.cpp`
  (synthetic frame pipeline with injectable defects), `queue_metrics.cpp`,
  `vdo_lifecycle.cpp` (stand-in types, not the VDO API), `overhead_bench.cpp`.
- Tests in `tests/`: each scenario is its own executable because the registry is
  process-global. `reject_*` tests assert that bad mode selections fail at configure time.

Usage and rules: `docs/06-integrating-cpp-probes.md`. The ABI is provisional and not
frozen. Nothing here has run on a camera.

## Allocation sampler (add-on)

```bash
cmake -S . -B build/native -DAXMEM_COUNTERS=ON -DAXMEM_SAMPLER=ON    # or AXMEM_LEDGER=ON
```

Adds `axis_memlab/sampler.h`, the sampler engine (`src/sampler.cpp`, `stack.cpp`, `modules.cpp`),
and the **opt-in** object library `axis_memlab_new_hook` (`src/new_hook.cpp`), which replaces the
global `operator new` / `new[]` / `delete`. Link it into a development executable, together with
`axis_memlab_sampler_flags` (`-g -fno-omit-frame-pointer`). Examples: `sampler_demo.cpp` (known
allocation sites) and `sampler_bench.cpp` (overhead). Guide: `docs/12-allocation-sampling.md`.

## Virtual camera and the root build

`examples/virtual_camera.cpp` builds as `axis_memlab_virtual_camera` in the COUNTERS/LEDGER
modes (linked with the `operator new` hook when the sampler is on). It is a synthetic pipeline
with five injectable defects and is the application used by the Orange Pi 5 guide
(`docs/device-optional/README.md`). The repository root `CMakeLists.txt` enables testing and
includes this directory, so configure and run `ctest` from the root build directory.
