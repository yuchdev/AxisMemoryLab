#include "axis_memlab/probe.hpp"

int main() {
  axis_memlab::Counter frames("app.frames_total_count");
  axis_memlab::ResourceKind kind("frame");
  {
    axis_memlab::ResourceGuard guard(1, kind.id(), 64);
    frames.add();
    axmem_phase_marker("synthetic-phase");
  }
  // Disabled mode: handles are inert and snapshots report that nothing is collected.
  if (frames.valid() || kind.valid()) return 1;
  return axmem_emit_snapshot() == AXMEM_STATUS_DISABLED ? 0 : 1;
}
