# Diagnostic decision tree (planned)

**Owner:** M0002. **Status:** implemented in `analysis/classify.py` as observation
patterns; synthetic validation only.

Future analysis should first verify data quality and sample availability,
separate system-wide pressure from process growth, compare controlled phases,
and state alternative explanations and limitations. No threshold in this
scaffold diagnoses a leak.

## Planned hypothesis signatures (M0002)

Signatures are questions to test, not diagnoses. Each needs controlled-phase
comparison before a report may state it.

| Observation                                      | Hypothesis to test                       | Next comparison                                       |
|--------------------------------------------------|------------------------------------------|-------------------------------------------------------|
| Private/anonymous and PSS rise with queue sizes  | Unbounded application retention          | Cap or drain queues                                   |
| App RSS rises while tracked live bytes plateau   | Allocator retention or untracked library | Development-only allocator experiment                 |
| PSS and in-flight buffer/fd counts rise together | Missed release or reference retention    | Acquire/release counts versus throughput              |
| System use rises while app PSS is flat           | Shared, driver, or other-service memory  | Identify other processes; vendor-supported inspection |
| Growth per reconnect only                        | Lifecycle cleanup defect                 | Repeated start/stop cycles                            |
| Growth tracks detections, not frames             | Result/event accumulation                | Disable or cap result publication                     |
| Plateau after warm-up                            | Bounded cache or preallocation           | Verify bound across workloads and durations           |

Rules: do not claim a leak from a linear fit alone; report slopes before and
after warm-up with span, sample count, and min/max; annotate restarts and
configuration changes as run-segment boundaries; falling `MemAvailable` with
flat app PSS does not prove a kernel leak.

## Implemented rules (M0002)

Evaluated per segment on the post-warm-up window only; a window with too few samples
yields no statement. A finding says what was observed, lists alternatives, and names
the next controlled comparison.

| ID                           | Pattern required                                                                                          | Not concluded                         |
|------------------------------|-----------------------------------------------------------------------------------------------------------|---------------------------------------|
| `H-RETENTION`                | PSS or anonymous RSS rising and an `app.*queue*` metric rising                                            | Cause of the queue growth             |
| `H-MISSED-RELEASE`           | PSS or anonymous RSS rising and an `app.*in_flight*` metric rising                                        | That a release call is missing        |
| `H-ALLOCATOR`                | Anonymous RSS rising while `app.*live_bytes*` or ledger `app.resource.*.in_flight_bytes` metrics are flat | Fragmentation vs untracked allocation |
| `H-UNATTRIBUTED`             | Process growth and none of the above                                                                      | Anything about cause                  |
| `H-NOT-IN-PROCESS`           | `MemAvailable` falling, PSS flat                                                                          | A kernel leak                         |
| `H-PLATEAU`                  | Rising during warm-up, flat after                                                                         | That the bound holds longer           |
| `H-RECONNECT`, `H-DETECTION` | Not evaluated: need cycle/counter data                                                                    | n/a                                   |

"Rising/falling" means the Theil-Sen rise over the window exceeds 3 robust sigma of
the residuals plus 2% of the median; otherwise "flat". These thresholds are untuned
and should be revisited against real-device data.
