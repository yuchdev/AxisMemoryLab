// Many threads allocating and freeing while another thread flushes: no crash, no deadlock, and
// the file stays internally consistent (every free refers to a recorded sample, the summary's
// live count equals recorded allocs minus recorded frees once dropped free events are counted).
#include <atomic>
#include <chrono>
#include <cstdint>
#include <set>
#include <thread>
#include <vector>

#include "check.hpp"
#include "sampler_util.hpp"

namespace {

volatile char g_sink;

void worker(unsigned seed, int rounds, std::atomic<std::uint64_t> &requests) {
  std::uint64_t state = seed * 2654435761u + 1;
  std::vector<char *> held;  // grows once, before the hot loop is representative
  held.reserve(64);
  for (int r = 0; r < rounds; ++r) {
    state = state * 6364136223846793005ull + 1442695040888963407ull;
    const std::size_t size = 16 + (state >> 40) % 4096;
    char *p = new char[size];
    p[0] = static_cast<char>(r);
    g_sink = p[0];
    requests.fetch_add(1, std::memory_order_relaxed);
    if (held.size() < 64 && (state & 3) == 0) {
      held.push_back(p);  // some allocations outlive the iteration and are freed by this thread
    } else {
      delete[] p;
    }
    if (held.size() == 64) {
      for (char *q : held) delete[] q;
      held.clear();
    }
  }
  for (char *q : held) delete[] q;
}

}  // namespace

int main() {
  const std::string path = temp_path("new_hook_threads");
  auto config = sampler_config(path.c_str(), 65536, 777);
  config.max_live_samples = 16384;
  CHECK(axmem_sampler_start(&config) == AXMEM_OK);

  std::atomic<std::uint64_t> requests{0};
  std::atomic<bool> stop{false};
  std::thread flusher([&] {
    while (!stop.load()) {
      axmem_sampler_flush();
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
  });
  std::vector<std::thread> threads;
  for (unsigned t = 0; t < 8; ++t) threads.emplace_back(worker, t + 1, 20000, std::ref(requests));
  for (auto &th : threads) th.join();
  stop.store(true);
  flusher.join();

  axmem_sampler_stats stats{};
  stats.struct_size = sizeof stats;
  CHECK(axmem_sampler_get_stats(&stats) == AXMEM_OK);
  CHECK(stats.alloc_requests >= requests.load());  // the std::thread machinery adds a few
  CHECK(stats.free_requests >= requests.load() - 100);
  CHECK(stats.samples_taken > 100);
  axmem_sampler_stop();

  ParsedSamples parsed = parse_samples(path);
  CHECK(parsed.all_lines_end_cleanly && parsed.final_summary);
  std::set<unsigned long long> ids;
  for (const AllocRec &a : parsed.allocs) CHECK(ids.insert(a.id).second);  // unique ids
  std::set<unsigned long long> freed;
  for (unsigned long long id : parsed.frees) {
    CHECK(ids.count(id) == 1);       // a free always refers to a recorded sample
    CHECK(freed.insert(id).second);  // and is reported once
  }
  const unsigned long long recorded_live = parsed.allocs.size() - parsed.frees.size();
  const unsigned long long dropped_free = parsed.summary["dropped_free_events"];
  CHECK(parsed.summary["live_samples"] + dropped_free == recorded_live);
  CHECK(parsed.summary["samples_taken"] == parsed.allocs.size());
  return 0;
}
