// Statistical allocation sampler engine and C API (AXMEM_SAMPLER).
//
// Hot-path rules: no heap allocation, no stdio, no symbolization, no demangling. An allocation
// that is not sampled costs a relaxed load, two relaxed adds, and one subtraction. A sampled
// allocation additionally walks a bounded stack and takes a short mutex to queue one record.
// Files are written only by axmem_sampler_flush(), on the caller's thread.

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>

#include "axis_memlab/probe.h"
#include "axis_memlab/sampler.h"
#include "modules.hpp"
#include "sampler_core.hpp"
#include "self_proc.hpp"
#include "stack.hpp"
#include "validate.hpp"

#if defined(_WIN32)
#include <process.h>
#define AXMEM_PID() static_cast<std::uint64_t>(_getpid())
#else
#include <unistd.h>
#define AXMEM_PID() static_cast<std::uint64_t>(getpid())
#endif

#ifndef AXMEM_SAMPLER_RING
#define AXMEM_SAMPLER_RING 1024u  // events buffered between flushes, per buffer (two buffers)
#endif

namespace axmem_internal {
namespace {

constexpr auto kRlx = std::memory_order_relaxed;
constexpr std::size_t kRing = AXMEM_SAMPLER_RING;
constexpr std::size_t kTableMax = 16384;
constexpr unsigned kMaxProbe = 64;
constexpr unsigned kThreadSlots = 64;
constexpr std::uint64_t kDefaultInterval = 512u * 1024u;
constexpr std::uint64_t kDefaultMaxOutput = 4u * 1024u * 1024u;
constexpr std::uint64_t kSummaryReserve = 2048;  // always leave room for the final summary

constexpr std::uintptr_t kEmpty = 0;
constexpr std::uintptr_t kTomb = 1;
constexpr std::uintptr_t kClaimed = 2;

struct Event {
  std::uint8_t type;  // 1 alloc, 2 free
  std::uint8_t kind;
  std::uint16_t depth;
  std::uint32_t thread;
  std::uint64_t id;
  std::uint64_t ts_ns;
  std::uint64_t size;
  std::uint64_t align;
  double weight_count;
  void *frames[kMaxStackDepth];
};

struct Live {
  std::uint64_t id;
  std::uint64_t size;
};

struct ThreadStat {
  std::atomic<std::uint64_t> allocs{0};
  std::atomic<std::uint64_t> bytes{0};
  std::atomic<std::uint64_t> frees{0};
};

struct Tls {
  bool shared_stat = false;  // true when this thread shares the overflow slot with others
  std::int64_t until = 0;
  std::uint64_t rng = 0;
  std::uint32_t epoch = 0;
  std::uint32_t tid = 0;
  ThreadStat *stat = nullptr;
  bool busy = false;
  unsigned depth = 0;
  std::uint64_t ts = 0;
  void *frames[kMaxStackDepth] = {};  // keeps the thread_local constant-initialized
};
thread_local Tls t_tls;

// ---- global state ----------------------------------------------------------------------------
std::atomic<bool> g_active{false};
std::atomic<std::uint32_t> g_epoch{0};
std::atomic<std::uint64_t> g_interval{kDefaultInterval};
std::atomic<std::uint64_t> g_seed{1};
std::atomic<unsigned> g_depth{16};
std::atomic<std::uint64_t> g_next_id{1};
std::atomic<std::uint32_t> g_thread_counter{0};
ThreadStat g_threads[kThreadSlots];

std::atomic<std::uintptr_t> g_keys[kTableMax];
Live g_vals[kTableMax];
std::size_t g_mask = 4095;
std::atomic<std::uint64_t> g_live{0};

std::mutex g_ring_mu;
Event g_rings[2][kRing];
std::size_t g_ring_n[2] = {0, 0};
int g_front = 0;

std::atomic<std::uint64_t> g_samples{0}, g_matched{0}, g_drop_table{0}, g_drop_ring{0},
    g_drop_free{0}, g_drop_cap{0}, g_stack_fail{0}, g_flushes{0}, g_out_bytes{0};

std::mutex g_file_mu;  // serializes start / flush / stop and guards the fields below
std::FILE *g_file = nullptr;
std::uint64_t g_max_bytes = kDefaultMaxOutput;
std::uint64_t g_written = 0;
bool g_capped = false;
std::uint64_t g_modules_fp = 0;
char g_run_id[40];
char g_device_id[72];

std::uint64_t now_ns() noexcept {
  return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                        std::chrono::steady_clock::now().time_since_epoch())
                                        .count());
}

std::uint64_t utc_ns() noexcept {
  return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                        std::chrono::system_clock::now().time_since_epoch())
                                        .count());
}

std::uint64_t splitmix(std::uint64_t x) noexcept {
  x += 0x9E3779B97F4A7C15ull;
  x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
  x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
  return x ^ (x >> 31);
}

std::uint64_t next_random(std::uint64_t &state) noexcept {
  state = splitmix(state);
  return state;
}

// Exponentially distributed byte gap with the configured mean (memoryless, so restarting the
// count after a sampled allocation is exact).
std::int64_t draw_gap(Tls &t) noexcept {
  const double u = (static_cast<double>(next_random(t.rng) >> 11) + 1.0) * (1.0 / 9007199254740993.0);
  double gap = -std::log(u) * static_cast<double>(g_interval.load(kRlx));
  if (gap < 1.0) gap = 1.0;
  if (gap > 4.0e18) gap = 4.0e18;
  return static_cast<std::int64_t>(gap);
}

void ensure_thread(Tls &t) noexcept {
  if (t.stat == nullptr) {
    t.tid = g_thread_counter.fetch_add(1, kRlx) + 1;
    // The first kThreadSlots-1 threads own a slot (single writer: plain load+store, no locked
    // instruction). Later threads share the last slot and must use atomic adds.
    const bool owned = t.tid - 1 < kThreadSlots - 1;
    t.shared_stat = !owned;
    t.stat = &g_threads[owned ? t.tid - 1 : kThreadSlots - 1];
  }
  const std::uint32_t epoch = g_epoch.load(kRlx);
  if (t.epoch != epoch) {
    t.epoch = epoch;
    // Seeded from (seed, thread) only, so a given seed reproduces the same samples on each start.
    t.rng = splitmix(g_seed.load(kRlx) ^ (static_cast<std::uint64_t>(t.tid) * 0xD1B54A32D192ED03ull));
    t.until = draw_gap(t);
  }
}

// Counter update that is exact for both ownership cases.
inline void bump(std::atomic<std::uint64_t> &counter, std::uint64_t delta, bool shared) noexcept {
  if (shared) {
    counter.fetch_add(delta, kRlx);
  } else {
    counter.store(counter.load(kRlx) + delta, kRlx);  // single writer: no locked instruction
  }
}

// ---- live-sample table (lock-free, bounded probing) ---------------------------------------------
std::size_t hash_ptr(std::uintptr_t p) noexcept {
  std::uint64_t x = static_cast<std::uint64_t>(p >> 3) * 0x9E3779B97F4A7C15ull;
  return static_cast<std::size_t>(x >> 29);
}

bool table_insert(std::uintptr_t p, const Live &v) noexcept {
  const std::size_t home = hash_ptr(p) & g_mask;
  for (unsigned i = 0; i < kMaxProbe; ++i) {
    const std::size_t idx = (home + i) & g_mask;
    std::uintptr_t key = g_keys[idx].load(std::memory_order_acquire);
    if (key == kEmpty || key == kTomb || key == p) {
      if (g_keys[idx].compare_exchange_strong(key, kClaimed, std::memory_order_acq_rel)) {
        const bool replaced = key == p;
        g_vals[idx] = v;
        g_keys[idx].store(p, std::memory_order_release);
        if (!replaced) g_live.fetch_add(1, kRlx);
        return true;
      }
    }
  }
  return false;
}

bool table_remove(std::uintptr_t p, Live &out) noexcept {
  const std::size_t home = hash_ptr(p) & g_mask;
  for (unsigned i = 0; i < kMaxProbe; ++i) {
    const std::size_t idx = (home + i) & g_mask;
    std::uintptr_t key = g_keys[idx].load(std::memory_order_acquire);
    if (key == kEmpty) return false;  // an empty slot ends every probe sequence
    if (key == p) {
      const Live copy = g_vals[idx];
      if (g_keys[idx].compare_exchange_strong(key, kTomb, std::memory_order_acq_rel)) {
        out = copy;
        g_live.fetch_sub(1, kRlx);
        return true;
      }
      return false;
    }
  }
  return false;
}

// ---- event ring ----------------------------------------------------------------------------------
bool ring_push(const Event &e) noexcept {
  std::lock_guard<std::mutex> lock(g_ring_mu);
  std::size_t &n = g_ring_n[g_front];
  if (n >= kRing) return false;
  g_rings[g_front][n++] = e;
  return true;
}

const char *kind_name(unsigned kind) noexcept {
  switch (kind) {
    case kKindNew: return "new";
    case kKindNewArray: return "new[]";
    case kKindNewNothrow: return "new_nothrow";
    case kKindNewArrayNothrow: return "new[]_nothrow";
    case kKindNewAligned: return "new_aligned";
    case kKindNewArrayAligned: return "new[]_aligned";
    case kKindNewAlignedNothrow: return "new_aligned_nothrow";
    case kKindNewArrayAlignedNothrow: return "new[]_aligned_nothrow";
    default: return "manual";
  }
}

const char *arch_name() noexcept {
#if defined(__x86_64__) || defined(_M_X64)
  return "x86_64";
#elif defined(__aarch64__) || defined(_M_ARM64)
  return "aarch64";
#elif defined(__arm__) || defined(_M_ARM)
  return "arm";
#elif defined(__i386__) || defined(_M_IX86)
  return "x86";
#else
  return "other";
#endif
}

// Writes one line if it fits under the cap (keeping room for the summary). Caller holds g_file_mu.
bool write_line(const char *line, std::size_t len, bool is_summary) noexcept {
  if (g_file == nullptr) return false;
  if (g_capped && !is_summary) return false;  // the reserve is kept for the closing summary
  const std::uint64_t need = static_cast<std::uint64_t>(len) + 1;
  const std::uint64_t reserve = is_summary ? 0 : kSummaryReserve;
  if (g_written + need + reserve > g_max_bytes) {
    if (!is_summary) g_capped = true;
    return false;
  }
  if (std::fwrite(line, 1, len, g_file) != len || std::fputc('\n', g_file) == EOF) {
    g_capped = true;
    return false;
  }
  g_written += need;
  g_out_bytes.store(g_written, kRlx);
  return true;
}

// Appends a modules array body: [{...},{...}] . Returns the new length.
std::size_t format_modules(char *buf, std::size_t cap, const ModuleInfo *mods, unsigned n) noexcept {
  std::size_t len = 0;
  auto put = [&](const char *fmt, auto... args) {
    if (len + 1 >= cap) return;
    const int w = std::snprintf(buf + len, cap - len, fmt, args...);
    if (w > 0) len += static_cast<std::size_t>(w < static_cast<int>(cap - len) ? w : cap - len - 1);
  };
  put("[");
  for (unsigned i = 0; i < n; ++i) {
    put("%s{\"name\":\"%s\",\"build_id\":\"%s\",\"base\":\"0x%llx\",\"size\":\"0x%llx\"}",
        i ? "," : "", mods[i].name, mods[i].build_id,
        static_cast<unsigned long long>(mods[i].base),
        static_cast<unsigned long long>(mods[i].size));
  }
  put("]");
  return len;
}

// Static: this runs while allocation hooks are live and must not allocate.
ModuleInfo g_mods[kMaxModules];
char g_line[24 * 1024];

void write_modules_record(bool header, unsigned n) noexcept {
  if (header) return;  // the header writes its own copy
  const int w = std::snprintf(g_line, sizeof g_line, "{\"type\":\"modules\",\"ts_mono_ns\":%llu,\"modules\":",
                              static_cast<unsigned long long>(now_ns()));
  std::size_t len = w > 0 ? static_cast<std::size_t>(w) : 0;
  len += format_modules(g_line + len, sizeof g_line - len - 2, g_mods, n);
  g_line[len++] = '}';
  g_line[len] = '\0';
  write_line(g_line, len, false);
}

void write_summary(bool final_record) noexcept {
  SamplerCounters c;
  sampler_counters(c);
  const int w = std::snprintf(
      g_line, sizeof g_line,
      "{\"type\":\"summary\",\"final\":%s,\"ts_mono_ns\":%llu,\"alloc_requests\":%llu,"
      "\"alloc_request_bytes\":%llu,\"free_requests\":%llu,\"samples_taken\":%llu,"
      "\"frees_matched\":%llu,\"live_samples\":%llu,\"dropped_table_full\":%llu,"
      "\"dropped_ring_full\":%llu,\"dropped_free_events\":%llu,\"dropped_output_cap\":%llu,"
      "\"stack_failures\":%llu,\"sample_interval_bytes\":%llu}",
      final_record ? "true" : "false", static_cast<unsigned long long>(now_ns()),
      static_cast<unsigned long long>(c.alloc_requests),
      static_cast<unsigned long long>(c.alloc_request_bytes),
      static_cast<unsigned long long>(c.free_requests),
      static_cast<unsigned long long>(c.samples_taken),
      static_cast<unsigned long long>(c.frees_matched),
      static_cast<unsigned long long>(c.live_samples),
      static_cast<unsigned long long>(c.dropped_table_full),
      static_cast<unsigned long long>(c.dropped_ring_full),
      static_cast<unsigned long long>(c.dropped_free_events),
      static_cast<unsigned long long>(c.dropped_output_cap),
      static_cast<unsigned long long>(c.stack_failures),
      static_cast<unsigned long long>(g_interval.load(kRlx)));
  // Only the closing summary may use the reserved room; periodic ones respect the cap like events.
  if (w > 0) write_line(g_line, static_cast<std::size_t>(w), final_record);
}

// Caller holds g_file_mu and has set the thread-local busy flag.
int flush_locked(bool final_record) noexcept {
  if (g_file == nullptr) return AXMEM_ERR_NOT_INIT;
  const unsigned n_mods = collect_modules(g_mods, kMaxModules);
  const std::uint64_t fp = modules_fingerprint(g_mods, n_mods);
  if (fp != g_modules_fp) {
    write_modules_record(false, n_mods);
    g_modules_fp = fp;
  }
  int old;
  std::size_t count;
  {
    std::lock_guard<std::mutex> lock(g_ring_mu);
    old = g_front;
    count = g_ring_n[old];
    g_front ^= 1;
    g_ring_n[g_front] = 0;
  }
  for (std::size_t i = 0; i < count; ++i) {
    const Event &e = g_rings[old][i];
    int w;
    if (e.type == 1) {
      w = std::snprintf(g_line, sizeof g_line,
                        "{\"type\":\"alloc\",\"id\":%llu,\"ts_mono_ns\":%llu,\"size\":%llu,"
                        "\"align\":%llu,\"kind\":\"%s\",\"thread\":%u,\"weight_count\":%.9g,"
                        "\"stack\":[",
                        static_cast<unsigned long long>(e.id),
                        static_cast<unsigned long long>(e.ts_ns),
                        static_cast<unsigned long long>(e.size),
                        static_cast<unsigned long long>(e.align), kind_name(e.kind), e.thread,
                        e.weight_count);
      std::size_t len = w > 0 ? static_cast<std::size_t>(w) : 0;
      for (unsigned f = 0; f < e.depth && len + 32 < sizeof g_line; ++f) {
        const int a = std::snprintf(g_line + len, sizeof g_line - len, "%s\"0x%llx\"", f ? "," : "",
                                    static_cast<unsigned long long>(
                                        reinterpret_cast<std::uintptr_t>(e.frames[f])));
        if (a > 0) len += static_cast<std::size_t>(a);
      }
      g_line[len++] = ']';
      g_line[len++] = '}';
      g_line[len] = '\0';
      if (!write_line(g_line, len, false)) g_drop_cap.fetch_add(1, kRlx);
    } else {
      w = std::snprintf(g_line, sizeof g_line, "{\"type\":\"free\",\"id\":%llu,\"ts_mono_ns\":%llu}",
                        static_cast<unsigned long long>(e.id),
                        static_cast<unsigned long long>(e.ts_ns));
      if (w > 0 && !write_line(g_line, static_cast<std::size_t>(w), false)) {
        g_drop_cap.fetch_add(1, kRlx);
        g_drop_free.fetch_add(1, kRlx);
      }
    }
  }
  g_ring_n[old] = 0;
  write_summary(final_record);
  std::fflush(g_file);
  g_flushes.fetch_add(1, kRlx);
  return g_capped ? AXMEM_ERR_LIMIT : AXMEM_OK;
}

struct BusyScope {
  Tls &t;
  bool previous;
  explicit BusyScope(Tls &tls) noexcept : t(tls), previous(tls.busy) { t.busy = true; }
  ~BusyScope() { t.busy = previous; }
};

void reset_state() noexcept {
  for (std::size_t i = 0; i < kTableMax; ++i) g_keys[i].store(kEmpty, kRlx);
  g_live.store(0, kRlx);
  g_ring_n[0] = g_ring_n[1] = 0;
  g_front = 0;
  g_samples = g_matched = g_drop_table = g_drop_ring = g_drop_free = g_drop_cap = 0;
  g_stack_fail = g_flushes = g_out_bytes = 0;
  for (ThreadStat &s : g_threads) {
    s.allocs.store(0, kRlx);
    s.bytes.store(0, kRlx);
    s.frees.store(0, kRlx);
  }
}

}  // namespace

// ================================ engine entry points =============================================

double sample_probability(std::uint64_t size, std::uint64_t interval) noexcept {
  if (interval == 0) interval = 1;
  if (size == 0) size = 1;
  const double x = static_cast<double>(size) / static_cast<double>(interval);
  return -std::expm1(-x);
}

bool sampler_active() noexcept { return g_active.load(kRlx); }

bool sampler_begin(std::size_t size) noexcept {
  if (!g_active.load(kRlx)) return false;
  Tls &t = t_tls;
  if (t.busy) return false;  // nested: our own bookkeeping, a flush, or a new_handler callback
  ensure_thread(t);
  bump(t.stat->allocs, 1, t.shared_stat);
  bump(t.stat->bytes, size, t.shared_stat);
  const std::int64_t sz = size > (static_cast<std::size_t>(1) << 60)
                              ? (static_cast<std::int64_t>(1) << 60)
                              : static_cast<std::int64_t>(size);
  t.until -= sz;
  if (t.until >= 0) return false;
  t.until = draw_gap(t);
  t.busy = true;  // until sampler_end / sampler_abort
  return true;
}

void sampler_capture(void *hook_fp, void *hook_ra) noexcept {
  Tls &t = t_tls;
  const unsigned depth = g_depth.load(kRlx);
  t.depth = capture_stack(hook_fp, hook_ra, t.frames, depth < kMaxStackDepth ? depth : kMaxStackDepth);
  t.ts = now_ns();
}

void sampler_abort() noexcept { t_tls.busy = false; }

void sampler_end(void *p, std::size_t size, std::size_t align, AllocKind kind) noexcept {
  Tls &t = t_tls;
  t.busy = false;
  const std::uintptr_t key = reinterpret_cast<std::uintptr_t>(p);
  if (!g_active.load(kRlx) || key <= kClaimed) return;
  const std::uint64_t id = g_next_id.fetch_add(1, kRlx);
  if (!table_insert(key, Live{id, size})) {
    g_drop_table.fetch_add(1, kRlx);
    return;
  }
  Event e;
  e.type = 1;
  e.kind = static_cast<std::uint8_t>(kind);
  e.depth = static_cast<std::uint16_t>(t.depth);
  e.thread = t.tid;
  e.id = id;
  e.ts_ns = t.ts;
  e.size = size;
  e.align = align;
  e.weight_count = 1.0 / sample_probability(size, g_interval.load(kRlx));
  for (unsigned i = 0; i < t.depth; ++i) e.frames[i] = t.frames[i];
  if (t.depth == 0) g_stack_fail.fetch_add(1, kRlx);
  if (!ring_push(e)) {
    Live ignored;
    table_remove(key, ignored);  // keep "tracked" and "recorded" identical
    g_drop_ring.fetch_add(1, kRlx);
    return;
  }
  g_samples.fetch_add(1, kRlx);
}

void sampler_free(void *p) noexcept {
  if (!g_active.load(kRlx)) return;
  Tls &t = t_tls;
  if (t.busy) return;  // a flush or hook on this thread: it never frees tracked memory
  ensure_thread(t);
  bump(t.stat->frees, 1, t.shared_stat);
  if (g_live.load(kRlx) == 0 || p == nullptr) return;
  Live v;
  if (!table_remove(reinterpret_cast<std::uintptr_t>(p), v)) return;
  g_matched.fetch_add(1, kRlx);
  Event e;
  std::memset(&e, 0, sizeof e);
  e.type = 2;
  e.id = v.id;
  e.ts_ns = now_ns();
  if (!ring_push(e)) g_drop_free.fetch_add(1, kRlx);
}

void sampler_counters(SamplerCounters &out) noexcept {
  std::memset(&out, 0, sizeof out);
  for (const ThreadStat &s : g_threads) {
    out.alloc_requests += s.allocs.load(kRlx);
    out.alloc_request_bytes += s.bytes.load(kRlx);
    out.free_requests += s.frees.load(kRlx);
  }
  out.samples_taken = g_samples.load(kRlx);
  out.frees_matched = g_matched.load(kRlx);
  out.live_samples = g_live.load(kRlx);
  out.dropped_table_full = g_drop_table.load(kRlx);
  out.dropped_ring_full = g_drop_ring.load(kRlx);
  out.dropped_free_events = g_drop_free.load(kRlx);
  out.dropped_output_cap = g_drop_cap.load(kRlx);
  out.stack_failures = g_stack_fail.load(kRlx);
  out.flushes = g_flushes.load(kRlx);
  out.output_bytes = g_out_bytes.load(kRlx);
}

}  // namespace axmem_internal

// ================================ public C API ====================================================

using namespace axmem_internal;

extern "C" {

int axmem_sampler_start(const axmem_sampler_config *config) {
  if (config == nullptr || config->struct_size != sizeof(axmem_sampler_config) ||
      config->output_path == nullptr || config->output_path[0] == '\0' ||
      !valid_uuid_text(config->run_id) || !valid_device_label(config->device_id)) {
    return AXMEM_ERR_INVALID;
  }
  const std::uint64_t interval = config->sample_interval_bytes ? config->sample_interval_bytes : kDefaultInterval;
  const unsigned depth = config->max_stack_depth ? config->max_stack_depth : 16;
  std::size_t cap = config->max_live_samples ? config->max_live_samples : 4096;
  if (depth > kMaxStackDepth || cap > kTableMax || (cap & (cap - 1)) != 0 || cap < 16 ||
      interval > (static_cast<std::uint64_t>(1) << 60)) {
    return AXMEM_ERR_INVALID;
  }
  Tls &t = t_tls;
  BusyScope busy(t);
  std::lock_guard<std::mutex> lock(g_file_mu);
  if (g_file != nullptr) return AXMEM_ERR_ALREADY;
  std::FILE *file = std::fopen(config->output_path, "ab");
  if (file == nullptr) return AXMEM_ERR_IO;

  g_active.store(false, kRlx);
  reset_state();
  g_file = file;
  g_written = 0;
  g_capped = false;
  g_max_bytes = config->max_output_bytes ? config->max_output_bytes : kDefaultMaxOutput;
  g_mask = cap - 1;
  g_interval.store(interval, kRlx);
  g_depth.store(depth, kRlx);
  g_next_id.store(1, kRlx);
  std::snprintf(g_run_id, sizeof g_run_id, "%s", config->run_id);
  std::snprintf(g_device_id, sizeof g_device_id, "%s", config->device_id);
  std::uint64_t seed = config->seed;
  if (seed == 0) seed = splitmix(now_ns() ^ reinterpret_cast<std::uintptr_t>(&g_seed));
  g_seed.store(seed, kRlx);

  const unsigned n_mods = collect_modules(g_mods, kMaxModules);
  g_modules_fp = modules_fingerprint(g_mods, n_mods);
  int w = std::snprintf(
      g_line, sizeof g_line,
      "{\"schema\":\"alloc-samples-v1\",\"type\":\"header\",\"run_id\":\"%s\",\"device_id\":\"%s\","
      "\"pid\":%llu,",
      g_run_id, g_device_id, static_cast<unsigned long long>(AXMEM_PID()));
  std::size_t len = w > 0 ? static_cast<std::size_t>(w) : 0;
  std::string stat;
  if (read_small_file("/proc/self/stat", 4096, stat)) {
    const auto ticks = parse_stat_start_ticks(stat);
    if (ticks) len += static_cast<std::size_t>(std::snprintf(g_line + len, sizeof g_line - len,
                                                              "\"process_start_ticks\":%llu,",
                                                              static_cast<unsigned long long>(*ticks)));
  }
  if (const auto boot = read_boot_id()) {
    len += static_cast<std::size_t>(std::snprintf(g_line + len, sizeof g_line - len,
                                                  "\"boot_id\":\"%s\",", boot->c_str()));
  }
  len += static_cast<std::size_t>(std::snprintf(
      g_line + len, sizeof g_line - len,
      "\"ts_utc_ns\":%llu,\"ts_mono_ns\":%llu,\"sample_interval_bytes\":%llu,"
      "\"max_stack_depth\":%u,\"pointer_bits\":%u,\"arch\":\"%s\",\"unwinder\":\"%s\",\"modules\":",
      static_cast<unsigned long long>(utc_ns()), static_cast<unsigned long long>(now_ns()),
      static_cast<unsigned long long>(interval), depth,
      static_cast<unsigned>(sizeof(void *) * 8), arch_name(), unwinder_name()));
  len += format_modules(g_line + len, sizeof g_line - len - 2, g_mods, n_mods);
  g_line[len++] = '}';
  g_line[len] = '\0';
  if (!write_line(g_line, len, false)) {
    std::fclose(g_file);
    g_file = nullptr;
    return AXMEM_ERR_LIMIT;
  }
  std::fflush(g_file);
  g_epoch.fetch_add(1, kRlx);
  g_active.store(true, std::memory_order_release);
  return AXMEM_OK;
}

int axmem_sampler_flush(void) {
  Tls &t = t_tls;
  BusyScope busy(t);
  std::lock_guard<std::mutex> lock(g_file_mu);
  return flush_locked(false);
}

void axmem_sampler_stop(void) {
  Tls &t = t_tls;
  BusyScope busy(t);
  std::lock_guard<std::mutex> lock(g_file_mu);
  if (g_file == nullptr) return;
  g_active.store(false, std::memory_order_release);
  flush_locked(true);
  std::fclose(g_file);
  g_file = nullptr;
  for (std::size_t i = 0; i < kTableMax; ++i) g_keys[i].store(kEmpty, kRlx);
  g_live.store(0, kRlx);
}

uint32_t axmem_sampler_active(void) { return sampler_active() ? 1u : 0u; }

int axmem_sampler_get_stats(axmem_sampler_stats *out) {
  if (out == nullptr || out->struct_size != sizeof(axmem_sampler_stats)) return AXMEM_ERR_INVALID;
  SamplerCounters c;
  sampler_counters(c);
  out->alloc_requests = c.alloc_requests;
  out->alloc_request_bytes = c.alloc_request_bytes;
  out->free_requests = c.free_requests;
  out->samples_taken = c.samples_taken;
  out->frees_matched = c.frees_matched;
  out->live_samples = c.live_samples;
  out->dropped_table_full = c.dropped_table_full;
  out->dropped_ring_full = c.dropped_ring_full;
  out->dropped_free_events = c.dropped_free_events;
  out->dropped_output_cap = c.dropped_output_cap;
  out->stack_failures = c.stack_failures;
  out->flushes = c.flushes;
  out->output_bytes = c.output_bytes;
  return AXMEM_OK;
}

void axmem_sampler_record_alloc(const void *p, size_t size, size_t align) {
  if (!sampler_begin(size)) return;
#if defined(__GNUC__)
  sampler_capture(__builtin_frame_address(0), __builtin_return_address(0));
#else
  sampler_capture(nullptr, nullptr);
#endif
  sampler_end(const_cast<void *>(p), size, align, kKindManual);
}

void axmem_sampler_record_free(const void *p) { sampler_free(const_cast<void *>(p)); }

}  // extern "C"
