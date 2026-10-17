// Synthetic program with known allocation behaviour, for exercising the sampler end to end.
//
//   usage: axis_memlab_sampler_demo OUTPUT.jsonl [INTERVAL_BYTES] [SEED]
//
// Three call sites with distinct, stable names so that a host-side symbolizer can attribute them:
//   axmem_demo_leak_site       allocates 1 KiB blocks that are never freed      (live)
//   axmem_demo_transient_site  allocates and frees 4 KiB blocks                 (cumulative only)
//   axmem_demo_array_site      allocates arrays of 8 widgets, frees every other (half live)
// The ground truth is printed as JSON on stdout so a test can compare the estimates with it.
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "axis_memlab/sampler.h"

namespace {

constexpr unsigned kLeakCount = 4000;
constexpr unsigned kTransientCount = 2000;
constexpr unsigned kArrayCount = 1000;
constexpr std::size_t kLeakSize = 1024;
constexpr std::size_t kTransientSize = 4096;

struct Widget {
  char payload[64];
};

void *volatile g_leaked[kLeakCount];
Widget *volatile g_arrays[kArrayCount];
volatile char g_sink;

}  // namespace

#if defined(_MSC_VER)
#define AXMEM_DEMO_NOINLINE __declspec(noinline)
#else
#define AXMEM_DEMO_NOINLINE __attribute__((noinline))
#endif

extern "C" AXMEM_DEMO_NOINLINE void axmem_demo_leak_site() {
  for (unsigned i = 0; i < kLeakCount; ++i) {
    char *block = new char[kLeakSize];
    block[0] = static_cast<char>(i);
    g_sink = block[0];
    g_leaked[i] = block;
    if ((i & 255) == 255) axmem_sampler_flush();  // keep the sample ring from overflowing
  }
}

extern "C" AXMEM_DEMO_NOINLINE void axmem_demo_transient_site() {
  for (unsigned i = 0; i < kTransientCount; ++i) {
    char *block = new char[kTransientSize];
    block[0] = static_cast<char>(i);
    g_sink = block[0];
    delete[] block;
    if ((i & 255) == 255) axmem_sampler_flush();
  }
}

extern "C" AXMEM_DEMO_NOINLINE void axmem_demo_array_site() {
  for (unsigned i = 0; i < kArrayCount; ++i) {
    Widget *w = new Widget[8];
    w[0].payload[0] = static_cast<char>(i);
    g_sink = w[0].payload[0];
    g_arrays[i] = w;
    if ((i & 255) == 255) axmem_sampler_flush();
  }
  for (unsigned i = 0; i < kArrayCount; i += 2) {
    delete[] g_arrays[i];
    g_arrays[i] = nullptr;
  }
}

int main(int argc, char **argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s OUTPUT.jsonl [INTERVAL_BYTES] [SEED]\n", argv[0]);
    return 2;
  }
  axmem_sampler_config config{};
  config.struct_size = sizeof config;
  config.output_path = argv[1];
  config.run_id = "00000000-0000-4000-8000-0000000000e7";
  config.device_id = "synthetic-device-001";
  config.sample_interval_bytes = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 4096;
  config.seed = argc > 3 ? std::strtoull(argv[3], nullptr, 10) : 12345;
  config.max_stack_depth = 16;
  config.max_output_bytes = 16u * 1024u * 1024u;
  if (axmem_sampler_start(&config) != AXMEM_OK) {
    std::fprintf(stderr, "axmem_sampler_start failed\n");
    return 1;
  }

  axmem_demo_leak_site();
  axmem_demo_transient_site();
  axmem_demo_array_site();

  axmem_sampler_flush();
  axmem_sampler_stats stats{};
  stats.struct_size = sizeof stats;
  axmem_sampler_get_stats(&stats);
  axmem_sampler_stop();

  const unsigned long long array_size = sizeof(Widget) * 8;  // sizes may include a cookie
  std::printf(
      "{\"leak_live_bytes\":%llu,\"leak_count\":%u,\"transient_cumulative_bytes\":%llu,"
      "\"transient_count\":%u,\"array_block_bytes\":%llu,\"array_live_count\":%u,"
      "\"samples_taken\":%llu,\"dropped_ring_full\":%llu,\"dropped_table_full\":%llu}\n",
      static_cast<unsigned long long>(kLeakCount) * kLeakSize, kLeakCount,
      static_cast<unsigned long long>(kTransientCount) * kTransientSize, kTransientCount,
      array_size, kArrayCount / 2, static_cast<unsigned long long>(stats.samples_taken),
      static_cast<unsigned long long>(stats.dropped_ring_full),
      static_cast<unsigned long long>(stats.dropped_table_full));
  return 0;
}
