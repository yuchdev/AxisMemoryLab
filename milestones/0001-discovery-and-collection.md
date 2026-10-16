# Milestone 0001 — Discovery and collection

**Owner:** M0001. **Depends on:** M0000. **Status:** planned.

Refine and freeze the record protocol; discover capabilities without assuming
firmware, permissions, or procfs availability; implement bounded, read-only
collection and immutable annotations. Acceptance requires explicit capability
and unavailable states, safe timeouts, synthetic tests, and verified platform
compatibility. Device work must remain opt-in and least-privileged.

## Planned work from the memory-growth playbook

- Extend the run manifest with camera model, SoC, SDK generation, libc, workload
  (resolution, FPS, codec), and a test-case identifier; keep `device_identity`
  pseudonymous.
- Define the `capability` record payload and an event/annotation convention for
  phase markers and run-segment boundaries.
- Add trigger thresholds and a memory-pressure abort setting to configuration.
- Publish a metric-name registry in `docs/03-metrics-semantics.md`.
- Record collector self-timing and read errors.
- Populate `docs/01-axis-compatibility.md` from device evidence only.
