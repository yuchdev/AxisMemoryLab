#ifndef AXIS_MEMLAB_PROBE_H
#define AXIS_MEMLAB_PROBE_H

/*
 * Axis Memory Lab in-app probe API (ABI version 2, provisional).
 *
 * Exactly one build mode must be selected by the build system:
 *   AXMEM_DISABLED=1  inline no-ops, header only, nothing to link;
 *   AXMEM_COUNTERS=1  relaxed-atomic counters/gauges, per-kind resource totals, snapshots;
 *   AXMEM_LEDGER=1    COUNTERS plus a fixed-capacity identity ledger (development use).
 * AXMEM_SAMPLER (allocation sampling) belongs to milestone 0004 and is not available.
 *
 * Hot-path calls (counter/gauge by handle, resource acquire/release) perform no I/O, no
 * allocation, and take no lock in COUNTERS mode. axmem_init, axmem_phase_marker, and
 * axmem_emit_snapshot do file I/O and must be called from a timer or control thread, never
 * from a frame path. The library never opens a network connection or starts a thread.
 */

#include <stdint.h>

#if defined(AXMEM_DISABLED) && AXMEM_DISABLED == 1
#define AXMEM_MODE_DISABLED_ 1
#else
#define AXMEM_MODE_DISABLED_ 0
#endif
#if defined(AXMEM_COUNTERS) && AXMEM_COUNTERS == 1
#define AXMEM_MODE_COUNTERS_ 1
#else
#define AXMEM_MODE_COUNTERS_ 0
#endif
#if defined(AXMEM_LEDGER) && AXMEM_LEDGER == 1
#define AXMEM_MODE_LEDGER_ 1
#else
#define AXMEM_MODE_LEDGER_ 0
#endif
#if (AXMEM_MODE_DISABLED_ + AXMEM_MODE_COUNTERS_ + AXMEM_MODE_LEDGER_) != 1
#error "Define exactly one of AXMEM_DISABLED=1, AXMEM_COUNTERS=1, AXMEM_LEDGER=1"
#endif
#if defined(AXMEM_SAMPLER) && AXMEM_SAMPLER == 1
#error "AXMEM_SAMPLER is owned by milestone 0004 and is not implemented"
#endif

#define AXMEM_ABI_VERSION 2

#define AXMEM_OK 0
#define AXMEM_STATUS_DISABLED (-1)
#define AXMEM_ERR_INVALID (-2)   /* bad argument, name, or configuration */
#define AXMEM_ERR_IO (-3)        /* file could not be opened or written */
#define AXMEM_ERR_LIMIT (-4)     /* output size cap reached; the record was not written */
#define AXMEM_ERR_NOT_INIT (-5)  /* axmem_init has not succeeded */
#define AXMEM_ERR_ALREADY (-6)   /* axmem_init called twice */

#define AXMEM_INVALID_HANDLE 0xFFFFFFFFu
#define AXMEM_MODE_ID_DISABLED 0u
#define AXMEM_MODE_ID_COUNTERS 1u
#define AXMEM_MODE_ID_LEDGER 2u

#ifdef __cplusplus
extern "C" {
#endif

typedef struct axmem_config {
  uint32_t struct_size;         /* sizeof(axmem_config) */
  const char *output_path;      /* JSON Lines file, appended to; required */
  const char *run_id;           /* UUID text, e.g. 00000000-0000-4000-8000-000000000001 */
  const char *device_id;        /* pseudonymous id; [A-Za-z0-9._-], at most 64 chars */
  uint64_t max_output_bytes;    /* hard cap for the file written by this process; 0 = 4 MiB */
  uint32_t include_allocator_stats; /* 1 = add glibc mallinfo2 metrics when available */
  uint32_t include_smaps_rollup;    /* 1 = read /proc/self/smaps_rollup each snapshot (PSS,
                                       private, anonymous; costs a page-table scan) */
  uint32_t include_fd_count;        /* 1 = count /proc/self/fd entries each snapshot */
} axmem_config;

#if AXMEM_MODE_DISABLED_

static inline int axmem_init(const axmem_config *config) {
  (void)config;
  return AXMEM_STATUS_DISABLED;
}
static inline void axmem_shutdown(void) {}
static inline uint32_t axmem_mode(void) { return AXMEM_MODE_ID_DISABLED; }
static inline uint32_t axmem_counter_handle(const char *name) {
  (void)name;
  return AXMEM_INVALID_HANDLE;
}
static inline uint32_t axmem_gauge_handle(const char *name) {
  (void)name;
  return AXMEM_INVALID_HANDLE;
}
static inline void axmem_counter_add_h(uint32_t handle, uint64_t delta) {
  (void)handle;
  (void)delta;
}
static inline void axmem_gauge_set_h(uint32_t handle, uint64_t value) {
  (void)handle;
  (void)value;
}
static inline void axmem_gauge_watermark_h(uint32_t handle, uint64_t value) {
  (void)handle;
  (void)value;
}
static inline void axmem_counter_add(const char *name, uint64_t delta) {
  (void)name;
  (void)delta;
}
static inline void axmem_gauge_set(const char *name, uint64_t value) {
  (void)name;
  (void)value;
}
static inline uint32_t axmem_kind_register(const char *name) {
  (void)name;
  return 0;
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
static inline void axmem_phase_marker(const char *phase) { (void)phase; }
static inline int axmem_emit_snapshot(void) { return AXMEM_STATUS_DISABLED; }

#else /* COUNTERS or LEDGER: implemented in native/src/probe.cpp */

/* Open the sink. Counters may be registered and updated before or without init; only
 * markers and snapshots need it. Returns AXMEM_OK or a negative AXMEM_ERR_* code. */
int axmem_init(const axmem_config *config);
/* Flush and close the sink. Registered names and values are kept. */
void axmem_shutdown(void);
/* AXMEM_MODE_ID_COUNTERS or AXMEM_MODE_ID_LEDGER, as compiled into the library. */
uint32_t axmem_mode(void);

/* Names must match ^app\.[a-z0-9_.]{1,60}$ so snapshots validate against record-v1; a name
 * ending in _bytes is exported in bytes, _ns in nanoseconds, anything else as a count.
 * Registration is idempotent. Returns AXMEM_INVALID_HANDLE when the name is invalid, the
 * name is already registered with the other kind, or the fixed table (128) is full; the
 * failure is counted in app.probe.registration_rejected_count. */
uint32_t axmem_counter_handle(const char *name);
uint32_t axmem_gauge_handle(const char *name);

void axmem_counter_add_h(uint32_t handle, uint64_t delta);      /* relaxed atomic add */
void axmem_gauge_set_h(uint32_t handle, uint64_t value);        /* relaxed atomic store */
void axmem_gauge_watermark_h(uint32_t handle, uint64_t value);  /* keep the maximum */

/* Name-based forms look the name up on every call; prefer handles on hot paths. */
void axmem_counter_add(const char *name, uint64_t delta);
void axmem_gauge_set(const char *name, uint64_t value);

/* Resource kinds (at most 16) use the same name rule as counters, without the app. prefix.
 * Returns 0 on failure; valid kinds are nonzero. Per-kind totals are exported as
 * app.resource.<kind>.{acquired_total_count,released_total_count,in_flight_count} and, in
 * LEDGER mode only, {in_flight_bytes,high_watermark_bytes}. */
uint32_t axmem_kind_register(const char *name);
/* The application decides what an id is and when a resource is really owned. Calls with an
 * unregistered kind are counted as rejected. In LEDGER mode a repeated acquire of a live id
 * and a release of an unknown id are counted, not applied. */
void axmem_resource_acquire(uint64_t id, uint32_t kind, uint64_t bytes);
void axmem_resource_release(uint64_t id, uint32_t kind);

/* Record a phase boundary event ({"event":"phase_start","phase":...}). The phase string
 * must match [A-Za-z0-9_.:-]{1,48}. Without init the call is a counted no-op. */
void axmem_phase_marker(const char *phase);

/* Append one `sample` record. AXMEM_ERR_LIMIT when the output cap would be exceeded. */
int axmem_emit_snapshot(void);

#endif

#ifdef __cplusplus
}
#endif

#endif
