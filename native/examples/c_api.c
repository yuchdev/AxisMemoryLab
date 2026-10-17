#include "axis_memlab/probe.h"

int main(void) {
  /* In disabled mode nothing is registered, recorded, or written. */
  if (axmem_mode() != AXMEM_MODE_ID_DISABLED) return 1;
  if (axmem_init((const axmem_config *)0) != AXMEM_STATUS_DISABLED) return 1;
  if (axmem_counter_handle("app.synthetic_count") != AXMEM_INVALID_HANDLE) return 1;
  axmem_counter_add("app.synthetic_count", 1);
  axmem_gauge_set("app.synthetic_gauge_count", 2);
  axmem_resource_acquire(1, axmem_kind_register("frame"), 64);
  axmem_resource_release(1, 1);
  axmem_phase_marker("synthetic-phase");
  axmem_shutdown();
  return axmem_emit_snapshot() == AXMEM_STATUS_DISABLED ? 0 : 1;
}
