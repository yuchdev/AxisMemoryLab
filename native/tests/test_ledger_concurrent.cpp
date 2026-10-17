#include <thread>
#include <vector>

#include "axis_memlab/probe.hpp"
#include "check.hpp"

int main() {
  axis_memlab::ResourceKind buffer("buffer");
  CHECK(buffer.valid());
  const int kThreads = 4;
  const uint64_t kPerThread = 3000;  // 1200 stay live: below the 4096 capacity
  std::vector<std::thread> threads;
  for (int t = 0; t < kThreads; ++t) {
    threads.emplace_back([&, t] {
      const uint64_t base = static_cast<uint64_t>(t) * 1000000u;
      for (uint64_t i = 0; i < kPerThread; ++i) {
        buffer.acquire(base + i, 10);
        if (i % 10 != 0) buffer.release(base + i);
      }
    });
  }
  for (auto &th : threads) th.join();

  const std::string path = temp_path("ledger_concurrent");
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = kRunId;
  config.device_id = "synthetic-device-001";
  CHECK(axmem_init(&config) == AXMEM_OK);
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_shutdown();
  const std::string text = slurp(path);
  CHECK(value_of(text, "app.resource.buffer.in_flight_count") == 1200);
  CHECK(value_of(text, "app.resource.buffer.in_flight_bytes") == 12000);
  CHECK(value_of(text, "app.resource.buffer.acquired_total_count") == 12000);
  CHECK(value_of(text, "app.resource.buffer.released_total_count") == 10800);
  CHECK(value_of(text, "app.ledger.unmatched_release_count") == 0);
  CHECK(value_of(text, "app.ledger.duplicate_acquire_count") == 0);
  CHECK(value_of(text, "app.ledger.events_dropped_count") == 0);
  return 0;
}
