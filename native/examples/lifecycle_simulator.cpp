// Synthetic frame pipeline with optional injected lifecycle defects. It uses no camera SDK; the
// "frames" are integers. Output is a JSON Lines file of probe records that the Python analysis
// can read (see tests/integration/test_native_probe.py).
//
//   usage: axis_memlab_lifecycle_simulator OUTPUT MODE [SNAPSHOTS] [ITERATIONS] [INTERVAL_MS]
//                                          [LEAK_EVERY]
//   MODE:  ok     every frame is released, the queue stays shallow
//          leak   every LEAK_EVERY-th frame (default 10) skips its release on an error path
//          queue  frames are released but a result queue is never drained
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "axis_memlab/probe.hpp"

namespace {

void spin_for(std::chrono::milliseconds duration) {
  const auto end = std::chrono::steady_clock::now() + duration;
  while (std::chrono::steady_clock::now() < end) {
  }
}

}  // namespace

int main(int argc, char **argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: %s OUTPUT ok|leak|queue [SNAPSHOTS] [ITERATIONS] [INTERVAL_MS]\n",
                 argv[0]);
    return 2;
  }
  const std::string mode = argv[2];
  if (mode != "ok" && mode != "leak" && mode != "queue") {
    std::fprintf(stderr, "unknown mode: %s\n", mode.c_str());
    return 2;
  }
  const int snapshots = argc > 3 ? std::atoi(argv[3]) : 40;
  const int iterations = argc > 4 ? std::atoi(argv[4]) : 200;
  const int interval_ms = argc > 5 ? std::atoi(argv[5]) : 5;
  const uint64_t leak_every = argc > 6 ? std::strtoull(argv[6], nullptr, 10) : 10;
  if (leak_every == 0) {
    std::fprintf(stderr, "LEAK_EVERY must be positive\n");
    return 2;
  }

  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = argv[1];
  config.run_id = "00000000-0000-4000-8000-0000000000d4";
  config.device_id = "synthetic-device-001";
  config.max_output_bytes = 8u * 1024u * 1024u;
  config.include_fd_count = 1;
  config.include_smaps_rollup = 1;
  if (axmem_init(&config) != AXMEM_OK) {
    std::fprintf(stderr, "axmem_init failed\n");
    return 1;
  }

  axis_memlab::ResourceKind frame("frame");
  axis_memlab::Counter frames_total("app.frames_total_count");
  axis_memlab::Counter recognitions("app.recognitions_total_count");
  axis_memlab::Gauge queue_depth("app.queue.depth_count");
  axmem_phase_marker("T2");

  uint64_t next_id = 1;
  uint64_t depth = 0;
  for (int s = 0; s < snapshots; ++s) {
    for (int i = 0; i < iterations; ++i) {
      const uint64_t id = next_id++;
      frame.acquire(id, 4096);
      frames_total.add();
      // ... the application would process the frame here ...
      const bool error_path = (mode == "leak") && (id % leak_every == 0);
      if (!error_path) frame.release(id);  // the injected defect: release skipped
      if (mode == "queue") {
        if (id % 10 == 0) {
          ++depth;  // one recognition result per 10 frames, pushed and never drained
          recognitions.add();
        }
      } else {
        depth = id % 5;  // shallow, bounded
        if (id % 10 == 0) recognitions.add();
      }
      queue_depth.set(depth);
    }
    if (axmem_emit_snapshot() != AXMEM_OK) {
      std::fprintf(stderr, "snapshot failed\n");
      return 1;
    }
    spin_for(std::chrono::milliseconds(interval_ms));
  }
  axmem_shutdown();
  return 0;
}
