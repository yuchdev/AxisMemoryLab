#ifndef AXIS_MEMLAB_SAMPLER_H
#define AXIS_MEMLAB_SAMPLER_H

/*
 * Statistical allocation sampler (milestone 0004, development use only).
 *
 * Build with AXMEM_SAMPLER=1 on top of AXMEM_COUNTERS or AXMEM_LEDGER. When it is not compiled
 * in, every function below is an inline stub, so application code can call it unconditionally.
 *
 * What it does. It samples allocations by BYTES, not by count: the gap between samples is drawn
 * from an exponential distribution with mean `sample_interval_bytes`, so an allocation of s
 * bytes is sampled with probability 1 - exp(-s / interval). Each sample records the size,
 * alignment, kind, thread, time, and a bounded call stack of raw program counters, plus a weight
 * 1 / probability so that sums over samples are unbiased estimates of the totals. A sampled
 * allocation is remembered until it is freed; the free is recorded too, which lets the host
 * estimate what is still LIVE. Cumulative allocated volume is never reported as live volume.
 *
 * What it does not do. It never symbolizes, demangles, or resolves anything on the device. It
 * covers only operator new / new[] (through the hook library `axis_memlab_new_hook`) and the
 * manual calls below. malloc, mmap, SDK buffers, and allocations made before axmem_sampler_start
 * are not seen. Frees of allocations the sampler did not sample are only counted.
 *
 * Cost control. Samples go to a fixed in-memory ring; nothing is written until the application
 * calls axmem_sampler_flush() from a control thread, so no I/O happens on an allocation path.
 * The ring, the live-sample table, and the output file are all bounded; overflow is counted,
 * never silent.
 */

#include <stddef.h>
#include <stdint.h>

#include "axis_memlab/probe.h"

#define AXMEM_ERR_UNSUPPORTED (-7) /* this platform or build cannot do that */

#define AXMEM_ALLOC_NEW 1u
#define AXMEM_ALLOC_NEW_ARRAY 2u
#define AXMEM_ALLOC_NEW_NOTHROW 3u
#define AXMEM_ALLOC_NEW_ARRAY_NOTHROW 4u
#define AXMEM_ALLOC_NEW_ALIGNED 5u
#define AXMEM_ALLOC_NEW_ARRAY_ALIGNED 6u
#define AXMEM_ALLOC_NEW_ALIGNED_NOTHROW 7u
#define AXMEM_ALLOC_NEW_ARRAY_ALIGNED_NOTHROW 8u
#define AXMEM_ALLOC_MANUAL 9u

#ifdef __cplusplus
extern "C" {
#endif

typedef struct axmem_sampler_config {
  uint32_t struct_size;            /* sizeof(axmem_sampler_config) */
  const char *output_path;         /* alloc-samples-v1 JSON Lines file, appended to; required */
  const char *run_id;              /* UUID text, ties the file to a run */
  const char *device_id;           /* pseudonymous label, [A-Za-z0-9._-], at most 64 chars */
  uint64_t sample_interval_bytes;  /* mean bytes between samples; 0 = 524288 (512 KiB) */
  uint32_t max_stack_depth;        /* 1..32; 0 = 16 */
  uint32_t max_live_samples;       /* live-sample table size, power of two <= 16384; 0 = 4096 */
  uint64_t max_output_bytes;       /* hard cap on the file written by this process; 0 = 4 MiB */
  uint64_t seed;                   /* nonzero = deterministic sampling (tests); 0 = from clock */
} axmem_sampler_config;

typedef struct axmem_sampler_stats {
  uint32_t struct_size;            /* set to sizeof(axmem_sampler_stats) before the call */
  uint64_t alloc_requests;         /* exact: allocation requests seen while running */
  uint64_t alloc_request_bytes;    /* exact: sum of requested sizes (cumulative, NOT live) */
  uint64_t free_requests;          /* exact: frees seen while running */
  uint64_t samples_taken;          /* allocations sampled and tracked */
  uint64_t frees_matched;          /* frees of tracked (sampled) allocations */
  uint64_t live_samples;           /* tracked allocations not yet freed */
  uint64_t dropped_table_full;     /* sample not taken: live table full */
  uint64_t dropped_ring_full;      /* alloc sample not taken: ring full */
  uint64_t dropped_free_events;    /* free events lost (ring or output cap): live estimate suspect */
  uint64_t dropped_output_cap;     /* records not written because the output cap was reached */
  uint64_t stack_failures;         /* samples with an empty stack (no unwinder / bounds) */
  uint64_t flushes;                /* flush calls that wrote records */
  uint64_t output_bytes;           /* bytes written so far */
} axmem_sampler_stats;

#if AXMEM_SAMPLER_

/* Open the output, write the header and module table, and start sampling. AXMEM_OK or a
 * negative AXMEM_ERR_*. Call once; allocations made before this are invisible to it. */
int axmem_sampler_start(const axmem_sampler_config *config);

/* Append pending sample records, a `modules` record if the loaded modules changed, and a
 * `summary`. Call from a control or timer thread, never from an allocation path. AXMEM_ERR_LIMIT
 * means the file cap was reached and nothing further will be written. */
int axmem_sampler_flush(void);

/* Final flush, stop sampling, close the file. Allocation and free keep working normally. */
void axmem_sampler_stop(void);

/* Nonzero while sampling is running. */
uint32_t axmem_sampler_active(void);

int axmem_sampler_get_stats(axmem_sampler_stats *out);

/* Manual call-site instrumentation, for allocators the hook library does not cover (an SDK
 * buffer API, a pool). The caller states the pointer, size, and alignment; the stack is that
 * of the caller. Pair every record_alloc with a record_free. */
void axmem_sampler_record_alloc(const void *p, size_t size, size_t align);
void axmem_sampler_record_free(const void *p);

#else /* sampler not compiled in: inline stubs so callers need no #ifdef */

static inline int axmem_sampler_start(const axmem_sampler_config *config) {
  (void)config;
  return AXMEM_STATUS_DISABLED;
}
static inline int axmem_sampler_flush(void) { return AXMEM_STATUS_DISABLED; }
static inline void axmem_sampler_stop(void) {}
static inline uint32_t axmem_sampler_active(void) { return 0; }
static inline int axmem_sampler_get_stats(axmem_sampler_stats *out) {
  (void)out;
  return AXMEM_STATUS_DISABLED;
}
static inline void axmem_sampler_record_alloc(const void *p, size_t size, size_t align) {
  (void)p;
  (void)size;
  (void)align;
}
static inline void axmem_sampler_record_free(const void *p) { (void)p; }

#endif

#ifdef __cplusplus
}
#endif

#endif
