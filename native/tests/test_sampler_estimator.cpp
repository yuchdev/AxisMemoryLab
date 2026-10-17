// Statistics of the sampler, driven through the manual call-site API with fake pointers so no
// global operator new is involved. Deterministic: a fixed seed gives a fixed sample set.
#include <cmath>
#include <cstdint>
#include <set>

#include "check.hpp"
#include "sampler_util.hpp"
#include "sampler_core.hpp"

namespace {

// Distinct 16-byte-aligned fake addresses; the sampler never dereferences them.
const void *fake(std::uint64_t index) {
  return reinterpret_cast<const void *>(static_cast<std::uintptr_t>(0x100000 + index * 16));
}

double relative_error(double estimate, double truth) { return std::fabs(estimate - truth) / truth; }

}  // namespace

int main() {
  using axmem_internal::sample_probability;

  // The sampling probability follows 1 - exp(-size/interval).
  CHECK(std::fabs(sample_probability(4096, 4096) - (1.0 - std::exp(-1.0))) < 1e-12);
  CHECK(std::fabs(sample_probability(1, 1u << 20) - (1.0 / (1u << 20))) < 1e-9);  // small: ~size/I
  CHECK(sample_probability(1u << 30, 4096) == 1.0);                                // huge: certain
  CHECK(sample_probability(0, 4096) > 0.0);                                         // 0 acts as 1

  const std::string path = temp_path("sampler_estimator");
  auto config = sampler_config(path.c_str(), 4096, 20260101);
  config.max_live_samples = 16384;  // ~3,000 live samples must stay well below the probe limit
  CHECK(axmem_sampler_start(&config) == AXMEM_OK);

  // 1) Exact totals, and unbiased estimates of the cumulative and of the live volume.
  const std::uint64_t n = 200000;
  const std::uint64_t kSize = 64;
  for (std::uint64_t i = 0; i < n; ++i) {
    axmem_sampler_record_alloc(fake(i), kSize, 16);
    if (i % 20000 == 19999) CHECK(axmem_sampler_flush() == AXMEM_OK);  // keep the ring from filling
  }
  for (std::uint64_t i = 0; i < n; i += 2) {  // free every other allocation
    axmem_sampler_record_free(fake(i));
    if (i % 40000 == 39998) CHECK(axmem_sampler_flush() == AXMEM_OK);
  }
  CHECK(axmem_sampler_flush() == AXMEM_OK);

  axmem_sampler_stats stats{};
  stats.struct_size = sizeof stats;
  CHECK(axmem_sampler_get_stats(&stats) == AXMEM_OK);
  CHECK(stats.alloc_requests == n);                // exact, not sampled
  CHECK(stats.alloc_request_bytes == n * kSize);   // exact cumulative bytes
  CHECK(stats.free_requests == n / 2);
  CHECK(stats.dropped_ring_full == 0 && stats.dropped_table_full == 0);
  CHECK(stats.dropped_free_events == 0);
  CHECK(stats.samples_taken > 2000 && stats.samples_taken < 4500);  // expected ~ n*(1-e^-s/I)
  CHECK(stats.frees_matched + stats.live_samples == stats.samples_taken);

  axmem_sampler_stop();
  const ParsedSamples parsed = parse_samples(path);
  CHECK(parsed.headers == 1 && parsed.final_summary && parsed.all_lines_end_cleanly);
  CHECK(parsed.allocs.size() == stats.samples_taken);

  double cumulative = 0;
  std::set<unsigned long long> freed(parsed.frees.begin(), parsed.frees.end());
  CHECK(freed.size() == parsed.frees.size());  // no free is reported twice
  double live = 0;
  for (const AllocRec &a : parsed.allocs) {
    CHECK(a.size == kSize && a.kind == "manual" && a.weight > 1.0);
    cumulative += a.weight * static_cast<double>(a.size);
    if (!freed.count(a.id)) live += a.weight * static_cast<double>(a.size);
  }
  CHECK(relative_error(cumulative, static_cast<double>(n * kSize)) < 0.10);
  CHECK(relative_error(live, static_cast<double>(n / 2 * kSize)) < 0.12);
  // Live is not cumulative: the two estimates differ by about a factor of two here.
  CHECK(live < 0.7 * cumulative);
  for (unsigned long long id : parsed.frees) {
    bool known = false;
    for (const AllocRec &a : parsed.allocs) known = known || a.id == id;
    CHECK(known);  // a free always refers to a recorded sample
  }

  // 2) Mixed sizes, same estimator: a few huge allocations must still be seen (probability ~1).
  const std::string path2 = temp_path("sampler_estimator_mixed");
  auto config2 = sampler_config(path2.c_str(), 8192, 99);
  CHECK(axmem_sampler_start(&config2) == AXMEM_OK);
  const std::uint64_t sizes[] = {16, 100, 1000, 20000, 1u << 20};
  double exact = 0;
  for (std::uint64_t i = 0; i < 60000; ++i) {
    const std::uint64_t s = sizes[i % 5];
    exact += static_cast<double>(s);
    axmem_sampler_record_alloc(fake(1000000 + i), s, 16);
    axmem_sampler_record_free(fake(1000000 + i));  // keep the live table small
    if (i % 500 == 499) axmem_sampler_flush();
  }
  axmem_sampler_stop();
  const ParsedSamples mixed = parse_samples(path2);
  double estimate = 0;
  unsigned big = 0;
  for (const AllocRec &a : mixed.allocs) {
    estimate += a.weight * static_cast<double>(a.size);
    if (a.size == (1u << 20)) ++big;
  }
  CHECK(big == 12000);  // 1 MiB allocations are sampled with probability 1, weight 1
  CHECK(relative_error(estimate, exact) < 0.08);

  // 3) Same seed, same samples; a different seed gives a different sample set.
  auto run = [&](unsigned long long seed, const char *tag) {
    const std::string p = temp_path(tag);
    auto c = sampler_config(p.c_str(), 1024, seed);
    CHECK(axmem_sampler_start(&c) == AXMEM_OK);
    for (std::uint64_t i = 0; i < 5000; ++i) axmem_sampler_record_alloc(fake(i), 100, 16);
    axmem_sampler_stop();
    std::vector<unsigned long long> ids;
    for (const AllocRec &a : parse_samples(p).allocs) ids.push_back(a.id);
    return ids;
  };
  const auto first = run(5, "sampler_seed_a");
  const auto again = run(5, "sampler_seed_b");
  const auto other = run(6, "sampler_seed_c");
  CHECK(!first.empty() && first == again);
  CHECK(first != other);
  return 0;
}
