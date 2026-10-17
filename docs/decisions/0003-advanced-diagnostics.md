# Decision 0003: advanced diagnostics, escalation, and deep captures

Date: 2026-10-17. Applies to milestone 0005. Guide: `docs/13-advanced-diagnostics.md`.

## Decisions

**Fail closed, per firmware, on recorded evidence.** An advanced diagnostic is allowed only when a
compatibility evidence record says it was verified available *on that exact firmware*, the unit is
a declared lab unit where the catalog requires it, Developer Mode is recorded where required, and
the safety model does not forbid it. A result must say how it was tested. Anything untested,
verified unavailable, or recorded for another firmware is blocked with the reason. The default for
every diagnostic on every firmware is "blocked"; the repository holds no evidence yet, so today
everything is blocked. Reason: vendor documentation says several facilities (ptrace, debugfs,
perf, BPF) may be unavailable to restricted AXIS OS 12 accounts, and compatibility must never be
inferred from another release.

**The gate is advisory; the toolset runs none of these diagnostics.** It does not enable Developer
Mode, install software, mount filesystems, or attach to processes. It tells the operator whether
the recorded evidence supports using a diagnostic and points at the procedure. This keeps the
repository inside its read-only, least-privilege contract.

**Deep captures stay blocked.** Full `/proc/PID/smaps`, the full fd inventory beyond counts, and
allocator reports remain refused (`allow_deep_snapshot=true` is rejected, `snapshot --level deep`
exits 3, and the gate never allows `deep_smaps` whatever the evidence). Reasons: the output
(mapping names, file paths, socket and fd targets) can identify users, software, and networks; the
read walks page tables and produces large output; and no device has shown it is safe under memory
pressure. Conditions that would have to hold before this decision is revisited:

1. Evidence on the exact firmware that the read is permitted and bounded (time and bytes) under the
   target workload, on a declared lab unit.
2. A refusal under memory pressure implemented in the collector (the sparse path already has one).
3. Mapping names and paths classified and hashed or dropped on capture, with raw values never
   written to the run archive or an evidence bundle.
4. A separate, explicit configuration flag and a test that the default profiles still reject it.
5. The owner's written approval. The M0002-S03 differential reports depend on this and stay open.

**DDH through an operator-written mapping.** Axis lists the DDH utilization topics at alpha
maturity and this repository has not seen a payload. The importer therefore hard-codes no shape:
the operator supplies JSON pointers for the timestamp and each value, units, and a scale, from a
message they captured. Unfitting messages are reported, not guessed. Samples carry the topic and
maturity and are labelled device-wide. A firmware-specific mapping waits for a device.

**Platform findings are hypotheses with the usual caveats.** Shared buffers, DMA-buffer handle
growth, kernel slab growth with a flat process, and cgroup charge versus anonymous memory are
reported when the data supports them. They state what was observed, name alternatives, never say
"leak" or name a kernel owner, and send lab-only follow-ups through the gate. A rule whose input
is absent is not evaluated; absence is not evidence of health.

**Evidence bundles minimise and refuse.** A bundle holds the manifest, analysis, capability and
error records, limitations, and optional evidence, allocation report, plan, reproducer, and a
redacted server report. Raw records are opt-in with the kernel boot id hashed. Every text file is
scanned for addresses, serial numbers, e-mail, credentials, key material, and labelled host names;
if anything remains the build is refused and names the file and the kind, never the text. A
sensitive run needs an explicit review confirmation. `BUNDLE.json` carries SHA-256 for every file
and `--verify` detects later changes. The bundle has no option for a core dump. Contact, transfer,
retention, and approval procedures are owner-supplied and are not invented here.

**The virtual board is not AXIS evidence.** The Orange Pi 5 deployment (`docs/device-optional/`)
exercises the tools on real Linux hardware with a synthetic pipeline. Its verification log must
not be copied into the compatibility matrix.

## Consequences

- M0005 acceptance (documented firmware/SoC/SDK evidence, least privilege, bounded overhead,
  explicit unsupported cases) is **not met**: there is no device evidence. The machinery to record
  and enforce it exists; the evidence does not.
- Everything that needs a real camera is listed in the guide and in the milestone document as a
  TODO and is not implemented.
