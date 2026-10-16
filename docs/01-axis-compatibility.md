# AXIS compatibility matrix (unverified)

No compatibility has been tested or claimed. M0001 must populate this matrix
from explicit test evidence rather than assumptions.

| Firmware | SoC | ACAP SDK | SSH/procfs access | VDO/Larod | Evidence/status |
| --- | --- | --- | --- | --- | --- |
| Unknown | Unknown | Unknown | Unknown | Unknown | Not tested |

Record exact versions, permission level, test scope, and limitations when
compatibility work is authorized.

## Vendor-documented facts (planning input, not device-tested)

Checked against Axis developer documentation on 2026-10-16. These are vendor
statements, not results from this repository; none changes the matrix above.

- **VDO leak.** Axis lists a memory leak in `vdo_buffer_get_data` on ARTPEC
  chips from AXIS OS 10.10, fixed in 10.11.65
  (<https://developer.axis.com/acap/reference/supported-apis/>). Treat
  firmware in that range as a first suspect when the API is used.
- **Larod 3 buffer lifetime.** In Larod 3.0, `larodDestroyTensors()` also frees
  buffers allocated by larod, and DMA-buffer users must handle cache
  synchronization themselves. Do not reuse free logic across SDK generations
  (api-changes page, ACAP SDK 3 Larod documentation).
- **SSH.** Off by default; from AXIS OS 12 it requires a non-root account with
  restricted privileges. Developer Mode (since AXIS OS 11.11) gives SSH access
  as an ACAP application's user; on 12.11 it needs the
  `axis-unlock-acap-devmode` certificate, and the Developer Mode ACAP
  application has no effect there
  (<https://developer.axis.com/acap/get-started/set-up-developer-environment/set-up-device-advanced/>).
- **Device Data Hub.** Topics `com.axis.device.cpu-utilization.v1` and
  `com.axis.device.memory-utilization.v1` exist in the AXIS OS 12 SDK
  documentation and are marked `alpha` maturity. They are supplementary
  system metrics, not per-process accounting.

Not verified: which `/proc`, `ptrace`, `debugfs`, `perf`, and eBPF facilities
are blocked on a given AXIS OS 12 build. Record these per device as
capabilities rather than assuming them.
