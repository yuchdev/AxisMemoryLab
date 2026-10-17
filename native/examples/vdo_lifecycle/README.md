# VDO lifecycle integration (pattern)

See `../vdo_lifecycle.cpp`, which uses a stand-in stream type. It is not the VDO API and
adds no SDK dependency. A real integration must be verified against the exact free/unref
sequence and buffer-lifetime rules of the application's SDK generation; the hooks must
observe ownership, never change it (`docs/06-integrating-cpp-probes.md`, section 5).
