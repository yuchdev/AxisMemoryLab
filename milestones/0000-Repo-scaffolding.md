# Milestone 0000 — Repo scaffolding

## Goal and status

Create an installable, importable, testable host package, provisional contracts,
synthetic examples, and SDK-free disabled native compile target. This document
does not mark the milestone complete; completion requires every applicable
acceptance gate in the source milestone specification and passing local CI.

## Stories and exit gates

- S01: preserve repository policy; add package metadata and project policies.
- S02: implement CLI help/version/config validation and planned command errors.
- S03: validate conservative TOML profiles and reject unsafe settings.
- S04: add provisional schemas, typed records, and synthetic fixtures.
- S05: compile the C/C++ API only with `AXMEM_DISABLED`; run native smoke tests.
- S06: document safety, metric semantics, decisions, and later milestones.
- S07: exercise Python, packaging, native, schema, and CI gates offline.

Exit requires working local install/help/version/config checks, all tests and
quality tools, disabled native CTest, no sensitive fixture data, and honest
documentation that device profiling is not implemented.
