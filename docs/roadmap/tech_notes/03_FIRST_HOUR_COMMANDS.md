# First-hour field checklist — approved development camera only

This is an **operator's checklist**, not an all-model AXIS OS installation procedure. All commands are read-only; Linux commands may be absent/restricted on individual device/firmware combinations.

## 1. Establish hardware/software identity

Collect exact Axis camera model, SoC, AXIS OS version, FF Group/ACAP package and build ID, SDK version, application executable and PID, total physical RAM. Prefer Axis web UI and the device server report if shell tools do not expose this reliably. Document whether firmware/ACAP app is running with a dynamic user and whether app self-inspection works.

## 2. Discover read-only procfs features

With an authorized **non-root** SSH session, try these individually:

```sh
uname -a
cat /proc/meminfo
cat /proc/vmstat
cat /proc/pressure/memory  # optional
ps                          # optional; locate the target ACAP process
```

Choose the actual numeric application PID shown by `ps` (or a trustworthy application status source). Then:

```sh
PID=1234                     # REPLACE with real process PID
cat /proc/$PID/status        # if permitted
cat /proc/$PID/stat          # if permitted
cat /proc/$PID/smaps_rollup  # optional; may be missing or denied
ls -l /proc/$PID/fd         # optional; potentially permission-limited
```

Some `ps` implementations have different options, and read permissions may differ from ordinary desktop Linux. If another account's procfs entry is denied, use `/proc/self` in the FF Group application rather than trying to bypass Axis access controls.

## 3. Quick ad hoc baseline

If available, record these process fields: `VmRSS`, `RssAnon`, `RssFile`, `RssShmem`, `VmSize`, `Threads` from `/proc/$PID/status`, and `Rss`, `Pss`, `Private_Clean`, `Private_Dirty`, `Anonymous`, `Swap` from `smaps_rollup`. Record `MemTotal`, `MemAvailable`, `MemFree`, `Cached`, `Shmem`, `Slab`, `SReclaimable`, `SUnreclaim` from `/proc/meminfo`.

Store every record with UTC time, device label, process PID, process start ticks, firmware, run phase and video workload. A snapshot taken after a process restart is not comparable to one from the previous process without segmenting.

Do **not** collect a full `/proc/PID/smaps` repeatedly on the camera for a quick test. Do not run Valgrind or a core dump on a production camera.

## 4. First experiment

1. Capture a baseline with FF Group analytics disabled, with any default Axis streams and services held constant.
2. Enable FF Group analytics and observe startup warm-up.
3. Hold a stable video workload; sample process/system at 10–15 s and `smaps_rollup` at 1–5 min if permitted.
4. Disable recognition/inference but keep capture at the same rate; compare slopes.
5. Perform repeated controlled reconnects; annotate each one and check FD/resource counters.
6. Compare `process private/PSS growth` with `device MemAvailable decline` and video throughput.

**Report back with:** model/firmware/SDK, memory at test start and end, duration, frame rate, PSS/private vs RSS, MemAvailable, thread/fd trends, and whether growth occurs with analytics disabled. This is sufficient to choose the correct next probe without guessing.

## 5. Interpretation cheat sheet

- `RssAnon` and private dirty grow together: prioritize C++ heap, queues, object/caches and application-owned mappings.
- `RssShmem` or shared mappings grow; VDO/Larod in-flight buffers/fds increase: prioritize video and inference resource ownership.
- App PSS flat but camera MemAvailable falls: compare other processes, shared buffers, cache and kernel slab before blaming the FF Group heap.
- Everything rises during startup then plateaus: investigate stable high-water memory, not necessarily a leak.
- Only reconnects cause jumps: audit create/destroy paths for streams, tensors, network clients and frame buffers.

## 6. What not to infer

- A larger `VmSize` is not proof of higher physical RAM usage.
- `RSS` is not USS; summing RSS across processes double-counts shared mappings.
- `malloc`-only hooks do not capture all C++/GPU/DMA/video allocations.
- `kmalloc` kernel events are not a catalog of all `malloc` callsites.
- A remotely transferred `smaps` snapshot cannot be reopened in Valgrind to recover allocation history.
- A device-wide memory-utilization percentage cannot determine which process or subsystem is responsible.
