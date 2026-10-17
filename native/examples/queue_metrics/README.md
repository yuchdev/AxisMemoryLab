# Queue metrics integration (pattern)

See `../queue_metrics.cpp`: a bounded queue that publishes depth, bytes, high-watermark,
and drops at its own push/pop boundaries. Application-agnostic; no camera-specific code.
