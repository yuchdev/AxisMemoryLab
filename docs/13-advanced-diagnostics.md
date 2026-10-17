# Advanced diagnostics (Level 3-4)

**Owner:** M0005. **Status:** the gate, the evidence record, the DDH importer, the platform
correlation rules, and the escalation bundle are implemented and tested on synthetic data. **No
advanced diagnostic has been run on a real AXIS device**, so nothing here claims that any of them
works on a given firmware. Everything below is a procedure to follow on an authorized lab unit,
with the owner's approval, after the gate says it is permitted.

Read first: `docs/05-collecting-on-axis.md` (Levels 0-2 and the allowlist),
`docs/08-security-privacy.md`, `docs/11-investigation-workflow.md` (when to escalate), and
`docs/01-axis-compatibility.md` (vendor-documented facts and the evidence matrix).

## 1. How the gate works

Advanced diagnostics are **blocked by default for every firmware**. A diagnostic is permitted only
when a compatibility evidence record (`schemas/compat-evidence-v1.schema.json`) says it was
**verified available on that exact firmware**, and the record's other conditions hold:

```bash
# 1. A normal collection run on the lab unit, with exact device facts:
axis-memlab collect ... --camera-model "<model>" --soc "<soc>" --firmware-version "<AXIS OS>" ...

# 2. Start an evidence record from it (every diagnostic begins as "not_tested"):
axis-memlab advanced evidence --run runs/<id> --authorized-by-reference INC-1234 \
    --lab-unit [--developer-mode] --out evidence.json

# 3. Test one diagnostic by hand using the section below, then edit its entry in evidence.json:
#      "status": "verified_available" | "verified_unavailable",  "method": "what you did and saw"

# 4. Ask the gate before relying on it:
axis-memlab advanced check --evidence evidence.json --diagnostic strace_scoped \
    --for-firmware "<AXIS OS>"                 # exit 0 allowed, 3 blocked, 4 invalid evidence
axis-memlab advanced list                      # the catalog: what each shows and cannot show
```

Rules the gate enforces (`src/axis_memlab/advanced/evidence.py`):

* A diagnostic with no verified result is blocked ("not tested"), as is one verified *unavailable*.
* Evidence is for one firmware; a different `--for-firmware` is blocked. Compatibility is never
  assumed across firmware, SoC, or SDK.
* Where the catalog says so, the unit must be a **declared lab unit** (`device.lab_unit`), and
  Developer Mode must be recorded for `gdbserver`.
* Any result other than `not_tested` must say **how it was tested** (`method`); a bare claim is
  rejected.
* `deep_smaps` is never allowed, whatever the evidence says (section 10).
* `authorized_by_reference` is an approved incident or consent identifier, not a name or contact.
* The gate is advisory: the toolset never runs these diagnostics. Evidence older than a year is
  flagged, not trusted silently.

## 2. `ddh_topics`: Device Data Hub utilization topics

* **What:** device-wide CPU and memory utilization from topics Axis lists for AXIS OS 12 (for
  example `com.axis.device.memory-utilization.v1`). **Alpha maturity**; not per-process.
* **Why it helps:** an independent device-level series next to `/proc/meminfo`, useful to confirm
  that the platform sees the same trend.
* **Tool support:** `axis-memlab advanced import-ddh` imports *captured* messages through a mapping
  file you write from a real message (`src/axis_memlab/sources/ddh.py` documents the format). No
  payload shape is assumed. A message that does not fit is reported, not guessed. Imported samples
  are `system.ddh.*` with the topic and maturity as provenance.
* **Procedure:** subscribe with a client allowed on your firmware (an ACAP application or a
  supported MQTT/API path; see the Axis documentation, which this repository does not duplicate),
  save messages as JSON Lines, write the mapping, import, and compare in `analyze`.
* **Unsupported until verified:** which firmware exposes the topics, the payload shape, the update
  rate, and whether memory utilization includes cache are unknown. **TODO (needs a device):** a
  firmware-specific mapping and an evidence entry.

## 3. `server_report`: the Axis device server report

* **What:** an operator-exported report with firmware, configuration, logs, and environment.
* **Use:** context for a vendor escalation. It is not a measurement.
* **Handling:** it contains identifying data (addresses, serial numbers, configuration). Export it
  yourself from the device's web interface or the supported procedure in the Axis knowledge base;
  the toolset never fetches it. If it is an archive, extract the text files you intend to share.
  `axis-memlab bundle --server-report FILE --redact-server-report` redacts addresses, serial
  numbers, e-mail, credentials, host labels, and key material, and **refuses** to build the bundle
  if anything identifying remains. Redaction is best-effort: read the result.

## 4. `strace_scoped`: scoped strace

* **What:** system calls for memory mapping and descriptors (`mmap`, `munmap`, `mremap`, `brk`,
  `openat`, `close`, `dup*`) of one process.
* **Shows:** when mappings and descriptors are created and released, and sizes of mappings.
  **Cannot show:** the `malloc` call site (use the sampler, `docs/12`), kernel allocations, or
  anything outside the trace filter.
* **Risks:** ptrace slows the target heavily and changes timing; it needs `ptrace` permission,
  which restricted AXIS OS 12 accounts are expected not to have. Never on a production unit.
* **Procedure (lab unit, after the gate allows it):** attach to the PID of the application for a
  short bounded window with a syscall filter, for example
  `strace -f -p <pid> -e trace=mmap,munmap,mremap,brk -tt -o /tmp/trace.txt` for 30-60 seconds
  under the T2 workload; stop it; copy the file off the device; delete it on the device. Record
  success or the exact error in the evidence entry.

## 5. `gdbserver`: remote debugging

* **What:** an interactive session from a workstation that has the matching unstripped binaries.
* **Prerequisite:** Developer Mode as described by Axis for the firmware. SSH access in Developer
  Mode is as the ACAP application's user; on some releases it needs a certificate step (see
  `docs/01-axis-compatibility.md`). **This toolset never enables Developer Mode, installs
  anything, or toggles settings.** Do it manually, with approval.
* **Risks:** it stops the process and disturbs the video pipeline. Use it for inspecting a
  stopped process (object counts, queue contents) on a lab unit, not for measuring behaviour.
* **Procedure:** start `gdbserver` attached to the application as the owner documents, connect
  from the workstation, load symbols from the off-device unstripped build (build-id must match,
  `docs/12-allocation-sampling.md` section 4), inspect, detach cleanly.

## 6. `perf_stat`, `perf_record`: perf

* **What:** hardware and software event counting (`perf stat`) or sampling (`perf record`).
* **Shows:** page-fault and context-switch rates, where CPU time goes, and with call graphs where
  faults occur. **Cannot show:** allocation ownership; kernel symbols may be missing.
* **Prerequisite:** the binary exists on the device, `perf_event_paranoid` allows it for your
  account, and the kernel exposes the events. Any of these may be false on AXIS OS 12.
* **Procedure (lab unit):** `perf stat -e page-faults,minor-faults,major-faults -p <pid> -- sleep 30`
  first (counting is cheap); only then, if verified, a short `perf record -p <pid> -g -- sleep 20`.
  Keep the data file off the camera's flash.

## 7. `ftrace`, `ebpf`: kernel tracing

* **What:** kernel tracepoints for allocation and page events (`kmem`, `mm`), or programmable
  probes where the kernel has BPF.
* **Rule that must not be forgotten:** `kmalloc` and page-allocation events happen *in the kernel*,
  including work done on behalf of a userspace process. They do **not** identify userspace `malloc`
  sites or C++ object types, and a PID on such an event is **not** proof that the process owns the
  pages long-term, especially for device and shared buffers. For userspace heap stacks use the
  sampler, not kernel tracing.
* **Prerequisite:** `tracefs` mounted, privilege, and (for eBPF) a kernel with BPF and a toolchain.
  Restricted AXIS OS 12 accounts are expected not to qualify; a vendor-approved lab image may.
* **Procedure:** only on a vendor-approved lab image, following the vendor's guide, for a short
  window with filters on the one PID. Record in the evidence entry what was and was not possible.

## 8. `slabinfo`, `dmabuf_debugfs`: kernel-side accounting (lab)

* **`slabinfo`:** `/proc/slabinfo` lists kernel cache sizes. Usually root-only. Tells you *which
  kernel cache* grows, never which userspace code caused it. Pairs with the `H-KERNEL-SLAB`
  hypothesis (`system.mem.slab_unreclaim_bytes` rising while the process is flat).
* **`dmabuf_debugfs`:** where `debugfs` exposes DMA-BUF accounting (for example under
  `/sys/kernel/debug/dma_buf/`), it lists exported buffers, sizes, and holders. Requires `debugfs`
  mounted (a device change) and privilege. Pairs with `H-SHARED-BUFFERS` and `H-DMABUF-HANDLES`.
  Buffers that are not exported through dma-buf do not appear.
* Both are read-only once available, but they walk kernel structures and need privilege that
  restricted accounts do not have. Do not change mounts or permissions on a production unit.

## 9. `core_dump`: process core or full memory dumps

* A core file is a frozen copy of process memory. It is large, slow to take, and likely to contain
  private CCTV data, credentials, TLS key material, and plate text. **It is not ordinary
  telemetry**, must never be attached to a bundle by this toolset (the bundle has no option for
  it), and needs the owner's explicit approval, local-only handling, and secure deletion.
* It cannot recover allocation history. **Valgrind cannot reconstruct heap history from a core
  file, from `/proc` snapshots, or from `smaps` output**; history must be recorded while the
  program runs (the sampler, or a replay under a heap profiler on a workstation).
* If a core is truly needed for a crash, analyse it on a workstation with the matching unstripped
  build and `gdb`, and treat the file as sensitive.

## 10. `deep_smaps`: deep captures remain blocked

Full `/proc/PID/smaps`, the full fd inventory beyond counts, and allocator reports are **not**
available: `allow_deep_snapshot=true` is rejected by the configuration and `snapshot --level deep`
exits 3. The review is recorded in `docs/decisions/0003-advanced-diagnostics.md`: the gate refuses
it whatever the evidence says, because the data it would produce (mapping names and paths) can
identify users and software, and because no device has shown that the read is safe under memory
pressure. What would have to be true to enable it later is listed there.

## 11. What the platform rules add to `analyze`

When the collected data contains the relevant series (`docs/03-metrics-semantics.md`), `analyze`
evaluates, per segment and after warm-up, with the usual caveats:

| Rule               | Needs                                                                                        | Says                                                                                | Does not say                                               |
|--------------------|----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|------------------------------------------------------------|
| `H-SHARED-BUFFERS` | `system.mem.shmem_bytes` and (`process.rss_shmem_bytes` or `process.fd_dmabuf_count`) rising | Shared/video-buffer memory is rising with the process's shared pages or DMA handles | Who owns the buffers, or that they leak                    |
| `H-DMABUF-HANDLES` | `process.fd_dmabuf_count` rising, anonymous memory not                                       | The number of open DMA-buffer descriptors is rising                                 | That the handles are never closed                          |
| `H-KERNEL-SLAB`    | `system.mem.slab_unreclaim_bytes` rising, process known flat                                 | Kernel slab is rising while the process is not; allocator and owner unconfirmed     | A kernel leak                                              |
| `H-CGROUP-CHARGE`  | `process.cgroup_memory_current_bytes` rising, anonymous memory known flat                    | The cgroup charge rises without process anonymous growth                            | What is charged (page cache, other members, kernel memory) |

A rule whose inputs are absent or unreadable is simply not evaluated; absence is not evidence of
health. Each finding names the next comparison, and lab-only diagnostics are referred to the gate.

## 12. Unsupported and unverified, in one list

* Which of `ptrace`, `perf_event`, `tracefs`, `debugfs`, BPF, and root-only files are reachable on any
  AXIS OS 12 build. **Unknown; each is a per-firmware evidence entry.**
* The DDH payload shapes and update rates.
* Whether the server report can be obtained in a text form without manual extraction.
* Everything in this guide on a real camera. See `docs/device-optional/README.md` for the virtual
  board that exercises the *tools* (not AXIS-specific behaviour) and for the TODO list that needs
  a camera.
