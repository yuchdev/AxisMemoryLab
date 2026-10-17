// Enabled implementation of the probe API (COUNTERS and LEDGER modes). SDK-free: standard C++17
// plus optional /proc and glibc facilities. No threads, no network, no allocation on the
// counter/gauge/resource hot paths (LEDGER mode additionally takes one mutex).

#include "axis_memlab/probe.h"

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

#include "self_proc.hpp"

#if defined(_WIN32)
#include <process.h>
#define AXMEM_GETPID() static_cast<uint64_t>(_getpid())
#else
#include <unistd.h>
#define AXMEM_GETPID() static_cast<uint64_t>(getpid())
#endif

#if defined(__GLIBC__) && (__GLIBC__ > 2 || (__GLIBC__ == 2 && __GLIBC_MINOR__ >= 33))
#include <malloc.h>
#define AXMEM_HAVE_MALLINFO2 1
#else
#define AXMEM_HAVE_MALLINFO2 0
#endif

#ifndef AXMEM_LEDGER_CAPACITY
#define AXMEM_LEDGER_CAPACITY 4096u
#endif

namespace {

constexpr std::size_t kMaxMetrics = 128;
constexpr std::size_t kMaxNameLen = 64;
constexpr std::size_t kMaxKinds = 16;
constexpr std::size_t kMaxKindNameLen = 24;
constexpr std::size_t kOldestLive = 8;
constexpr uint64_t kDefaultMaxOutput = 4u * 1024u * 1024u;
constexpr uint32_t kLedgerCapacity = AXMEM_LEDGER_CAPACITY;
static_assert((kLedgerCapacity & (kLedgerCapacity - 1)) == 0, "ledger capacity: power of two");

constexpr bool kLedgerMode = AXMEM_MODE_LEDGER_ == 1;

constexpr auto kRlx = std::memory_order_relaxed;

// ---- statistics about the probe itself -------------------------------------------------------
std::atomic<uint64_t> g_registration_rejected{0};
std::atomic<uint64_t> g_rejected_calls{0};
std::atomic<uint64_t> g_snapshots_emitted{0};
std::atomic<uint64_t> g_snapshots_dropped{0};
std::atomic<uint64_t> g_last_snapshot_ns{0};
std::atomic<uint64_t> g_output_bytes{0};

// ---- counter / gauge registry (lock-free) ----------------------------------------------------
struct Slot {
  std::atomic<uint32_t> state{0};  // 0 empty, 1 being initialised, 2 ready
  bool is_gauge = false;
  char name[kMaxNameLen + 1] = {0};
  std::atomic<uint64_t> value{0};
};
Slot g_slots[kMaxMetrics];

uint64_t fnv1a(const char *text) {
  uint64_t hash = 1469598103934665603ull;
  for (; *text != '\0'; ++text) {
    hash ^= static_cast<unsigned char>(*text);
    hash *= 1099511628211ull;
  }
  return hash;
}

bool name_char_ok(char c, bool allow_dot) {
  return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || (allow_dot && c == '.');
}

bool valid_metric_name(const char *name) {
  if (name == nullptr || std::strncmp(name, "app.", 4) != 0) return false;
  std::size_t length = std::strlen(name);
  if (length <= 4 || length > kMaxNameLen) return false;
  for (std::size_t i = 4; i < length; ++i) {
    if (!name_char_ok(name[i], true)) return false;
  }
  return true;
}

bool valid_kind_name(const char *name) {
  if (name == nullptr) return false;
  std::size_t length = std::strlen(name);
  if (length == 0 || length > kMaxKindNameLen) return false;
  for (std::size_t i = 0; i < length; ++i) {
    if (!name_char_ok(name[i], false)) return false;
  }
  return true;
}

uint32_t register_metric(const char *name, bool gauge) {
  if (!valid_metric_name(name)) {
    g_registration_rejected.fetch_add(1, kRlx);
    return AXMEM_INVALID_HANDLE;
  }
  const std::size_t start = static_cast<std::size_t>(fnv1a(name) % kMaxMetrics);
  for (std::size_t probe = 0; probe < kMaxMetrics; ++probe) {
    const std::size_t index = (start + probe) % kMaxMetrics;
    Slot &slot = g_slots[index];
    uint32_t state = slot.state.load(std::memory_order_acquire);
    if (state == 0) {
      uint32_t expected = 0;
      if (slot.state.compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) {
        std::strncpy(slot.name, name, kMaxNameLen);
        slot.is_gauge = gauge;
        slot.state.store(2, std::memory_order_release);
        return static_cast<uint32_t>(index);
      }
      state = expected;
    }
    for (int spins = 0; state == 1 && spins < 1000000; ++spins) {
      std::this_thread::yield();
      state = slot.state.load(std::memory_order_acquire);
    }
    if (state != 2) continue;
    if (std::strcmp(slot.name, name) == 0) {
      if (slot.is_gauge == gauge) return static_cast<uint32_t>(index);
      g_registration_rejected.fetch_add(1, kRlx);  // same name, other kind
      return AXMEM_INVALID_HANDLE;
    }
  }
  g_registration_rejected.fetch_add(1, kRlx);  // table full
  return AXMEM_INVALID_HANDLE;
}

// ---- resource kinds and per-kind totals ------------------------------------------------------
struct Kind {
  char name[kMaxKindNameLen + 1] = {0};
  std::atomic<uint64_t> acquired{0};
  std::atomic<uint64_t> released{0};
  // LEDGER mode only (guarded by g_ledger_mutex when written):
  uint64_t live_count = 0;
  uint64_t live_bytes = 0;
  uint64_t high_watermark_bytes = 0;
};
Kind g_kinds[kMaxKinds];
std::atomic<uint32_t> g_kind_count{0};
std::mutex g_kind_mutex;

// ---- identity ledger (LEDGER mode) -----------------------------------------------------------
struct Entry {
  uint64_t id = 0;
  uint64_t bytes = 0;
  uint64_t seq = 0;
  int64_t acquired_mono_ns = 0;
  uint32_t kind = 0;
  bool live = false;
};
std::mutex g_ledger_mutex;
Entry g_ledger[kLedgerMode ? kLedgerCapacity : 1];
uint32_t g_ledger_live = 0;
uint64_t g_ledger_seq = 0;
uint64_t g_ledger_dropped = 0;
uint64_t g_ledger_duplicates = 0;
uint64_t g_ledger_unmatched = 0;

uint32_t ledger_hash(uint64_t id, uint32_t kind) {
  uint64_t mixed = (id ^ (static_cast<uint64_t>(kind) << 56)) * 0x9E3779B97F4A7C15ull;
  return static_cast<uint32_t>(mixed >> 40) & (kLedgerCapacity - 1);
}

int64_t mono_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

int64_t utc_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

// Returns the slot index holding (id, kind), or kLedgerCapacity if absent. Caller holds the lock.
uint32_t ledger_find(uint64_t id, uint32_t kind) {
  uint32_t index = ledger_hash(id, kind);
  for (uint32_t step = 0; step < kLedgerCapacity; ++step) {
    const Entry &entry = g_ledger[index];
    if (!entry.live) return kLedgerCapacity;
    if (entry.id == id && entry.kind == kind) return index;
    index = (index + 1) & (kLedgerCapacity - 1);
  }
  return kLedgerCapacity;
}

// Linear-probing deletion by backward shift, so no tombstones accumulate. The hole is always
// marked empty before scanning, so the walk terminates even when the table is completely full.
void ledger_erase(uint32_t hole) {
  g_ledger[hole] = Entry();
  uint32_t next = hole;
  for (;;) {
    next = (next + 1) & (kLedgerCapacity - 1);
    const Entry candidate = g_ledger[next];
    if (!candidate.live) break;
    const uint32_t ideal = ledger_hash(candidate.id, candidate.kind);
    // The entry may move into the hole unless its ideal slot lies cyclically in (hole, next].
    const bool movable = (hole <= next) ? (ideal <= hole || ideal > next)
                                        : (ideal <= hole && ideal > next);
    if (movable) {
      g_ledger[hole] = candidate;
      g_ledger[next] = Entry();
      hole = next;
    }
  }
}

// ---- sink ------------------------------------------------------------------------------------
struct Sink {
  std::FILE *file = nullptr;
  std::string run_id;
  std::string device_id;
  uint64_t pid = 0;
  std::optional<uint64_t> start_ticks;
  std::optional<std::string> boot_id;
  uint64_t max_bytes = kDefaultMaxOutput;
  uint64_t written = 0;
  bool allocator_stats = false;
  bool smaps_rollup = false;
  bool fd_count = false;
};
std::mutex g_sink_mutex;
Sink g_sink;

bool valid_uuid(const char *text) {
  if (text == nullptr || std::strlen(text) != 36) return false;
  for (int i = 0; i < 36; ++i) {
    const char c = text[i];
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (c != '-') return false;
    } else if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) {
      return false;
    }
  }
  return true;
}

bool valid_device_id(const char *text) {
  if (text == nullptr) return false;
  const std::size_t length = std::strlen(text);
  if (length == 0 || length > 64) return false;
  for (std::size_t i = 0; i < length; ++i) {
    const char c = text[i];
    const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                    c == '.' || c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

bool valid_phase(const char *text) {
  if (text == nullptr) return false;
  const std::size_t length = std::strlen(text);
  if (length == 0 || length > 48) return false;
  for (std::size_t i = 0; i < length; ++i) {
    const char c = text[i];
    const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                    c == '.' || c == '_' || c == '-' || c == ':';
    if (!ok) return false;
  }
  return true;
}

// ---- JSON assembly (off the hot path; names are validated so no escaping is needed) -----------
struct MetricWriter {
  std::string out;
  bool first = true;

  void key(const std::string &name) {
    if (!first) out += ',';
    first = false;
    out += '"';
    out += name;
    out += "\":";
  }
  void value(const std::string &name, uint64_t v, const char *unit, const char *source) {
    key(name);
    out += "{\"value\":" + std::to_string(v) + ",\"unit\":\"" + unit + "\",\"source\":\"" +
           source + "\"}";
  }
  void unavailable(const std::string &name, const char *reason) {
    key(name);
    out += "{\"available\":false,\"reason\":\"";
    out += reason;
    out += "\"}";
  }
  void optional_bytes(const std::string &name, const std::optional<uint64_t> &v, const char *unit,
                      const char *source) {
    if (v) {
      value(name, *v, unit, source);
    } else {
      unavailable(name, "field not present in /proc/self/status or file unreadable");
    }
  }
};

const char *unit_for(const char *name) {
  const std::size_t length = std::strlen(name);
  auto ends = [&](const char *suffix) {
    const std::size_t n = std::strlen(suffix);
    return length >= n && std::strcmp(name + length - n, suffix) == 0;
  };
  if (ends("_bytes")) return "bytes";
  if (ends("_ns")) return "nanoseconds";
  return "count";
}

std::string identity_json(const Sink &sink) {
  std::string out = "{\"device_id\":\"" + sink.device_id + "\",\"pid\":" + std::to_string(sink.pid);
  if (sink.start_ticks) out += ",\"process_start_ticks\":" + std::to_string(*sink.start_ticks);
  if (sink.boot_id) out += ",\"boot_id\":\"" + *sink.boot_id + "\"";
  out += '}';
  return out;
}

std::string envelope(const Sink &sink, const char *type, const std::string &metrics,
                     const std::string &annotations) {
  std::string line = "{\"schema_version\":1,\"record_type\":\"";
  line += type;
  line += "\",\"run_id\":\"" + sink.run_id + "\",\"producer\":\"axmem-probe\",\"ts_utc_ns\":" +
          std::to_string(utc_ns()) + ",\"ts_mono_ns\":" + std::to_string(mono_ns()) +
          ",\"identity\":" + identity_json(sink) + ",\"metrics\":{" + metrics + "}";
  if (!annotations.empty()) line += ",\"annotations\":" + annotations;
  line += "}";
  return line;
}

// Caller holds g_sink_mutex.
int write_line(Sink &sink, const std::string &line) {
  if (sink.file == nullptr) return AXMEM_ERR_NOT_INIT;
  const uint64_t needed = static_cast<uint64_t>(line.size()) + 1;
  if (sink.written + needed > sink.max_bytes) return AXMEM_ERR_LIMIT;
  if (std::fwrite(line.data(), 1, line.size(), sink.file) != line.size() ||
      std::fputc('\n', sink.file) == EOF || std::fflush(sink.file) != 0) {
    return AXMEM_ERR_IO;
  }
  sink.written += needed;
  g_output_bytes.store(sink.written, kRlx);
  return AXMEM_OK;
}

void append_process_metrics(MetricWriter &w, const Sink &sink) {
  std::string text;
  axmem_internal::StatusFields f;
  if (axmem_internal::read_small_file("/proc/self/status", 16384, text)) {
    f = axmem_internal::parse_status(text);
  }
  const char *src = "procfs:/proc/self/status";
  w.optional_bytes("process.rss_bytes", f.vm_rss_bytes, "bytes", src);
  w.optional_bytes("process.rss_anon_bytes", f.rss_anon_bytes, "bytes", src);
  w.optional_bytes("process.rss_file_bytes", f.rss_file_bytes, "bytes", src);
  w.optional_bytes("process.rss_shmem_bytes", f.rss_shmem_bytes, "bytes", src);
  w.optional_bytes("process.vm_swap_bytes", f.vm_swap_bytes, "bytes", src);
  w.optional_bytes("process.threads_count", f.threads, "count", src);

  if (sink.smaps_rollup) {
    axmem_internal::SmapsRollupFields r;
    const char *rsrc = "procfs:/proc/self/smaps_rollup";
    if (axmem_internal::read_small_file("/proc/self/smaps_rollup", 16384, text)) {
      r = axmem_internal::parse_smaps_rollup(text);
    }
    auto put = [&](const char *name, const std::optional<uint64_t> &v) {
      if (v) {
        w.value(name, *v, "bytes", rsrc);
      } else {
        w.unavailable(name, "smaps_rollup missing, unreadable, or field not present");
      }
    };
    put("process.pss_bytes", r.pss_bytes);
    put("process.private_clean_bytes", r.private_clean_bytes);
    put("process.private_dirty_bytes", r.private_dirty_bytes);
    put("process.anonymous_bytes", r.anonymous_bytes);
    put("process.swap_bytes", r.swap_bytes);
  }
  if (sink.fd_count) {
    const std::optional<uint64_t> fds = axmem_internal::count_open_fds();
    if (fds) {
      w.value("process.fd_count", *fds, "count", "procfs:/proc/self/fd");
    } else {
      w.unavailable("process.fd_count", "/proc/self/fd could not be listed");
    }
  }
}

void append_allocator_metrics(MetricWriter &w) {
#if AXMEM_HAVE_MALLINFO2
  const struct mallinfo2 info = mallinfo2();  // takes the arena lock: development use only
  const char *src = "glibc:mallinfo2";
  w.value("app.allocator.arena_bytes", info.arena, "bytes", src);
  w.value("app.allocator.in_use_bytes", info.uordblks, "bytes", src);
  w.value("app.allocator.free_bytes", info.fordblks, "bytes", src);
  w.value("app.allocator.mmapped_bytes", info.hblkhd, "bytes", src);
#else
  for (const char *name : {"app.allocator.arena_bytes", "app.allocator.in_use_bytes",
                           "app.allocator.free_bytes", "app.allocator.mmapped_bytes"}) {
    w.unavailable(name, "mallinfo2 requires glibc 2.33 or newer");
  }
#endif
}

void append_kind_metrics(MetricWriter &w, std::string &annotations) {
  const uint32_t kinds = g_kind_count.load(std::memory_order_acquire);
  const std::string base = "app.resource.";
  const char *src = "axmem_resource";
  if (!kLedgerMode) {
    for (uint32_t i = 0; i < kinds; ++i) {
      const std::string prefix = base + g_kinds[i].name;
      const uint64_t acquired = g_kinds[i].acquired.load(kRlx);
      const uint64_t released = g_kinds[i].released.load(kRlx);
      w.value(prefix + ".acquired_total_count", acquired, "count", src);
      w.value(prefix + ".released_total_count", released, "count", src);
      w.value(prefix + ".in_flight_count", acquired > released ? acquired - released : 0, "count",
              src);
      w.unavailable(prefix + ".in_flight_bytes", "byte accounting needs LEDGER mode");
    }
    return;
  }
  std::lock_guard<std::mutex> lock(g_ledger_mutex);
  for (uint32_t i = 0; i < kinds; ++i) {
    const std::string prefix = base + g_kinds[i].name;
    w.value(prefix + ".acquired_total_count", g_kinds[i].acquired.load(kRlx), "count", src);
    w.value(prefix + ".released_total_count", g_kinds[i].released.load(kRlx), "count", src);
    w.value(prefix + ".in_flight_count", g_kinds[i].live_count, "count", src);
    w.value(prefix + ".in_flight_bytes", g_kinds[i].live_bytes, "bytes", src);
    w.value(prefix + ".high_watermark_bytes", g_kinds[i].high_watermark_bytes, "bytes", src);
  }
  w.value("app.ledger.capacity_count", kLedgerCapacity, "count", "axmem_ledger");
  w.value("app.ledger.live_count", g_ledger_live, "count", "axmem_ledger");
  w.value("app.ledger.events_dropped_count", g_ledger_dropped, "count", "axmem_ledger");
  w.value("app.ledger.duplicate_acquire_count", g_ledger_duplicates, "count", "axmem_ledger");
  w.value("app.ledger.unmatched_release_count", g_ledger_unmatched, "count", "axmem_ledger");
  w.value("app.ledger.degraded", g_ledger_dropped > 0 ? 1 : 0, "count", "axmem_ledger");

  // Oldest live entries by acquisition sequence.
  const Entry *oldest[kOldestLive] = {nullptr};
  std::size_t have = 0;
  for (uint32_t i = 0; i < kLedgerCapacity; ++i) {
    const Entry &entry = g_ledger[i];
    if (!entry.live) continue;
    std::size_t pos = have;
    while (pos > 0 && oldest[pos - 1]->seq > entry.seq) --pos;
    if (pos >= kOldestLive) continue;
    const std::size_t last = have < kOldestLive ? have : kOldestLive - 1;
    for (std::size_t j = last; j > pos; --j) oldest[j] = oldest[j - 1];
    oldest[pos] = &entry;
    if (have < kOldestLive) ++have;
  }
  const int64_t now = mono_ns();
  annotations = "{\"ledger\":{\"capacity\":" + std::to_string(kLedgerCapacity) +
                ",\"degraded\":" + (g_ledger_dropped > 0 ? "true" : "false") + ",\"oldest_live\":[";
  for (std::size_t i = 0; i < have; ++i) {
    if (i) annotations += ',';
    annotations += "{\"kind\":\"" + std::string(g_kinds[oldest[i]->kind - 1].name) +
                   "\",\"id\":" + std::to_string(oldest[i]->id) +
                   ",\"seq\":" + std::to_string(oldest[i]->seq) +
                   ",\"bytes\":" + std::to_string(oldest[i]->bytes) +
                   ",\"age_ms\":" + std::to_string((now - oldest[i]->acquired_mono_ns) / 1000000) +
                   "}";
  }
  annotations += "]}}";
}

}  // namespace

// ================================ public API ====================================================

extern "C" {

uint32_t axmem_mode(void) { return kLedgerMode ? AXMEM_MODE_ID_LEDGER : AXMEM_MODE_ID_COUNTERS; }

int axmem_init(const axmem_config *config) {
  if (config == nullptr || config->struct_size != sizeof(axmem_config) ||
      config->output_path == nullptr || config->output_path[0] == '\0' ||
      !valid_uuid(config->run_id) || !valid_device_id(config->device_id)) {
    return AXMEM_ERR_INVALID;
  }
  std::lock_guard<std::mutex> lock(g_sink_mutex);
  if (g_sink.file != nullptr) return AXMEM_ERR_ALREADY;
  std::FILE *file = std::fopen(config->output_path, "ab");
  if (file == nullptr) return AXMEM_ERR_IO;
  Sink fresh;
  fresh.file = file;
  fresh.run_id = config->run_id;
  fresh.device_id = config->device_id;
  fresh.pid = AXMEM_GETPID();
  std::string stat;
  if (axmem_internal::read_small_file("/proc/self/stat", 4096, stat)) {
    fresh.start_ticks = axmem_internal::parse_stat_start_ticks(stat);
  }
  fresh.max_bytes = config->max_output_bytes != 0 ? config->max_output_bytes : kDefaultMaxOutput;
  fresh.allocator_stats = config->include_allocator_stats != 0;
  fresh.smaps_rollup = config->include_smaps_rollup != 0;
  fresh.fd_count = config->include_fd_count != 0;
  fresh.boot_id = axmem_internal::read_boot_id();
  g_sink = fresh;
  return AXMEM_OK;
}

void axmem_shutdown(void) {
  std::lock_guard<std::mutex> lock(g_sink_mutex);
  if (g_sink.file != nullptr) std::fclose(g_sink.file);
  g_sink = Sink();
}

uint32_t axmem_counter_handle(const char *name) { return register_metric(name, false); }
uint32_t axmem_gauge_handle(const char *name) { return register_metric(name, true); }

void axmem_counter_add_h(uint32_t handle, uint64_t delta) {
  if (handle >= kMaxMetrics) return;  // includes AXMEM_INVALID_HANDLE: a failed registration
  Slot &slot = g_slots[handle];
  if (slot.is_gauge) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  slot.value.fetch_add(delta, kRlx);
}

void axmem_gauge_set_h(uint32_t handle, uint64_t value) {
  if (handle >= kMaxMetrics) return;
  Slot &slot = g_slots[handle];
  if (!slot.is_gauge) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  slot.value.store(value, kRlx);
}

void axmem_gauge_watermark_h(uint32_t handle, uint64_t value) {
  if (handle >= kMaxMetrics) return;
  Slot &slot = g_slots[handle];
  if (!slot.is_gauge) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  uint64_t seen = slot.value.load(kRlx);
  while (seen < value && !slot.value.compare_exchange_weak(seen, value, kRlx)) {
  }
}

void axmem_counter_add(const char *name, uint64_t delta) {
  axmem_counter_add_h(register_metric(name, false), delta);
}

void axmem_gauge_set(const char *name, uint64_t value) {
  axmem_gauge_set_h(register_metric(name, true), value);
}

uint32_t axmem_kind_register(const char *name) {
  if (!valid_kind_name(name)) {
    g_registration_rejected.fetch_add(1, kRlx);
    return 0;
  }
  std::lock_guard<std::mutex> lock(g_kind_mutex);
  const uint32_t count = g_kind_count.load(std::memory_order_acquire);
  for (uint32_t i = 0; i < count; ++i) {
    if (std::strcmp(g_kinds[i].name, name) == 0) return i + 1;
  }
  if (count >= kMaxKinds) {
    g_registration_rejected.fetch_add(1, kRlx);
    return 0;
  }
  std::strncpy(g_kinds[count].name, name, kMaxKindNameLen);
  g_kind_count.store(count + 1, std::memory_order_release);
  return count + 1;
}

void axmem_resource_acquire(uint64_t id, uint32_t kind, uint64_t bytes) {
  if (kind == 0 || kind > g_kind_count.load(std::memory_order_acquire)) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  Kind &k = g_kinds[kind - 1];
  if (!kLedgerMode) {
    k.acquired.fetch_add(1, kRlx);
    return;
  }
  std::lock_guard<std::mutex> lock(g_ledger_mutex);
  if (ledger_find(id, kind) != kLedgerCapacity) {
    ++g_ledger_duplicates;
    return;
  }
  if (g_ledger_live >= kLedgerCapacity) {
    ++g_ledger_dropped;
    return;
  }
  uint32_t index = ledger_hash(id, kind);
  while (g_ledger[index].live) index = (index + 1) & (kLedgerCapacity - 1);
  g_ledger[index] = Entry{id, bytes, ++g_ledger_seq, mono_ns(), kind, true};
  ++g_ledger_live;
  k.acquired.fetch_add(1, kRlx);
  ++k.live_count;
  k.live_bytes += bytes;
  if (k.live_bytes > k.high_watermark_bytes) k.high_watermark_bytes = k.live_bytes;
}

void axmem_resource_release(uint64_t id, uint32_t kind) {
  if (kind == 0 || kind > g_kind_count.load(std::memory_order_acquire)) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  Kind &k = g_kinds[kind - 1];
  if (!kLedgerMode) {
    k.released.fetch_add(1, kRlx);
    return;
  }
  std::lock_guard<std::mutex> lock(g_ledger_mutex);
  const uint32_t index = ledger_find(id, kind);
  if (index == kLedgerCapacity) {
    ++g_ledger_unmatched;
    return;
  }
  k.live_bytes -= g_ledger[index].bytes;
  --k.live_count;
  k.released.fetch_add(1, kRlx);
  --g_ledger_live;
  ledger_erase(index);
}

void axmem_phase_marker(const char *phase) {
  if (!valid_phase(phase)) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  std::lock_guard<std::mutex> lock(g_sink_mutex);
  if (g_sink.file == nullptr) {
    g_rejected_calls.fetch_add(1, kRlx);
    return;
  }
  const std::string annotations =
      std::string("{\"event\":\"phase_start\",\"phase\":\"") + phase + "\"}";
  if (write_line(g_sink, envelope(g_sink, "event", "", annotations)) != AXMEM_OK) {
    g_snapshots_dropped.fetch_add(1, kRlx);
  }
}

int axmem_emit_snapshot(void) {
  // Lock order is always sink -> ledger; hot paths take only the ledger mutex.
  std::lock_guard<std::mutex> lock(g_sink_mutex);
  if (g_sink.file == nullptr) return AXMEM_ERR_NOT_INIT;
  const int64_t begin = mono_ns();
  MetricWriter w;
  uint64_t used = 0;
  for (std::size_t i = 0; i < kMaxMetrics; ++i) {
    Slot &slot = g_slots[i];
    if (slot.state.load(std::memory_order_acquire) != 2) continue;
    ++used;
    w.value(slot.name, slot.value.load(kRlx), unit_for(slot.name),
            slot.is_gauge ? "axmem_gauge" : "axmem_counter");
  }
  append_process_metrics(w, g_sink);
  std::string annotations;
  append_kind_metrics(w, annotations);
  if (g_sink.allocator_stats) append_allocator_metrics(w);
  const char *src = "axmem_probe";
  w.value("app.probe.metric_slots_used_count", used, "count", src);
  w.value("app.probe.snapshots_emitted_count", g_snapshots_emitted.load(kRlx), "count", src);
  w.value("app.probe.snapshots_dropped_count", g_snapshots_dropped.load(kRlx), "count", src);
  w.value("app.probe.registration_rejected_count", g_registration_rejected.load(kRlx), "count",
          src);
  w.value("app.probe.rejected_calls_count", g_rejected_calls.load(kRlx), "count", src);
  w.value("app.probe.output_bytes", g_sink.written, "bytes", src);
  if (g_snapshots_emitted.load(kRlx) == 0) {
    w.unavailable("app.probe.snapshot_duration_ns", "no previous snapshot to time");
  } else {
    w.value("app.probe.snapshot_duration_ns", g_last_snapshot_ns.load(kRlx), "nanoseconds", src);
  }
  const int status = write_line(g_sink, envelope(g_sink, "sample", w.out, annotations));
  if (status == AXMEM_OK) {
    g_snapshots_emitted.fetch_add(1, kRlx);
    g_last_snapshot_ns.store(static_cast<uint64_t>(mono_ns() - begin), kRlx);
  } else {
    g_snapshots_dropped.fetch_add(1, kRlx);
  }
  return status;
}

}  // extern "C"
