#ifndef AXIS_MEMLAB_PROBE_HPP
#define AXIS_MEMLAB_PROBE_HPP

#include "axis_memlab/counters.hpp"
#include "axis_memlab/ledger.hpp"
#include "axis_memlab/probe.h"

namespace axis_memlab {

// Scope-bound acquire/release. It records what the application declares; it does not own,
// extend, or change the lifetime of the resource, and never throws. Use it only where the
// application's own ownership rules make "this scope owns the resource" true; for ownership
// that crosses threads or queues, call ResourceKind::acquire/release at the real boundaries.
class ResourceGuard {
 public:
  ResourceGuard(uint64_t id, uint32_t kind, uint64_t bytes) noexcept : id_(id), kind_(kind) {
    axmem_resource_acquire(id, kind, bytes);
  }
  ~ResourceGuard() { axmem_resource_release(id_, kind_); }
  ResourceGuard(const ResourceGuard &) = delete;
  ResourceGuard &operator=(const ResourceGuard &) = delete;

 private:
  uint64_t id_;
  uint32_t kind_;
};

}  // namespace axis_memlab

#endif
