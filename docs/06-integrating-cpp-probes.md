# Integrating C/C++ probes

Today, `native/` is an SDK-free, explicitly disabled compile demonstration only.
It collects no data and makes no telemetry or network calls. Its API is
provisional, not a frozen ABI.

M0003 may propose hooks around application-owned allocation, queue, frame, and
resource lifecycle boundaries. Integration must not assume unconditional
ownership of VDO/Larod objects; the application must decide which lifecycle
hooks are valid. M0004 owns sampled allocation profiling and symbolization.
Follow the disabled build and return convention in `native/README.md`.

## Planned counter design (M0003)

Core counters are generic and application-named (`app.<name>`): acquired and
released totals, in-flight count and bytes, queue depth, bytes and high
watermark, drops, active sessions, reconnects. Counters use relaxed atomics,
are updated on success and error paths, and must not change buffer lifetime,
thread scheduling, or release order; serialization happens off the hot path.
VDO- and Larod-specific counters are integration examples only, written
against the application's own SDK generation. An opt-in lifetime ledger uses
fixed capacity keyed by stable IDs with generation numbers, exports aggregates
and oldest live IDs, and counts `events_dropped` on overflow. Allocator
introspection (`malloc_info`, `mallinfo2`, `malloc_trim`) is glibc-only,
feature-detected, development-only, and `malloc_trim` is an experiment, not a
leak detector.
