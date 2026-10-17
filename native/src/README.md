# Native implementation

Enabled modes (`AXMEM_COUNTERS`, `AXMEM_LEDGER`) are implemented here; disabled mode is
header-only. `probe.cpp` holds the registry, resource kinds, ledger, JSON assembly, and
the public API; `self_proc.cpp` holds pure `/proc` parsers that tests drive with synthetic
text. Lock order is sink, then ledger. `AXMEM_SAMPLER` is owned by milestone 0004 and must
not be added as a no-op.
