# Milestone 0005 — AXIS advanced diagnostics

**Owner:** M0005. **Depends on:** M0001–M0004 and verified compatibility. **Status:** planned.

Add only evidence-backed platform diagnostics after compatibility validation.
Acceptance requires documented firmware/SoC/SDK evidence, least privilege,
bounded overhead, and explicit unsupported cases.

## Planned work from the memory-growth playbook

Level 3 and 4 diagnostics (`docs/05-collecting-on-axis.md`) are gated on
verified per-firmware capabilities, including which `ptrace`, `debugfs`,
`perf`, and eBPF facilities AXIS OS 12 actually permits. Device Data Hub topics
are alpha maturity and supplementary only.
