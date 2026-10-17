# FF Group CCTV on AXIS OS — Memory-Growth Diagnostic Playbook

**Status:** Proposed investigation and engineering plan  
**Scope:** FF Group CCTV analytics application running as an AXIS Camera Application Platform (ACAP) application on a constrained Axis camera.  
**Primary symptom:** Sustained growth of memory physically consumed while processing video.  
**Assumptions to validate:** Native C/C++ or native-library workload; device model, system-on-chip, AXIS OS release, ACAP SDK generation, memory allocator, and exact FF Group product/version are not yet established.

## 0. Decision summary

1. **Confirm the location of the growth:** application private resident pages, shared/image buffers, other Axis processes, or kernel-side memory. Compare device-wide `/proc/meminfo` with application metrics collected at the same time.
2. **Reproduce under controlled workloads:** a camera baseline without the ACAP, idle ACAP, constant video analysis, busy scene, repeated reconnects, and long-duration steady workload.
3. **Collect the least invasive information first:** `/proc/<pid>/status`, `/proc/meminfo`, `/proc/vmstat`, `/proc/<pid>/fd`, `/proc/<pid>/smaps_rollup` where present; application counters. Ship small records to a separate host.
4. **Find the discriminating trend:** private anonymous RSS, shared pages, mappings/file descriptors, kernel slab, or workload-dependent retained objects.
5. **Add scoped instrumentation:** frame acquisition/release, Larod jobs/tensors, live queues and their byte sizes, native heap and decoder/image buffers, connection/session lifecycle.
6. **Only then escalate:** off-camera sanitizer/heap profiling; development-only remote `gdbserver`; vendor-approved kernel facilities if a kernel/driver allocation problem remains.

### Platform-specific checks that come first

- Obtain exact camera model, SoC (ARTPEC or other), AXIS OS version, ACAP SDK version, application package and dependencies, and whether it is a native or container-based ACAP. **Do not assume all Axis cameras and firmware have identical tooling.**
- Axis documents a VDO memory leak affecting `vdo_buffer_get_data` on ARTPEC chips in firmware starting at **AXIS OS 10.10**, fixed in **10.11.65**. If the build uses this API and a vulnerable firmware version, prioritize a controlled firmware comparison.
- Compare the application's Larod/Tensor API usage to the **exact SDK generation**. Axis's older Larod API and newer Larod 3 API have different buffer-lifetime semantics; do not implement generic free logic from a different SDK generation. Review reference code and API migration notes.
- From AXIS OS 12, device SSH uses non-root accounts; do not design around root or unrestricted `ptrace`, `/sys/kernel/debug`, `perf`, eBPF, `slabinfo`, or cross-process `/proc` access. Developer Mode can enable application-user SSH on supported releases, but it is not a grant of universal kernel privileges.
- On supported AXIS OS 12.11 systems, Device Data Hub documentation includes device CPU and memory utilization topics, but they are version- and capability-dependent; treat these as supplementary system metrics, never a substitute for per-process page accounting.

## 1. Diagnostic model

Linux makes several related but different claims about memory. Record the source and semantics of every reading.

| Metric | Source | Meaning | Limitations |
|---|---|---|---|
| `VmSize` | `/proc/PID/status` | Virtual address space reserved/mapped | Not physical memory usage |
| `VmRSS` / `RssAnon` / `RssFile` / `RssShmem` | `/proc/PID/status` | Process resident pages by high-level category | Shared mappings counted in every mapper; status counters can be approximate |
| `Rss` | `/proc/PID/smaps_rollup` | Resident mapped memory | Includes shared pages; scanning page tables can cost CPU |
| `Pss` | `/proc/PID/smaps_rollup` | Proportional Set Size: shared pages proportionally accounted | Requires access; not universally available |
| `Private_Clean + Private_Dirty` | `/proc/PID/smaps_rollup` | Approximate Unique Set Size (USS) of resident ordinary pages | Consider private hugetlb metrics where applicable; not a universal absolute footprint |
| `Anonymous`, `Swap`, `SwapPss` | `/proc/PID/smaps_rollup` | Anonymous resident and swap usage indicators | Not synonymous with `malloc` allocations |
| `MemAvailable`, `MemFree`, `Cached`, `Shmem`, `SReclaimable`, `SUnreclaim`, `Slab` | `/proc/meminfo` | Device-wide memory accounting | Not attributable to an individual process |
| `nr_slab_unreclaimable`, `pgfault`, `pgmajfault`, reclaim counters | `/proc/vmstat` | Kernel memory/reclaim behavior | Names and availability vary by kernel |
| `some`, `full` | `/proc/pressure/memory` | Pressure Stall Information (PSI), if kernel enables it | Kernel-dependent and not a measure of allocation size |
| Open fd count and target types | `/proc/PID/fd/` | Leaked descriptors, sockets, `anon_inode:dmabuf`, related handles | FD count alone does not give buffer sizes or explain shared ownership |
| Mapping diffs | `/proc/PID/maps`, `/proc/PID/smaps` | Growing memory areas, heap, stacks, anonymous mappings, shared files | Heavy full `smaps`; mapping labels vary |
| Cgroup memory | `/sys/fs/cgroup/...` | Charged container/cgroup memory if used | RSS and cgroup memory measure different things; container support differs |

**Important:** Device-wide `MemAvailable` falling while `Pss` for the app is stable is a real signal, but it does **not** prove a kernel leak. Check camera services, page cache/reclaim, video hardware allocations, and application shared buffers first. Kernel slab values are not a per-process allocation profile.

### Expected diagnostic signatures

| Symptom | Working hypothesis | Next investigation |
|---|---|---|
| App private dirty/anonymous and PSS steadily climb; queue sizes climb | Unbounded application retention | Tag queues and object categories, force queue drain |
| App RSS climbs; tracked live bytes plateau; `malloc_info` arenas expand (on glibc) | Allocator retention/fragmentation or untracked libraries | Controlled trim experiment (development-only); heap profiler off-device |
| PSS climbs, VDO/Larod live buffer/fd count climbs | Missed release/unmap or reference retention | Count acquire/release per API, compare with frame throughput |
| System used grows, app PSS flat; `Shmem` or driver buffers grow | Shared/driver/service memory | Identify service PID(s), DMA fd lifetime; vendor-supported inspection |
| Resident memory grows on every reconnect but stabilizes otherwise | Resource cleanup defect | Repeated start/stop/reconnect cycles and lifecycle counters |
| Growth tied to recognition hits rather than frames | Results/events accumulation | Disable event publication / flush queue / cap cache |
| Steady plateau after warm-up | Bounded cache or preallocation | Verify bound across representative workloads and durations |

## 2. Collection policy

### Level 0 — Device facts and baseline (once per run)

Capture: camera model, SoC, exact AXIS OS version, ACAP package/build ID, binary build IDs, SDK generation, libc/allocator, process executable path, CPU architecture, total RAM, kernel version, available command list, ACAP user, developer-mode status, access limitations, workload/resolution/FPS/codec, duration, test case identifier. Preserve redacted Axis server report separately where authorized.

Determine whether the camera includes `ps`, `top`, `pmap`, `readlink`, `journalctl`, `gdbserver`, `perf`, or relevant `procfs` nodes — **record capabilities; do not require them**.

### Level 1 — Regular samples (default 10–15 seconds)

Collection should work with a simple shell command through SSH or an optional in-process self-monitor. Gather:

- `/proc/meminfo` selected values;
- `/proc/vmstat` selected values and pressure readings when present;
- `/proc/PID/status`, `stat` (process identity/start ticks, CPU, faults), and PID/thread counts;
- application counters: processed frames, detections, queue depth and bytes, in-flight frames/tensors/jobs, active network sessions;
- a concise monotonic timestamp plus UTC wall time, boot ID, process PID and process start time.

Run low-overhead probes as ordinary user **only for processes permitted by the platform**. Prefer in-app self-telemetry if the SSH user cannot read the ACAP's `/proc/PID` files. Use secure transport and store data on a remote host; avoid persistent high-frequency writes to camera flash.

### Level 2 — Sparse snapshots (default 60–300 seconds)

- `/proc/PID/smaps_rollup` for PSS, private/shared categories, anonymous and swap when readable.
- `/proc/PID/maps` and `/proc/PID/fd` inventory with canonicalized paths, **not every interval**.
- Per-service process summaries only where allowed.
- Optional `/proc/self/smaps_rollup` from the instrumented application.
- Optional app-level snapshot of allocator, queues and resource counts.

The collector must measure its own elapsed time and record missing-file/permission errors. If `smaps_rollup` does not exist, use status-based approximation during regular capture and defer expensive full `smaps` to Level 3. Reading full `smaps` repeatedly is specifically **not** an acceptable first-line solution on a constrained camera.

### Level 3 — Triggered snapshot (manual or bounded trigger)

Triggered by app PSS/private growth above a configured threshold, impending low `MemAvailable`, or test-phase boundaries. Attempt:

- `/proc/PID/smaps` **once** (if permitted); full fd inventory and classified fd targets;
- snapshots of application counters, allocator diagnostics when available, library-specific lifetime tables;
- high-level event markers and recent app logs (sanitized);
- system-wide process summary (only accessible PIDs).

A trigger has cooldown, snapshot size limit, strict time budget, and abort threshold if memory pressure is already critical. **Do not trigger heap/core dumps automatically in production.**

### Level 4 — Development-only targeted probes

On a laboratory unit under explicit approval: supported `gdbserver` remote debugging, capped allocation-stack sampler, `strace` on scoped system calls where permitted, `perf`/ftrace/eBPF if actually built/enabled and accessible. These can perturb timing and memory; never claim they work on all AXIS OS releases.

## 3. Controlled test matrix

Keep firmware, ACAP version, configuration, scene, video codec, resolution, frame rate, and network conditions fixed within each paired comparison.

| ID | Mode | Experiment | Primary interpretation |
|---|---|---|---|
| T0 | Baseline | Camera booted, ACAP stopped | Camera/AXIS OS baseline, video services |
| T1 | Idle | ACAP loaded but video processing disabled | Startup and idle/callback/thread behavior |
| T2 | Constant | ACAP processes controlled steady video | Frames/second-linked growth |
| T3 | Active | More plates/objects/detections; same FPS | Recognition-output-driven growth |
| T4 | Reconnect | Repeat camera stream restart or VDO/Larod init/teardown | Lifecycle leak |
| T5 | Recovery | Disable processing and drain queues without process exit | Temporary backlog vs retained allocations |
| T6 | Duration | Long steady test after warm-up | Persistent slope and eventual plateau |
| T7 | Platform comparison | Repeat on compatible alternate firmware/device | Platform-specific regression |

Use a fixture video/replay if the application architecture permits. Preserve sequence numbers or frame IDs; state whether playback has a fixed frequency and drop policy. Run at least two repetitions for any test used to decide regression/root cause. For performance tuning, compare sustained slope after the declared warm-up window, not the transient ramp. Choose test duration based on observed slope and available memory, with a predeclared safe stop condition.

### Interpreting growth

Compute rates per **hour**, per **1,000 frames**, per **1,000 recognitions**, and per **reconnect**. The reporter should print piecewise trends before and after warm-up, robust slope estimate, time span, start/end value, min/max, and number of samples; **not** claim leak solely on a linear regression. Annotate discontinuities after process restarts or configuration changes.

## 4. Application-side probes (C/C++)

### 4.1 Recommended production-safe probes

Provide a small library compiled into the native app (or adapt a library/module if the FF Group application is not entirely native). No sampling thread is strictly necessary: update atomic counters at lifecycle boundaries and collect using an existing periodic event loop or a timer with low duty cycle. Core counters:

- `frames_acquired_total`, `frames_released_total`, `frames_in_flight`, `frames_bytes_in_flight`;
- `vdo_streams_active`, `vdo_buffers_in_flight`;
- `larod_jobs_submitted_total`, `larod_jobs_completed_total`, `larod_tensors_active`, `larod_buffer_bytes_active`;
- queue `name`, `queued_objects`, `queued_bytes`, `dropped_total`, `high_watermark_bytes`;
- recognition request/results counters, metadata cache entries/bytes, active HTTP/TCP sessions, network sends outstanding;
- worker threads, fd count, mmap-region count (optional), allocation failures, reconnects and stage timings;
- process private/PSS from `/proc/self/smaps_rollup` when available; `RssAnon`, `RssFile`, `RssShmem` from `/proc/self/status`.

Integrate counters into all success **and error** paths. For resources acquired through a C API, use scoped wrappers if possible, but verify API-specific ownership rules. Counters must not change buffer lifetime, thread scheduling, or release order.

**Example conceptual contract:**

```cpp
struct PipelineMemoryStats {
    std::uint64_t frames_acquired_total;
    std::uint64_t frames_released_total;
    std::uint64_t frames_in_flight;
    std::uint64_t frame_bytes_in_flight;
    std::uint64_t recognition_results_queued;
    std::uint64_t recognition_results_bytes;
    std::uint64_t larod_jobs_in_flight;
    std::uint64_t larod_tensors_active;
    std::uint64_t reconnects_total;
};
// Serialize snapshots off the hot video-processing path.
```

Counters can use relaxed atomics for approximate telemetry; use stronger synchronization if claiming an invariant across multiple counters. Prefer explicit ownership accounting to global allocation interception as the first probe. A matching pair of total acquire/release counts is necessary but not sufficient to prove no leak because some resources may be mis-sized or ownership transferred.

### 4.2 Internal lifetime ledger (opt-in diagnostic build)

For targeted resource categories, use fixed-capacity maps/ring buffers keyed by a stable resource ID, rather than a general heap enumeration. On acquire: resource category, sequence, size, caller-defined stage; on release: validate ID, latency, decrement count. Export **aggregated totals** and oldest live IDs, not image payloads. Sample large populations to remain bounded; increment a `events_dropped` counter on overflow. Reuse stable identifiers/generation numbers to avoid address-reuse false matches.

### 4.3 Heap and allocator accounting

- With **glibc**, use `malloc_info()` XML (sporadic, development-only) and potentially `mallinfo2()` for allocator diagnostics. **Feature-detect:** an AXIS OS build may use a different libc or allocator. `mallinfo2()` and `malloc_trim()` are not portable.
- A one-time **development-only** `malloc_trim(0)` comparison, only on glibc and when approved, can suggest allocator retention/fragmentation if RSS drops. It is not a leak detector and can perturb the workload.
- For difficult unknown allocations, implement an **opt-in C/C++ allocation sampler** in the development build with limited stack depth and sampling probability (or instrument select call sites). Sampling must cover `malloc`, `calloc`, `realloc`, `free`, C++ new/delete, and `mmap` only to the extent explicitly implemented; **do not claim total coverage**. Avoid recursive tracing, malloc in alloc hooks, and symbolization on the device.
- Use frame pointers or preserved unwind metadata in profiling builds, and retain exact unstripped build-ID-matching binaries/symbols on the workstation.

### 4.4 Stage-by-stage isolation

Make video acquisition, image conversion, inference, recognition result queue, event/network upload, and diagnostic/log pipeline independently switchable in test builds. Each toggle needs a defined bypass behavior and phase marker. Compare acquisition-only to the full pipeline; re-enable stages one at a time. Add controls for queue maximum count, maximum bytes, and a test-triggered drain to distinguish backlog from leaking objects.

### 4.5 Logging and telemetry

Axis ACAP supports syslog-based app logging and `journalctl` where accessible. Use these for low-frequency markers/errors; do not send per-frame diagnostics into persistent camera logs. Prefer direct telemetry to the workstation for frequent counters. Authentication, privacy, redaction, and backpressure are required. No frame, plate, face or credential contents in default diagnostic packets.

## 5. Diagnostic tools: priority matrix

| Tool / technique | Location | Priority | Requires | Value / caveat |
|---|---|---|---|---|
| `/proc/PID/status`, `/proc/meminfo`, `/proc/vmstat` | Camera | Mandatory | Read access | Lowest-friction trends; memory/CPU counters |
| `/proc/PID/smaps_rollup` | Camera | High | Kernel provides; read access | PSS/private resident totals; page-table scan overhead |
| `/proc/PID/smaps`, `/proc/PID/maps` | Camera, occasional | High on trigger | Permissions; performance headroom | Classify growing memory maps |
| `/proc/PID/fd` and `/proc/PID/fdinfo` | Camera | High on trigger | Permissions | fd/socket/dma-buf lifetime hints |
| `/proc/pressure/memory` | Camera | Medium | Kernel PSI enabled | Memory stall and thrashing correlation |
| `/sys/fs/cgroup/*` | Camera/container | Conditional | Valid cgroup | Container charge, events and OOM signals |
| Application instrumented counters | Camera | Mandatory in stage 2 | Source/build access | Ownership, queue and frame retention |
| `ps` / `top` | Camera | Convenience | Installed | Rough cross-process overview; not source of truth |
| Axis app log / `journalctl` | Camera | High | Supported logging access | Lifecycle, crashes, context |
| Axis device server report | Host after export | High once per incident | Authorized UI access | Firmware, logs and environmental context |
| Device Data Hub (where supported) | Camera/host | Optional | Firmware and API support | Supplementary device CPU/memory utilization |
| Custom remote collector (Python) | Host | Mandatory | SSH or app telemetry | Storage, comparison, graphs, alerts |
| `addr2line`, `llvm-symbolizer`, `gdb` | Host | High after trace | Matching debug symbols | Resolve sampled allocation stacks |
| AddressSanitizer / LeakSanitizer | Workstation/lab | High for reproductions | Sanitizer-compatible build/runtime, RAM | Detect memory errors and unreachable allocations; not default on camera |
| `heaptrack`, Valgrind Massif, DHAT | Workstation/lab | Optional | Reproducible workload | Allocation history and heap retention with substantial overhead |
| `gdbserver` | Camera (lab) | Optional | Supported Axis tooling and permission | Targeted debugging, can interrupt operation |
| `strace` | Camera (lab) | Conditional | Installed, ptrace permission | `mmap`, `munmap`, `brk`, fd syscalls; not `malloc` site attribution |
| `perf`/ftrace/eBPF | Camera (vendor-approved lab) | Last resort | Kernel config, capabilities, access | Kernel or allocator pathways; AXIS OS 12 root restrictions may prevent use |
| Slab accounting, DMA-BUF debugfs | Camera (lab) | Conditional | Kernel build/permissions | System-side and video buffer evidence, not generally guaranteed |

**Kernel-side attribution rule:** `kmalloc` and page-allocation tracepoints see allocations within the kernel, including work done on behalf of a userspace process. They **do not identify each userspace `malloc` call or C++ object type**. A PID on a kernel allocation event is not proof of long-term ownership of the allocated pages, especially for device and shared buffers. For userspace heap stacks, instrument the allocator or use supported userspace tracing on a development device.

## 6. How to use off-device memory snapshots correctly

1. **Structured memory snapshots** (procfs counters, `smaps`, fd lists, app ledgers) can be streamed from the device and compared on a powerful workstation. This is the recommended method.
2. **Stack/allocation event samples** are recorded by the target app or profiler and symbolized/aggregated on the workstation. This can identify allocation sites if alloc/free tracking is implemented correctly.
3. **Process core or full memory dumps** can sometimes be analyzed offline with matching `gdb` and debug symbols, but they are intrusive, potentially very large, and might contain private CCTV data. They are not ordinary on-camera telemetry.
4. **Valgrind cannot retroactively profile historical allocation events from `/proc` snapshots or arbitrary memory dumps**. Run Valgrind on a compatible executable and replay workload off-device, or collect appropriate allocation history at runtime.

## 7. Production safety and operational constraints

- No root requirement; no firmware patch, unsigned diagnostic package, privileged shell, kernel module, or debugfs mount as part of the baseline.
- Rate-limit reads; place continuous storage on the host. Bounded sample sizes; no raw video or plate data.
- Fail open if an optional metric is missing: mark it unavailable; do not fabricate zeroes.
- Identify PID by `(boot_id, pid, process_start_ticks)`; PID reuse or ACAP restart creates a new run segment.
- Use monotonic time for slope analysis; keep UTC for coordination.
- Collector outages must not block the camera pipeline. On-device buffer capped; drop telemetry on overflow.
- Record profiling overhead on the smallest supported device: CPU, peak RSS, network bytes, image-processing throughput and latency versus uninstrumented baseline.
- `smaps` and allocator reports may stop/pause other threads or cost CPU; prohibit while a memory-pressure emergency is underway.
- Capture exact version-matched build IDs for binary/library symbolization; separate unstripped symbols should stay off-camera.

## 8. Suggested incident checklist

1. Identify AXIS OS build and SoC; check VDO/Larod release history.
2. Check current severity: time to exhaustion, memory pressure, reboots/OOM and impact on video stream.
3. Run a camera-only baseline, then enable the FF Group ACAP.
4. Capture `/proc/meminfo`, app `/proc/PID/status` every 10–15 s and `smaps_rollup` every 1–5 min (if permitted).
5. Record frame/detection throughput and a controlled idle/active/reconnect test.
6. Compare PSS/private memory, app anonymous RSS, system `MemAvailable`, `Slab`, `Shmem` and process/thread/fd counts.
7. Select one branch: app heap, library/shared video buffers, process/service growth, or kernel/driver suspicion.
8. Add focused counters to the chosen branch, reproduce, generate snapshot delta and symbolized evidence.
9. Validate the fix under the same workload including reconnect and 24h soak if memory budget permits.
10. Attach a redacted report for customer/Axis escalation, with reproducible steps, build IDs and confidence level.

## 9. Supporting references

- AXIS ACAP documentation: https://developer.axis.com/acap/
- Axis VDO known issue and supported APIs: https://developer.axis.com/acap/reference/supported-apis/
- Axis advanced SSH / Developer Mode: https://developer.axis.com/acap/get-started/set-up-developer-environment/set-up-device-advanced/
- Axis application logging: https://developer.axis.com/acap/how-to-guides/application-logging/
- Axis Device Data Hub topic list: https://developer.axis.com/acap/acap-native-sdk-version-12/api/src/api/device-data-hub/html/md_doc_acap_sdk_topic_list.html
- Axis 12.6 Larod modernization: https://www.developer.axis.com/acap/release-notes/12.6/
- Axis Larod memory lifetime API: https://developer.axis.com/acap/acap-sdk-version-3/api/src/api/larod/html/md__opt_builder-doc_larod_doc_api-changes.html
- AXIS OS server report: https://help.axis.com/en-US/axis-os-knowledge-base
- Linux `smaps` reference: https://man7.org/linux/man-pages/man5/proc_pid_smaps.5.html
- Linux pressure: https://docs.kernel.org/accounting/psi.html
- glibc allocator metadata: https://www.man7.org/linux/man-pages/man3/malloc_info.3.html
- glibc trimming: https://man7.org/linux/man-pages/man3/malloc_trim.3.html
