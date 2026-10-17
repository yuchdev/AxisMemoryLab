# Native probe

SDK-free C ABI (`include/axis_memlab/probe.h`) with a C++17 wrapper. Select exactly one
mode when configuring; no mode is on by default, and the sampler (M0004) is rejected.

```bash
cmake -S native -B build/native -DAXMEM_DISABLED=ON    # inline no-ops, nothing to link
cmake -S native -B build/native -DAXMEM_COUNTERS=ON    # lock-free counters, snapshots
cmake -S native -B build/native -DAXMEM_LEDGER=ON      # + identity ledger (development)
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
