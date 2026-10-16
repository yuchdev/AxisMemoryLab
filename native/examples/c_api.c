#include "axis_memlab/probe.h"

int main(void) {
  axmem_counter_add("synthetic.counter", 1);
  axmem_gauge_set("synthetic.gauge", 2);
  axmem_resource_acquire(1, 1, 64);
  axmem_resource_release(1, 1);
  axmem_phase_marker("synthetic-phase");
  return axmem_emit_snapshot() == AXMEM_STATUS_DISABLED ? 0 : 1;
}
