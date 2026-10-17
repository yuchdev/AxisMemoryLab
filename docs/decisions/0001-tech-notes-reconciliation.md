# Decision 0001: reconciling the tech notes with the implementation

Date: 2026-10-17. Applies to milestones 0002 and 0003. Source documents:
`docs/roadmap/tech_notes/`. Item-by-item status is in
`docs/roadmap/tech-notes-coverage.md`.

## Decisions

**Library structure.** The spec proposed `probe.cpp`, `counters.cpp`, `ledger.cpp`,
`proc_self.cpp`, and `emitter.cpp`. The implementation is two translation units:
`probe.cpp` (registry, ledger, JSON, API) and `self_proc.cpp` (pure `/proc` parsers that
are unit-tested on synthetic text). Reason: the pieces share one process-global state and
one lock order (sink, then ledger); splitting them would add headers without isolating
anything. Revisit if the sampler (M0004) makes the file unwieldy.

**No emitter thread; caller-driven snapshots.** The spec describes JSONL generation on a
separate low-priority task. The library starts no threads. The application calls
`axmem_emit_snapshot()` from a timer or control thread it already owns. Reason: thread
creation, priority, and shutdown semantics are the application's decision on a
constrained ACAP, and a library thread would be a new variable in a memory investigation.
Counter and ledger updates never block on I/O either way. An optional helper stays open
in M0003.

**File sink only.** The probe writes a size-capped JSON Lines file and opens no network
connection. Moving the file to the host (SSH copy, outbound TLS) belongs to M0001's
transport. Reason: authentication, TLS, and backpressure are easy to get wrong inside an
instrumentation library, and the file sink fails closed (drops and counts at the cap).

**Ledger uses a mutex; counters do not.** Exact in-flight bytes with duplicate and
unmatched detection need identity, which needs a table. The ledger is a development
mode: one mutex per acquire/release, fixed capacity (default 4096, power of two),
backward-shift deletion (no tombstones), and an explicit `degraded` state on overflow.
`COUNTERS` mode stays lock-free and reports in-flight counts only; bytes are reported as
unavailable rather than zero.

**Build selection.** Exactly one of `AXMEM_DISABLED`, `AXMEM_COUNTERS`, `AXMEM_LEDGER`
must be set; none, several, or `AXMEM_SAMPLER` fails at configure time. The previous
"only disabled mode" rule is replaced because the modes now exist; the rule that no mode
is on by default is kept.

**Name rules.** Probe metrics are `app.[a-z0-9_.]` names (at most 64 characters), so every
snapshot validates against `record-v1` without escaping; a `_bytes` suffix exports bytes,
`_ns` nanoseconds, anything else a count. Process memory uses `process.*`, the probe's own
health uses `app.probe.*`, and the ledger uses `app.resource.<kind>.*` and
`app.ledger.*`.

**Analysis CLI differs from the design contract.** The spec's `analyze --warmup 10m
--compare-phase A:B`, `compare --normalize`, and `report --run` are not implemented as
written. The current commands take warm-up, metrics, and normalizers from the validated
`[analysis]` config section, and `report` renders a saved report JSON. Parity is listed
in the M0002 document.

**Escalation bundle ownership.** The tech notes list a customer escalation bundle under
M2-S05, while `docs/09-customer-escalation.md` assigns escalation to M0005 and says no
workflow is invented before the repository owner supplies approved procedures. The bundle
is owned by M0005; M0002 only produces reports.

**Configuration vocabulary.** The reference profile file and the repository profiles use
different field and profile names (coverage matrix, section 6). The repository profiles
are authoritative and strictly validated; M0001 reconciles the names and adds separate
deep-snapshot caps when a deep path exists.

## Consequences

- Nothing from the three tech notes is unowned; the matrix lists the milestone for each
  open item.
- Real-device overhead, the < 1 MiB counter-only goal, Linux (gcc/clang) builds, and
  SDK-specific adapters remain unverified and are stated as open acceptance items rather
  than claimed.
