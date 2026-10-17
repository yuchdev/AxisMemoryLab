// Bounds and failure cases of the sampler: bad configuration, double start, overflow of the live
// table and of the ring, and the output cap. Every limit must be counted, never silent.
#include <cstdint>
#include <cstdio>
#include <fstream>

#include "check.hpp"
#include "sampler_util.hpp"

namespace {

const void *fake(std::uint64_t index) {
  return reinterpret_cast<const void *>(static_cast<std::uintptr_t>(0x200000 + index * 16));
}

axmem_sampler_stats stats() {
  axmem_sampler_stats s{};
  s.struct_size = sizeof s;
  CHECK(axmem_sampler_get_stats(&s) == AXMEM_OK);
  return s;
}

bool exists(const std::string &path) {
  std::ifstream in(path, std::ios::binary);
  return in.good();
}

}  // namespace

int main() {
  // ---- before start: nothing runs, nothing crashes -------------------------------------------------
  CHECK(axmem_sampler_active() == 0);
  CHECK(axmem_sampler_flush() == AXMEM_ERR_NOT_INIT);
  axmem_sampler_record_alloc(fake(1), 100, 16);  // ignored while stopped
  axmem_sampler_record_free(fake(1));
  axmem_sampler_stop();  // stopping a stopped sampler is harmless
  axmem_sampler_stats bad_size{};
  CHECK(axmem_sampler_get_stats(&bad_size) == AXMEM_ERR_INVALID);
  CHECK(axmem_sampler_get_stats(nullptr) == AXMEM_ERR_INVALID);

  // ---- invalid configuration is rejected before any file is created --------------------------------
  const std::string path = temp_path("sampler_limits");
  auto good = sampler_config(path.c_str(), 1, 1);
  {
    auto c = good;
    c.struct_size = 1;
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.run_id = "not-a-uuid";
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.device_id = "user@10.0.0.1";  // identifying text is refused
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.max_stack_depth = 33;
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.max_live_samples = 1000;  // not a power of two
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.max_live_samples = 32768;  // above the compile-time maximum
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.output_path = "";
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_INVALID);
    c = good;
    c.output_path = "no_such_directory_axmem/out.jsonl";
    CHECK(axmem_sampler_start(&c) == AXMEM_ERR_IO);
    CHECK(axmem_sampler_start(nullptr) == AXMEM_ERR_INVALID);
    CHECK(!exists(path));
  }

  // ---- double start --------------------------------------------------------------------------------
  CHECK(axmem_sampler_start(&good) == AXMEM_OK);
  CHECK(axmem_sampler_start(&good) == AXMEM_ERR_ALREADY);

  // ---- live-table overflow: tracked samples are bounded, the rest are counted ----------------------
  auto small = good;
  axmem_sampler_stop();
  std::remove(path.c_str());
  small.max_live_samples = 16;
  CHECK(axmem_sampler_start(&small) == AXMEM_OK);
  for (std::uint64_t i = 0; i < 200; ++i) axmem_sampler_record_alloc(fake(i), 4096, 16);
  axmem_sampler_stats s = stats();
  CHECK(s.alloc_requests == 200);  // the exact counters do not depend on the table
  CHECK(s.live_samples <= 16);
  CHECK(s.dropped_table_full > 0);
  CHECK(s.samples_taken + s.dropped_table_full + s.dropped_ring_full == 200);
  const unsigned long long tracked = s.samples_taken;
  for (std::uint64_t i = 0; i < 200; ++i) axmem_sampler_record_free(fake(i));
  s = stats();
  CHECK(s.frees_matched == tracked && s.live_samples == 0);  // only tracked ones can be matched
  axmem_sampler_stop();

  // ---- ring overflow: nothing is flushed, so only the ring's worth is kept ---------------------------
  std::remove(path.c_str());
  auto big_table = good;
  big_table.max_live_samples = 16384;
  CHECK(axmem_sampler_start(&big_table) == AXMEM_OK);
  for (std::uint64_t i = 0; i < 5000; ++i) axmem_sampler_record_alloc(fake(i), 4096, 16);
  s = stats();
  CHECK(s.samples_taken == 1024);  // AXMEM_SAMPLER_RING default
  CHECK(s.dropped_ring_full == 5000 - 1024);
  CHECK(s.live_samples == 1024);  // dropped ones were not left in the table
  // Freeing tracked ones fills the ring with free events; those that do not fit are counted.
  for (std::uint64_t i = 0; i < 5000; ++i) axmem_sampler_record_free(fake(i));
  s = stats();
  CHECK(s.frees_matched == 1024 && s.live_samples == 0);
  CHECK(s.dropped_free_events == 1024);  // the ring was still full of allocs: all frees dropped
  axmem_sampler_stop();
  ParsedSamples parsed = parse_samples(path);
  CHECK(parsed.allocs.size() == 1024 && parsed.frees.empty());
  CHECK(parsed.summary["dropped_free_events"] == 1024);  // the reader is told the estimate is suspect

  // ---- output cap: hard limit, no torn lines, summary still written ---------------------------------
  std::remove(path.c_str());
  auto capped = good;
  capped.max_output_bytes = 40000;  // room for the header and module table, little else
  capped.max_live_samples = 16384;
  const int started = axmem_sampler_start(&capped);
  if (started == AXMEM_OK) {
    int limit_seen = 0;
    for (int round = 0; round < 40; ++round) {
      for (std::uint64_t i = 0; i < 500; ++i) axmem_sampler_record_alloc(fake(round * 500 + i), 4096, 16);
      if (axmem_sampler_flush() == AXMEM_ERR_LIMIT) ++limit_seen;
    }
    CHECK(limit_seen > 0);
    s = stats();
    CHECK(s.dropped_output_cap > 0);
    CHECK(s.output_bytes <= 40000);
    axmem_sampler_stop();
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    CHECK(static_cast<unsigned long long>(in.tellg()) <= 40000);
    parsed = parse_samples(path);
    CHECK(parsed.all_lines_end_cleanly);
    CHECK(parsed.final_summary);  // the reserve guarantees a closing summary
  } else {
    // The header (module table) did not fit under the cap: refused cleanly, nothing half-written.
    CHECK(started == AXMEM_ERR_LIMIT);
  }
  return 0;
}
