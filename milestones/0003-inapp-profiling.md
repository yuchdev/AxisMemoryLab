# Milestone 0003 — In-app profiling

**Owner:** M0003. **Depends on:** M0000 and M0001. **Status:** planned.

Implement opt-in application counters and lifecycle hooks with measured
overhead and explicit ownership boundaries. Acceptance requires SDK-independent
tests, documented integration constraints, disabled default behavior, and no
unconditional VDO/Larod ownership assumptions.

## Planned work from the memory-growth playbook

Generic `app.<name>` counters and an opt-in lifetime ledger as described in
`docs/06-integrating-cpp-probes.md`; VDO/Larod counters only as examples.
Measure overhead per `docs/10-benchmarking-overhead.md`.
