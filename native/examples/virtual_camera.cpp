// A virtual CCTV analytics pipeline for exercising the whole toolset without a camera.
//
// It has the memory shape of a camera application and none of the camera-specific parts: no AXIS
// SDK, no VDO, no Larod, no network. A paced "capture" loop produces frames; each frame goes
// through a conversion buffer and a small inference tensor, may produce a detection result that
// is queued for a slower publisher thread, and is released. Optional defects reproduce the usual
// ways such pipelines grow, so the tools can be pointed at a known cause.
//
//   usage: axis_memlab_virtual_camera [options]
//     --width N --height N --fps N          frame geometry and rate (default 640 360 15)
//     --seconds N                           run time (default 10)
//     --no-pacing                           run as fast as possible (tests)
//     --defect none|release_miss|queue_growth|reconnect_leak|cache_growth
//     --defect-every N                      release_miss: every Nth frame is not released (50)
//     --queue-max N                         results queue bound, 0 = unbounded (0 with queue_growth)
//     --publisher-hz N                      results the publisher drains per second (200)
//     --reconnect-seconds N                 restart the "stream" every N seconds, 0 = never (0)
//     --probe-out FILE                      probe JSON Lines output (record-v1)
//     --snapshot-ms N                       probe snapshot period (1000)
//     --sampler-out FILE                    allocation sample file (needs an AXMEM_SAMPLER build)
//     --sampler-interval-bytes N            mean bytes between samples (65536)
//     --phase NAME                          initial phase marker (T2)
//     --run-id UUID --device-id LABEL       identity written to the outputs
//
// The summary printed on stdout lists the configuration and the amounts the chosen defect
// retains, so a test (or a person) can compare the tools' estimates with the truth.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "axis_memlab/probe.hpp"
#include "axis_memlab/sampler.h"

namespace {

using Clock = std::chrono::steady_clock;

struct Options {
  unsigned width = 640, height = 360, fps = 15;
  double seconds = 10;
  bool pacing = true;
  std::string defect = "none";
  unsigned defect_every = 50;
  long queue_max = -1;  // -1: choose from the defect
  unsigned publisher_hz = 200;
  double reconnect_seconds = 0;
  std::string probe_out, sampler_out;
  unsigned snapshot_ms = 1000;
  unsigned long long sampler_interval = 65536;
  std::string phase = "T2";
  std::string run_id = "00000000-0000-4000-8000-0000000000f1";
  std::string device_id = "virtual-board-001";
};

bool parse(int argc, char **argv, Options &o, std::string &error) {
  for (int i = 1; i < argc; ++i) {
    const std::string key = argv[i];
    auto value = [&]() -> const char * { return i + 1 < argc ? argv[++i] : nullptr; };
    if (key == "--no-pacing") {
      o.pacing = false;
      continue;
    }
    const char *v = value();
    if (v == nullptr) {
      error = "missing value for " + key;
      return false;
    }
    if (key == "--width") o.width = static_cast<unsigned>(std::atoi(v));
    else if (key == "--height") o.height = static_cast<unsigned>(std::atoi(v));
    else if (key == "--fps") o.fps = static_cast<unsigned>(std::atoi(v));
    else if (key == "--seconds") o.seconds = std::atof(v);
    else if (key == "--defect") o.defect = v;
    else if (key == "--defect-every") o.defect_every = static_cast<unsigned>(std::atoi(v));
    else if (key == "--queue-max") o.queue_max = std::atol(v);
    else if (key == "--publisher-hz") o.publisher_hz = static_cast<unsigned>(std::atoi(v));
    else if (key == "--reconnect-seconds") o.reconnect_seconds = std::atof(v);
    else if (key == "--probe-out") o.probe_out = v;
    else if (key == "--snapshot-ms") o.snapshot_ms = static_cast<unsigned>(std::atoi(v));
    else if (key == "--sampler-out") o.sampler_out = v;
    else if (key == "--sampler-interval-bytes") o.sampler_interval = std::strtoull(v, nullptr, 10);
    else if (key == "--phase") o.phase = v;
    else if (key == "--run-id") o.run_id = v;
    else if (key == "--device-id") o.device_id = v;
    else {
      error = "unknown option " + key;
      return false;
    }
  }
  const bool known = o.defect == "none" || o.defect == "release_miss" ||
                     o.defect == "queue_growth" || o.defect == "reconnect_leak" ||
                     o.defect == "cache_growth";
  if (!known) {
    error = "unknown defect: " + o.defect;
    return false;
  }
  if (o.width == 0 || o.height == 0 || o.fps == 0 || o.seconds <= 0 || o.defect_every == 0 ||
      o.publisher_hz == 0 || o.snapshot_ms == 0) {
    error = "numeric options must be positive";
    return false;
  }
  if (o.queue_max < 0) o.queue_max = o.defect == "queue_growth" ? 0 : 64;
  return true;
}

struct Result {
  unsigned long long id;
  std::unique_ptr<unsigned char[]> payload;
};

constexpr std::size_t kResultBytes = 512;
constexpr std::size_t kTensorBytes = 64 * 1024;
constexpr std::size_t kSessionBytes = 256 * 1024;
constexpr std::size_t kCacheRecordBytes = 64;

void *volatile g_lost;  // a pointer that is dropped on purpose, so the allocation really leaks

}  // namespace

int main(int argc, char **argv) {
  Options o;
  std::string error;
  if (!parse(argc, argv, o, error)) {
    std::fprintf(stderr, "axis_memlab_virtual_camera: %s\n", error.c_str());
    return 2;
  }

  if (!o.probe_out.empty()) {
    axmem_config config{};
    config.struct_size = sizeof config;
    config.output_path = o.probe_out.c_str();
    config.run_id = o.run_id.c_str();
    config.device_id = o.device_id.c_str();
    config.include_fd_count = 1;
    config.include_smaps_rollup = 1;
    config.max_output_bytes = 32u * 1024u * 1024u;
    if (axmem_init(&config) != AXMEM_OK) {
      std::fprintf(stderr, "axmem_init failed\n");
      return 1;
    }
  }
  if (!o.sampler_out.empty()) {
    axmem_sampler_config sc{};
    sc.struct_size = sizeof sc;
    sc.output_path = o.sampler_out.c_str();
    sc.run_id = o.run_id.c_str();
    sc.device_id = o.device_id.c_str();
    sc.sample_interval_bytes = o.sampler_interval;
    sc.max_output_bytes = 64u * 1024u * 1024u;
    if (axmem_sampler_start(&sc) != AXMEM_OK) {
      std::fprintf(stderr, "axmem_sampler_start failed (is this an AXMEM_SAMPLER build?)\n");
      return 1;
    }
  }

  axis_memlab::ResourceKind frame_kind("frame"), tensor_kind("tensor"), session_kind("session");
  axis_memlab::Counter frames_total("app.frames_total_count"),
      detections_total("app.detections_total_count"),
      reconnects_total("app.reconnects_total_count"),
      dropped_total("app.queue.results_dropped_count");
  axis_memlab::Gauge depth("app.queue.results_depth_count"), queue_bytes("app.queue.results_bytes"),
      cache_entries("app.cache.entries_count");

  std::mutex queue_mutex;
  std::deque<Result> queue;
  std::atomic<bool> stop{false};
  unsigned long long cache_count = 0;
  std::deque<std::unique_ptr<unsigned char[]>> cache;  // the cache_growth defect keeps these

  if (!o.probe_out.empty()) axmem_phase_marker(o.phase.c_str());

  std::thread publisher([&] {
    const auto period = std::chrono::microseconds(1000000 / o.publisher_hz);
    while (!stop.load()) {
      std::this_thread::sleep_for(period);
      Result r{0, nullptr};
      {
        std::lock_guard<std::mutex> lock(queue_mutex);
        if (queue.empty()) continue;
        r = std::move(queue.front());
        queue.pop_front();
        depth.set(queue.size());
        queue_bytes.set(queue.size() * kResultBytes);
      }
    }
  });
  std::thread telemetry([&] {
    while (!stop.load()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(o.snapshot_ms));
      if (!o.probe_out.empty()) axmem_emit_snapshot();
      if (!o.sampler_out.empty()) axmem_sampler_flush();
    }
  });

  const std::size_t frame_bytes = static_cast<std::size_t>(o.width) * o.height * 3 / 2;
  const std::size_t rgb_bytes = static_cast<std::size_t>(o.width) * o.height * 3;
  const auto period = std::chrono::nanoseconds(1000000000ull / o.fps);
  const auto start = Clock::now();
  auto next = start;
  auto last_reconnect = start;
  unsigned long long id = 0, session_id = 0, leaked_frames = 0, leaked_sessions = 0, queued = 0;
  unsigned char *session = nullptr;
  unsigned long long session_live = 0;

  while (std::chrono::duration<double>(Clock::now() - start).count() < o.seconds) {
    ++id;
    // Capture: a frame buffer that is owned until the pipeline is done with it.
    unsigned char *frame = new unsigned char[frame_bytes];
    std::memset(frame, static_cast<int>(id & 0xFF), frame_bytes);
    frame_kind.acquire(id, frame_bytes);

    // Convert: a transient buffer, allocated and released inside this stage.
    unsigned char *rgb = new unsigned char[rgb_bytes];
    std::memset(rgb, 1, rgb_bytes);
    delete[] rgb;

    // Inference stub: a small tensor with a tracked lifetime.
    unsigned char *tensor = new unsigned char[kTensorBytes];
    std::memset(tensor, 2, kTensorBytes);
    tensor_kind.acquire(id, kTensorBytes);

    if (id % 3 == 0) {  // a detection every third frame
      detections_total.add();
      std::unique_ptr<unsigned char[]> payload(new unsigned char[kResultBytes]);
      std::memset(payload.get(), 3, kResultBytes);
      {
        std::lock_guard<std::mutex> lock(queue_mutex);
        if (o.queue_max > 0 && static_cast<long>(queue.size()) >= o.queue_max) {
          dropped_total.add();  // a bounded queue sheds load instead of growing
        } else {
          queue.push_back(Result{id, std::move(payload)});
          ++queued;
          depth.set(queue.size());
          queue_bytes.set(queue.size() * kResultBytes);
        }
      }
      if (o.defect == "cache_growth") {
        cache.emplace_back(new unsigned char[kCacheRecordBytes]);
        cache_entries.set(++cache_count);
      }
    }

    tensor_kind.release(id);
    delete[] tensor;

    if (o.defect == "release_miss" && id % o.defect_every == 0) {
      g_lost = frame;  // the release is skipped on this path: the buffer is leaked
      ++leaked_frames;
    } else {
      frame_kind.release(id);
      delete[] frame;
    }

    frames_total.add();

    if (o.reconnect_seconds > 0 &&
        std::chrono::duration<double>(Clock::now() - last_reconnect).count() >= o.reconnect_seconds) {
      last_reconnect = Clock::now();
      reconnects_total.add();
      // No phase marker here: a marker starts a new analysis segment, and growth *across*
      // reconnects is exactly what the reconnect counter and per-kind totals are for.
      if (session != nullptr) {
        if (o.defect == "reconnect_leak") {
          g_lost = session;  // teardown forgets the old session context
          ++leaked_sessions;
        } else {
          session_kind.release(session_id);
          delete[] session;
          --session_live;
        }
      }
      session = new unsigned char[kSessionBytes];
      std::memset(session, 4, kSessionBytes);
      session_kind.acquire(++session_id, kSessionBytes);
      ++session_live;
    }

    if (o.pacing) {
      next += period;
      std::this_thread::sleep_until(next);
    }
  }

  stop.store(true);
  publisher.join();
  telemetry.join();
  if (session != nullptr && o.defect != "reconnect_leak") {
    session_kind.release(session_id);
    delete[] session;
  }
  if (!o.probe_out.empty()) {
    axmem_emit_snapshot();
    axmem_shutdown();
  }
  if (!o.sampler_out.empty()) {
    axmem_sampler_flush();
    axmem_sampler_stop();
  }

  std::printf(
      "{\"defect\":\"%s\",\"frames\":%llu,\"frame_bytes\":%zu,\"leaked_frames\":%llu,"
      "\"leaked_frame_bytes\":%llu,\"leaked_sessions\":%llu,\"leaked_session_bytes\":%llu,"
      "\"queued_results\":%llu,\"queue_left\":%zu,\"cache_entries\":%llu}\n",
      o.defect.c_str(), id, frame_bytes, leaked_frames,
      static_cast<unsigned long long>(leaked_frames) * frame_bytes, leaked_sessions,
      static_cast<unsigned long long>(leaked_sessions) * kSessionBytes, queued, queue.size(),
      cache_count);
  return 0;
}
