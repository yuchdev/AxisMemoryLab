// Cost of the sampler on a new/delete loop, on THIS machine only.
//
//   usage: axis_memlab_sampler_bench [ITERATIONS]
//   prints CSV: variant,size_bytes,ns_per_pair
//
// Built twice: `axis_memlab_alloc_baseline_bench` (plain operator new, no hook) and
// `axis_memlab_sampler_bench` (hook linked; measured with the sampler stopped and running at
// several intervals). Numbers describe a workstation, not an AXIS camera.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

#ifndef AXMEM_BENCH_BASELINE
#include "axis_memlab/sampler.h"
#endif

namespace {

volatile char g_sink;

// `interval` == 0 means "no sampler running": no flushing. Otherwise iterations are timed in
// chunks sized so that the sample ring cannot overflow, and the flush between chunks is not timed.
double measure(std::size_t size, std::uint64_t iterations, std::uint64_t interval) {
  std::uint64_t chunk = 20000;
  if (interval != 0) {
    const double p = -std::expm1(-static_cast<double>(size) / static_cast<double>(interval));
    const double safe = 300.0 / (p * 2.0);  // each sample can add an alloc and a free event
    chunk = safe < 512.0 ? 512 : (safe > 20000.0 ? 20000 : static_cast<std::uint64_t>(safe));
  }
  double total_ns = 0;
  std::uint64_t done = 0;
  while (done < iterations) {
    const std::uint64_t n = iterations - done < chunk ? iterations - done : chunk;
    const auto begin = std::chrono::steady_clock::now();
    for (std::uint64_t i = 0; i < n; ++i) {
      char *p = new char[size];
      p[0] = static_cast<char>(i);
      g_sink = p[0];
      delete[] p;
    }
    const auto end = std::chrono::steady_clock::now();
    total_ns += std::chrono::duration<double, std::nano>(end - begin).count();
    done += n;
#ifndef AXMEM_BENCH_BASELINE
    if (interval != 0) axmem_sampler_flush();  // outside the timed region
#endif
  }
  return total_ns / static_cast<double>(iterations);
}

}  // namespace

int main(int argc, char **argv) {
  const std::uint64_t iterations = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 1000000;
  if (iterations == 0) return 2;
  std::printf("variant,size_bytes,ns_per_pair\n");
  const std::size_t sizes[] = {32, 256, 4096};

#ifdef AXMEM_BENCH_BASELINE
  for (std::size_t size : sizes) std::printf("no_hook,%zu,%.1f\n", size, measure(size, iterations, 0));
#else
  for (std::size_t size : sizes) {
    std::printf("hook_sampler_stopped,%zu,%.1f\n", size, measure(size, iterations, 0));
  }
  const std::uint64_t intervals[] = {524288, 65536, 4096};
  for (std::uint64_t interval : intervals) {
    axmem_sampler_config config{};
    config.struct_size = sizeof config;
    config.output_path = "sampler_bench_output.jsonl";
    config.run_id = "00000000-0000-4000-8000-0000000000e8";
    config.device_id = "synthetic-device-001";
    config.sample_interval_bytes = interval;
    config.seed = 7;
    config.max_output_bytes = 64u * 1024u * 1024u;
    std::remove(config.output_path);
    if (axmem_sampler_start(&config) != AXMEM_OK) return 1;
    for (std::size_t size : sizes) {
      std::printf("sampler_interval_%llu,%zu,%.1f\n", static_cast<unsigned long long>(interval),
                  size, measure(size, iterations, interval));
    }
    axmem_sampler_stop();
  }
  std::remove("sampler_bench_output.jsonl");
#endif
  return 0;
}
