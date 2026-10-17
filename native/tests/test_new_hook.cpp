// The replaced global operator new / delete: standard semantics first, then sampling.
#include <cstddef>
#include <cstdint>
#include <new>
#include <set>
#include <string>
#include <vector>

#include "check.hpp"
#include "sampler_util.hpp"

// The hook defines these even when <new> hides them (Clang without -fsized-deallocation).
void operator delete(void *, std::size_t) noexcept;
void operator delete[](void *, std::size_t) noexcept;
void operator delete(void *, std::size_t, std::align_val_t) noexcept;
void operator delete[](void *, std::size_t, std::align_val_t) noexcept;

namespace {

int g_handler_calls = 0;
int g_handler_limit = 0;

void counting_handler() {
  ++g_handler_calls;
  if (g_handler_calls >= g_handler_limit) throw std::bad_alloc();
}

struct alignas(64) Aligned64 {
  char data[64];
};

constexpr std::size_t kHuge = static_cast<std::size_t>(-1) / 2;  // cannot be satisfied

axmem_sampler_stats get_stats() {
  axmem_sampler_stats s{};
  s.struct_size = sizeof s;
  CHECK(axmem_sampler_get_stats(&s) == AXMEM_OK);
  return s;
}

}  // namespace

int main() {
  // ---- standard semantics with the sampler OFF (the hook must be a conforming operator new) ---
  CHECK(axmem_sampler_active() == 0);
  {
    int *a = new int(7);
    int *arr = new int[10]();
    CHECK(*a == 7 && arr[9] == 0);
    delete a;
    delete[] arr;

    // zero-size requests give distinct non-null pointers
    void *z1 = ::operator new(0);
    void *z2 = ::operator new(0);
    CHECK(z1 != nullptr && z2 != nullptr && z1 != z2);
    ::operator delete(z1);
    ::operator delete(z2);

    // nothrow forms return nullptr instead of throwing
    CHECK(::operator new(kHuge, std::nothrow) == nullptr);
    CHECK(::operator new[](kHuge, std::nothrow) == nullptr);
    char *ok = new (std::nothrow) char[16];
    CHECK(ok != nullptr);
    ::operator delete[](ok, std::nothrow);

    // the throwing forms throw bad_alloc
    bool thrown = false;
    try {
      (void)::operator new(kHuge);
    } catch (const std::bad_alloc &) {
      thrown = true;
    }
    CHECK(thrown);
    thrown = false;
    try {
      std::vector<char> big(kHuge);
    } catch (const std::bad_alloc &) {
      thrown = true;
    } catch (const std::length_error &) {
      thrown = true;
    }
    CHECK(thrown);
  }

  // ---- new_handler is called repeatedly until it throws, nothrow swallows the exception --------
  {
    g_handler_calls = 0;
    g_handler_limit = 3;
    std::new_handler previous = std::set_new_handler(counting_handler);
    bool thrown = false;
    try {
      (void)::operator new(kHuge);
    } catch (const std::bad_alloc &) {
      thrown = true;
    }
    CHECK(thrown && g_handler_calls == 3);

    g_handler_calls = 0;
    CHECK(::operator new(kHuge, std::nothrow) == nullptr);
    CHECK(g_handler_calls == 3);
    std::set_new_handler(previous);
    CHECK(std::get_new_handler() == previous);
  }

  // ---- over-aligned forms honour the alignment and pair with aligned delete -----------------------
  {
    Aligned64 *p = new Aligned64;
    Aligned64 *arr = new Aligned64[3];
    CHECK(reinterpret_cast<std::uintptr_t>(p) % 64 == 0);
    CHECK(reinterpret_cast<std::uintptr_t>(arr) % 64 == 0);
    delete p;
    delete[] arr;
    void *big = ::operator new(1000, std::align_val_t(4096));
    CHECK(reinterpret_cast<std::uintptr_t>(big) % 4096 == 0);
    ::operator delete(big, std::align_val_t(4096));
    void *nt = ::operator new(10, std::align_val_t(256), std::nothrow);
    CHECK(nt != nullptr && reinterpret_cast<std::uintptr_t>(nt) % 256 == 0);
    ::operator delete(nt, std::align_val_t(256), std::nothrow);
    CHECK(::operator new(kHuge, std::align_val_t(64), std::nothrow) == nullptr);
  }

  // ---- sampling on: every request of >= 64 bytes is sampled at interval 1 ----------------------------
  const std::string path = temp_path("new_hook");
  auto config = sampler_config(path.c_str(), 1, 4242);
  std::vector<void *> plain;
  plain.reserve(50);  // the test's own bookkeeping must not allocate while sampling at interval 1
  CHECK(axmem_sampler_start(&config) == AXMEM_OK);
  CHECK(axmem_sampler_active() == 1);

  for (int i = 0; i < 50; ++i) plain.push_back(::operator new(256));
  char *arr = new char[300];
  char *nt = new (std::nothrow) char[400];
  Aligned64 *al = new Aligned64[4];
  void *al_nt = ::operator new(512, std::align_val_t(128), std::nothrow);
  CHECK(plain[0] != nullptr && arr && nt && al && al_nt);

  axmem_sampler_stats s = get_stats();
  CHECK_EQ(s.samples_taken, 50u + 4u);
  CHECK_EQ(s.live_samples, 54u);
  CHECK(s.stack_failures == 0);

  // A failed allocation leaves no sample and does not wedge the sampler.
  CHECK(::operator new(kHuge, std::nothrow) == nullptr);
  bool thrown = false;
  try {
    (void)::operator new(kHuge);
  } catch (const std::bad_alloc &) {
    thrown = true;
  }
  CHECK(thrown);
  CHECK(get_stats().samples_taken == 54);
  void *after_failure = ::operator new(128);
  CHECK(get_stats().samples_taken == 55);  // still sampling after the failures
  ::operator delete(after_failure);

  // Frees (all delete overloads) are matched before the memory is released.
  for (void *p : plain) ::operator delete(p, std::size_t{256});
  delete[] arr;
  ::operator delete[](nt, std::nothrow);
  delete[] al;
  ::operator delete(al_nt, std::align_val_t(128), std::nothrow);
  s = get_stats();
  CHECK(s.live_samples == 0 && s.frees_matched == 55);
  CHECK(s.dropped_ring_full == 0 && s.dropped_table_full == 0);

  // Explicitly exercise the remaining sized array and aligned delete overloads.
  ::operator delete[](::operator new[](256), std::size_t{256});
  ::operator delete(::operator new(256, std::align_val_t(64)), std::size_t{256},
                    std::align_val_t(64));
  ::operator delete[](::operator new[](256, std::align_val_t(64)), std::size_t{256},
                      std::align_val_t(64));
  s = get_stats();
  CHECK(s.samples_taken == 58 && s.live_samples == 0 && s.frees_matched == 58);

  // A pointer from before sampling started is just counted when freed.
  axmem_sampler_stop();
  void *old = ::operator new(1024);
  CHECK(axmem_sampler_start(&config) == AXMEM_OK);
  const unsigned long long frees_before = get_stats().free_requests;
  ::operator delete(old);
  s = get_stats();
  CHECK(s.free_requests == frees_before + 1 && s.frees_matched == 0);

  // Requests are counted exactly; sampled ones carry their size and kind.
  for (int i = 0; i < 10; ++i) ::operator delete(::operator new(2048));
  const unsigned long long requests = get_stats().alloc_requests;
  CHECK(requests >= 10);

  axmem_sampler_stop();
  CHECK(axmem_sampler_active() == 0);

  // After stop everything still works and nothing is recorded.
  void *late = ::operator new(4096);
  ::operator delete(late);

  const ParsedSamples parsed = parse_samples(path);
  CHECK(parsed.headers >= 1 && parsed.all_lines_end_cleanly && parsed.final_summary);
  std::set<std::string> kinds;
  std::set<unsigned long long> alloc_ids;
  for (const AllocRec &a : parsed.allocs) {
    kinds.insert(a.kind);
    alloc_ids.insert(a.id);
    CHECK(a.depth >= 1);
  }
  CHECK(kinds.count("new") && kinds.count("new[]") && kinds.count("new[]_nothrow"));
  CHECK(kinds.count("new[]_aligned"));
  CHECK(kinds.count("new_aligned_nothrow"));
  for (unsigned long long id : parsed.frees) CHECK(alloc_ids.count(id));
  return 0;
}
