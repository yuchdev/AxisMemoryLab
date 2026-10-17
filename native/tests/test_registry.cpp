#include <atomic>
#include <thread>
#include <vector>

#include "axis_memlab/counters.hpp"
#include "check.hpp"

int main() {
  // Name rules: app.-prefixed lower-case metric names only.
  CHECK(axmem_counter_handle("app.frames_total_count") != AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle("frames") == AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle("app.") == AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle("app.Upper") == AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle("app.has space") == AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle("app.quote\"") == AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle(nullptr) == AXMEM_INVALID_HANDLE);
  CHECK(axmem_counter_handle(
            "app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") ==
        AXMEM_INVALID_HANDLE);  // longer than 64

  // Registration is idempotent; the same name cannot be both counter and gauge.
  const uint32_t a = axmem_counter_handle("app.x_count");
  CHECK(a == axmem_counter_handle("app.x_count"));
  CHECK(axmem_gauge_handle("app.x_count") == AXMEM_INVALID_HANDLE);

  // Inert handles are harmless.
  axmem_counter_add_h(AXMEM_INVALID_HANDLE, 5);
  axmem_gauge_set_h(AXMEM_INVALID_HANDLE, 5);

  // Concurrent registration of the same name yields one slot.
  std::vector<std::thread> threads;
  std::atomic<int> mismatches{0};
  const uint32_t expected = axmem_counter_handle("app.shared_count");
  for (int t = 0; t < 8; ++t) {
    threads.emplace_back([&] {
      for (int i = 0; i < 1000; ++i) {
        if (axmem_counter_handle("app.shared_count") != expected) ++mismatches;
      }
    });
  }
  for (auto &th : threads) th.join();
  CHECK(mismatches == 0);

  // Wrapper classes.
  axis_memlab::Counter ok("app.wrapped_count");
  axis_memlab::Counter bad("not-valid");
  CHECK(ok.valid());
  CHECK(!bad.valid());
  bad.add();  // inert
  CHECK(axmem_mode() != AXMEM_MODE_ID_DISABLED);

  // The table is bounded: registering far more names than slots fails cleanly.
  int rejected = 0;
  for (int i = 0; i < 400; ++i) {
    std::string name = "app.fill_" + std::to_string(i);
    if (axmem_counter_handle(name.c_str()) == AXMEM_INVALID_HANDLE) ++rejected;
  }
  CHECK(rejected >= 400 - 128);
  CHECK(axmem_counter_handle("app.one_more_count") == AXMEM_INVALID_HANDLE);
  return 0;
}
