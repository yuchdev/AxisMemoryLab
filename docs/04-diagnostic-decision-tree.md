# Diagnostic decision tree (planned)

**Owner:** M0002. **Status:** outline; no conclusions are implemented.

Future analysis should first verify data quality and sample availability,
separate system-wide pressure from process growth, compare controlled phases,
and state alternative explanations and limitations. No threshold in this
scaffold diagnoses a leak.

## Planned hypothesis signatures (M0002)

Signatures are questions to test, not diagnoses. Each needs controlled-phase
comparison before a report may state it.

| Observation | Hypothesis to test | Next comparison |
| --- | --- | --- |
| Private/anonymous and PSS rise with queue sizes | Unbounded application retention | Cap or drain queues |
| App RSS rises while tracked live bytes plateau | Allocator retention or untracked library | Development-only allocator experiment |
| PSS and in-flight buffer/fd counts rise together | Missed release or reference retention | Acquire/release counts versus throughput |
| System use rises while app PSS is flat | Shared, driver, or other-service memory | Identify other processes; vendor-supported inspection |
| Growth per reconnect only | Lifecycle cleanup defect | Repeated start/stop cycles |
| Growth tracks detections, not frames | Result/event accumulation | Disable or cap result publication |
| Plateau after warm-up | Bounded cache or preallocation | Verify bound across workloads and durations |

Rules: do not claim a leak from a linear fit alone; report slopes before and
after warm-up with span, sample count, and min/max; annotate restarts and
configuration changes as run-segment boundaries; falling `MemAvailable` with
flat app PSS does not prove a kernel leak.
