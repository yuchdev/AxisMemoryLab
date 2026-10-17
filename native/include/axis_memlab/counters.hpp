#ifndef AXIS_MEMLAB_COUNTERS_HPP
#define AXIS_MEMLAB_COUNTERS_HPP

#include "axis_memlab/probe.h"

namespace axis_memlab {

// Registers once (construct at startup, not per frame) and updates with one relaxed atomic.
// A failed registration yields an inert handle: updates are silently ignored and the failure
// is visible as app.probe.registration_rejected_count in the next snapshot.
class Counter {
 public:
  explicit Counter(const char *name) noexcept : handle_(axmem_counter_handle(name)) {}
  void add(uint64_t delta = 1) const noexcept { axmem_counter_add_h(handle_, delta); }
  bool valid() const noexcept { return handle_ != AXMEM_INVALID_HANDLE; }

 private:
  uint32_t handle_;
};

class Gauge {
 public:
  explicit Gauge(const char *name) noexcept : handle_(axmem_gauge_handle(name)) {}
  void set(uint64_t value) const noexcept { axmem_gauge_set_h(handle_, value); }
  void watermark(uint64_t value) const noexcept { axmem_gauge_watermark_h(handle_, value); }
  bool valid() const noexcept { return handle_ != AXMEM_INVALID_HANDLE; }

 private:
  uint32_t handle_;
};

}  // namespace axis_memlab

#endif
