// With the sampler compiled in, the regular probe snapshot carries the sampler's health metrics.
#include <cstdint>

#include "axis_memlab/probe.h"
#include "axis_memlab/sampler.h"
#include "check.hpp"
#include "sampler_util.hpp"

int main() {
  const std::string probe_path = temp_path("snapshot_sampler_probe");
  const std::string sample_path = temp_path("snapshot_sampler_samples");
  axmem_config pc{};
  pc.struct_size = sizeof pc;
  pc.output_path = probe_path.c_str();
  pc.run_id = kRunId;
  pc.device_id = "synthetic-device-001";
  CHECK(axmem_init(&pc) == AXMEM_OK);

  // Not running: no sampler metrics, and nothing implies zero allocations.
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  CHECK(!contains(slurp(probe_path), "app.sampler."));

  auto sc = sampler_config(sample_path.c_str(), 1, 3);
  CHECK(axmem_sampler_start(&sc) == AXMEM_OK);
  for (unsigned i = 0; i < 20; ++i) {
    axmem_sampler_record_alloc(reinterpret_cast<const void *>(static_cast<std::uintptr_t>(0x400000 + i * 16)), 1024, 16);
  }
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_sampler_stop();
  axmem_shutdown();

  const std::string text = slurp(probe_path);
  CHECK_EQ(value_of(text, "app.sampler.alloc_requests_count"), 20ll);
  CHECK_EQ(value_of(text, "app.sampler.alloc_requested_total_bytes"), 20ll * 1024);
  CHECK_EQ(value_of(text, "app.sampler.samples_taken_count"), 20ll);
  CHECK_EQ(value_of(text, "app.sampler.live_samples_count"), 20ll);
  CHECK(contains(text, "\"app.sampler.alloc_requested_total_bytes\":{\"value\":20480,\"unit\":\"bytes\""));
  return 0;
}
