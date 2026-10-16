# Benchmarking overhead (planned)

**Owner:** M0003. **Status:** outline.

Measure instrumentation and collection overhead using synthetic workloads and
document device-specific limits only after compatible hardware is authorized.
No scaffold measurements imply real device cost.

Planned measurements on the smallest authorized device: collector CPU, peak
RSS, network bytes, and pipeline throughput/latency against an uninstrumented
baseline, plus `smaps_rollup` page-table scan cost per read.
