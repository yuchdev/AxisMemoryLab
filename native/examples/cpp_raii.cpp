#include "axis_memlab/probe.hpp"

int main() {
  {
    axis_memlab::ResourceGuard guard(1, 1, 64);
    axmem_phase_marker("synthetic-phase");
  }
  return axmem_emit_snapshot() == AXMEM_STATUS_DISABLED ? 0 : 1;
}
