#include <thread>
#include <vector>

#include "axis_memlab/probe.hpp"
#include "check.hpp"

static axmem_config make_config(const std::string &path) {
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = kRunId;
  config.device_id = "synthetic-device-001";
  config.include_smaps_rollup = 1;
  config.include_fd_count = 1;
  return config;
}

static std::size_t count_lines(const std::string &text) {
  std::size_t lines = 0;
  for (char c : text) lines += (c == '\n');
  return lines;
}

int main() {
  const std::string path = temp_path("snapshot");
  axmem_config config = make_config(path);

  // Before init: updates work, snapshots do not.
  const uint32_t frames = axmem_counter_handle("app.frames_total_count");
  CHECK(axmem_emit_snapshot() == AXMEM_ERR_NOT_INIT);

  // Invalid configurations are rejected without creating the file.
  axmem_config bad = config;
  bad.run_id = "not-a-uuid";
  CHECK(axmem_init(&bad) == AXMEM_ERR_INVALID);
  bad = config;
  bad.device_id = "user@10.0.0.1";  // identifying text is refused, not stored
  CHECK(axmem_init(&bad) == AXMEM_ERR_INVALID);
  bad = config;
  bad.struct_size = 1;
  CHECK(axmem_init(&bad) == AXMEM_ERR_INVALID);
  CHECK(axmem_init(nullptr) == AXMEM_ERR_INVALID);
  CHECK(slurp(path).empty());

  CHECK(axmem_init(&config) == AXMEM_OK);
  CHECK(axmem_init(&config) == AXMEM_ERR_ALREADY);

  // Exact totals under concurrency (relaxed atomics lose no increments).
  std::vector<std::thread> threads;
  for (int t = 0; t < 4; ++t) {
    threads.emplace_back([&] {
      for (int i = 0; i < 50000; ++i) axmem_counter_add_h(frames, 1);
    });
  }
  for (auto &th : threads) th.join();
  axis_memlab::Gauge queue("app.queue.depth_count");
  axis_memlab::Gauge hwm("app.queue.high_watermark_bytes");
  queue.set(0);  // a measured zero must be exported as 0, not omitted
  hwm.watermark(10);
  hwm.watermark(5);
  hwm.watermark(30);
  axmem_gauge_set("app.name_based_count", 3);

  axmem_phase_marker("T2");
  axmem_phase_marker("bad phase");  // rejected: space
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_shutdown();

  const std::string text = slurp(path);
  CHECK(contains(text, "\"record_type\":\"event\""));
  CHECK(contains(text, "\"phase\":\"T2\""));
  CHECK(!contains(text, "bad phase"));
  CHECK(contains(text, "\"app.frames_total_count\":{\"value\":200000,\"unit\":\"count\""));
  CHECK(contains(text, "\"app.queue.depth_count\":{\"value\":0,"));
  CHECK(contains(text, "\"app.queue.high_watermark_bytes\":{\"value\":30,\"unit\":\"bytes\""));
  CHECK(contains(text, "\"app.name_based_count\":{\"value\":3,"));
  CHECK(contains(text, "\"run_id\":\"00000000-0000-4000-8000-0000000000c3\""));
  CHECK(contains(text, "\"device_id\":\"synthetic-device-001\""));
  CHECK(contains(text, "\"producer\":\"axmem-probe\""));
  // First snapshot cannot report its own duration; the second can.
  CHECK(contains(text, "\"app.probe.snapshot_duration_ns\":{\"available\":false,\"reason\""));
  CHECK(contains(text, "\"app.probe.snapshot_duration_ns\":{\"value\":"));
  CHECK(contains(text, "\"app.probe.rejected_calls_count\":{\"value\":1,"));
  // Process memory is either a real value or an explicit unavailable reason, never missing.
  CHECK(contains(text, "\"process.rss_anon_bytes\":{"));
  // Opt-in sources are present as a value or an explicit unavailable reason.
  CHECK(contains(text, "\"process.pss_bytes\":{"));
  CHECK(contains(text, "\"process.fd_count\":{"));
  CHECK(!contains(text, ":nan") && !contains(text, ":inf") && !contains(text, "NaN"));
  // One phase event + two samples, each a self-contained line.
  CHECK(count_lines(text) == 3);

  // Re-init after shutdown appends to the same file.
  CHECK(axmem_init(&config) == AXMEM_OK);
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_shutdown();
  CHECK(count_lines(slurp(path)) == 4);
  return 0;
}
