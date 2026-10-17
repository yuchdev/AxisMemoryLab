# axis-memory-lab — specification pack

This folder contains **proposed engineering specifications**, not a working profiling tool or a created GitHub repository.

1. `0000_REPOSITORY_SCAFFOLDING.md` — agent-ready milestone 0000 instructions: repository structure, CLI and schemas, native disabled build, tests, CI, and acceptance gates.
2. `01_DIAGNOSTIC_PLAYBOOK.md` — complete diagnostic strategy, tools, workload tests, in-app instrumentation, AXIS OS restrictions and references.
3. `02_TOOLSET_REPOSITORY_SPEC.md` — repository architecture, modules, APIs, CLI, metrics schema, test criteria and five staged milestones.
4. `03_FIRST_HOUR_COMMANDS.md` — read-only first-hour checks and the minimum evidence needed from the camera.
5. `configs-default.toml` — representative safe defaults for the **future** collector.

**First test:** identify exact camera model/SoC + AXIS OS and ACAP SDK version; capture system `MemAvailable`, process `RssAnon` and `smaps_rollup` PSS in parallel, then compare no-ACAP / idle-ACAP / video-analysis states.

This pack intentionally distinguishes application resident memory from kernel/driver allocations and off-camera postprocessing from live allocation tracing. It does not assume root privileges or universal access to `smaps_rollup` on AXIS OS.
