// Microbenchmark of the probe hot paths on the machine it runs on. Results describe THIS host
// only; they say nothing about an AXIS camera. Prints CSV: operation,threads,ns_per_op.
//
//   usage: axis_memlab_overhead_bench [OPERATIONS_PER_THREAD]
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <vector>

#include "axis_memlab/probe.hpp"

namespace {

template <typename Fn>
double run(int threads, uint64_t ops, Fn fn) {
  std::atomic<int> ready{0};
  std::atomic<bool> go{false};
  std::vector<std::thread> pool;
  for (int t = 0; t < threads; ++t) {
    pool.emplace_back([&, t] {
      ++ready;
      while (!go.load()) {
      }
      for (uint64_t i = 0; i < ops; ++i) fn(t, i);
    });
  }
  while (ready.load() != threads) {
  }
  const auto begin = std::chrono::steady_clock::now();
  go.store(true);
  for (auto &th : pool) th.join();
  const auto elapsed = std::chrono::steady_clock::now() - begin;
  const double ns = std::chrono::duration<double, std::nano>(elapsed).count();
  return ns / static_cast<double>(ops);  // wall time per operation of one thread
}

void row(const char *name, int threads, double ns) {
  std::printf("%s,%d,%.2f\n", name, threads, ns);
}

}  // namespace

int main(int argc, char **argv) {
  const uint64_t ops = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 2000000;
  if (ops == 0) return 2;
  axis_memlab::Counter counter("app.bench_count");
  axis_memlab::Gauge gauge("app.bench_gauge_count");
  axis_memlab::ResourceKind kind("bench");

  std::printf("operation,threads,ns_per_op\n");
  volatile uint64_t sink = 0;
  for (int threads : {1, 4}) {
    row("empty_loop", threads, run(threads, ops, [&](int, uint64_t i) { sink = i; }));
    row("counter_add_handle", threads, run(threads, ops, [&](int, uint64_t) { counter.add(); }));
    row("counter_add_name", threads,
        run(threads, ops, [&](int, uint64_t) { axmem_counter_add("app.bench_count", 1); }));
    row("gauge_set_handle", threads, run(threads, ops, [&](int, uint64_t i) { gauge.set(i); }));
    row("resource_acquire_release", threads, run(threads, ops, [&](int t, uint64_t i) {
          const uint64_t id = (static_cast<uint64_t>(t) << 40) | i;
          kind.acquire(id, 64);
          kind.release(id);
        }));
  }
  (void)sink;
  return 0;
}
