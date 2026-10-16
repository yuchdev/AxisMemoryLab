#ifndef AXIS_MEMLAB_PROBE_H
#define AXIS_MEMLAB_PROBE_H

#include <stdint.h>

#if !defined(AXMEM_DISABLED) || AXMEM_DISABLED != 1
#error "M0000 supports only AXMEM_DISABLED=1; enabled probes are not implemented"
#endif

#define AXMEM_ABI_VERSION 1
#define AXMEM_STATUS_DISABLED (-1)

#ifdef __cplusplus
extern "C" {
#endif

static inline void axmem_counter_add(const char *name, uint64_t delta) {
  (void)name;
  (void)delta;
}

static inline void axmem_gauge_set(const char *name, uint64_t value) {
  (void)name;
  (void)value;
}

static inline void axmem_resource_acquire(uint64_t id, uint32_t kind, uint64_t bytes) {
  (void)id;
  (void)kind;
  (void)bytes;
}

static inline void axmem_resource_release(uint64_t id, uint32_t kind) {
  (void)id;
  (void)kind;
}

static inline void axmem_phase_marker(const char *phase) {
  (void)phase;
}

static inline int axmem_emit_snapshot(void) { return AXMEM_STATUS_DISABLED; }

#ifdef __cplusplus
}
#endif

#endif
