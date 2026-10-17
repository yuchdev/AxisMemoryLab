#ifndef AXIS_MEMLAB_SAMPLER_CORE_HPP
#define AXIS_MEMLAB_SAMPLER_CORE_HPP

// Internal interface between the global operator new/delete hooks and the sampler engine.
//
// Protocol for an allocation (see new_hook.cpp):
//   sampled = sampler_begin(size)       cheap; counts the request and decides by byte-interval
//   if (sampled) sampler_capture(fp,ra) record the stack BEFORE the real allocation runs
//   p = <standard allocation>           new_handler loop, bad_alloc, nothrow: unchanged
//   if (p && sampled) sampler_end(...)  attach the pointer, track it, queue the record
//   if (!p || exception) sampler_abort()
// For a deallocation: sampler_free(p) runs BEFORE the memory is released, so a recycled address
// cannot be matched against the wrong sample.

#include <cstddef>
#include <cstdint>

namespace axmem_internal {

enum AllocKind : std::uint32_t {
  kKindNew = 1,
  kKindNewArray = 2,
  kKindNewNothrow = 3,
  kKindNewArrayNothrow = 4,
  kKindNewAligned = 5,
  kKindNewArrayAligned = 6,
  kKindNewAlignedNothrow = 7,
  kKindNewArrayAlignedNothrow = 8,
  kKindManual = 9,
};

bool sampler_active() noexcept;
bool sampler_begin(std::size_t size) noexcept;
void sampler_capture(void *hook_fp, void *hook_ra) noexcept;
void sampler_end(void *p, std::size_t size, std::size_t align, AllocKind kind) noexcept;
void sampler_abort() noexcept;
void sampler_free(void *p) noexcept;

struct SamplerCounters {
  std::uint64_t alloc_requests, alloc_request_bytes, free_requests;
  std::uint64_t samples_taken, frees_matched, live_samples;
  std::uint64_t dropped_table_full, dropped_ring_full, dropped_free_events;
  std::uint64_t dropped_output_cap, stack_failures, flushes, output_bytes;
};
void sampler_counters(SamplerCounters &out) noexcept;

// Pure helpers exposed for tests.
// Probability that an allocation of `size` bytes is sampled at the given mean interval.
double sample_probability(std::uint64_t size, std::uint64_t interval) noexcept;

}  // namespace axmem_internal

#endif
