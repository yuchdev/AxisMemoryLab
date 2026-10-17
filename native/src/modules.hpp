#ifndef AXIS_MEMLAB_MODULES_HPP
#define AXIS_MEMLAB_MODULES_HPP

// Internal: the loaded-module table that lets a host map a sampled program counter back to a
// binary. Only the file's base name and a build identity are kept (no directories), so the
// sample file does not reveal where software is installed. Symbols never leave the host.

#include <cstddef>
#include <cstdint>

namespace axmem_internal {

constexpr unsigned kMaxModules = 128;

struct ModuleInfo {
  char name[64];
  char build_id[65];       // lower-case hex, empty when the binary has none
  std::uintptr_t base;     // load bias (ELF) or image base (PE); pc - base is the file address
  std::uintptr_t size;     // extent of the mapped image
};

// Fills `out` with up to `max` loaded modules; returns how many. Called at start and at flush,
// never on the allocation path. Not supported on macOS (returns 0).
unsigned collect_modules(ModuleInfo *out, unsigned max);

// Order-independent fingerprint of a table, used to write a `modules` record only on change.
std::uint64_t modules_fingerprint(const ModuleInfo *mods, unsigned n);

}  // namespace axmem_internal

#endif
