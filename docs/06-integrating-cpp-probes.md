# Integrating C/C++ probes

Today, `native/` is an SDK-free, explicitly disabled compile demonstration only.
It collects no data and makes no telemetry or network calls. Its API is
provisional, not a frozen ABI.

M0003 may propose hooks around application-owned allocation, queue, frame, and
resource lifecycle boundaries. Integration must not assume unconditional
ownership of VDO/Larod objects; the application must decide which lifecycle
hooks are valid. M0004 owns sampled allocation profiling and symbolization.
Follow the disabled build and return convention in `native/README.md`.
