#ifndef AXIS_MEMLAB_LEDGER_HPP
#define AXIS_MEMLAB_LEDGER_HPP

#include "axis_memlab/probe.h"

namespace axis_memlab {

// A named resource category, e.g. "frame" or "tensor". Register once at startup.
class ResourceKind {
 public:
  explicit ResourceKind(const char *name) noexcept : id_(axmem_kind_register(name)) {}
  uint32_t id() const noexcept { return id_; }
  bool valid() const noexcept { return id_ != 0; }
  void acquire(uint64_t resource_id, uint64_t bytes) const noexcept {
    axmem_resource_acquire(resource_id, id_, bytes);
  }
  void release(uint64_t resource_id) const noexcept { axmem_resource_release(resource_id, id_); }

 private:
  uint32_t id_;
};

}  // namespace axis_memlab

#endif
