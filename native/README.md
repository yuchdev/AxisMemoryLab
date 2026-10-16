# Native scaffold

This is an SDK-free API integration scaffold, not a profiler. Configure only
with `-DAXMEM_DISABLED=ON`; the C and C++ examples then make no telemetry,
network, allocation, or thread operations. `axmem_emit_snapshot()` returns
`-1` (`AXMEM_STATUS_DISABLED`). Configuring with disabled mode off or selecting
any enabled profiler mode fails clearly. The ABI is provisional and not frozen.

```bash
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=Debug -DAXMEM_DISABLED=ON
cmake --build build/native --parallel
ctest --test-dir build/native --output-on-failure
```
