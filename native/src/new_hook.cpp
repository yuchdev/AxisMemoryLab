// Global operator new / new[] / delete replacements that feed the allocation sampler.
//
// Linking this file replaces the program's global allocation functions (a C++ [new.delete]
// replacement). It is therefore an opt-in object library (`axis_memlab_new_hook`) for
// development builds, linked into the executable itself, never into a shared library that is
// loaded late.
//
// Order of work in every allocating overload:
//   1. record what is known before allocating (size, kind, call stack) if the sampler selects
//      this request;
//   2. perform the standard allocation: the new_handler loop, bad_alloc for the throwing forms,
//      nullptr for nothrow, alignment honoured, exactly as a conforming operator new behaves;
//   3. only if that succeeded, attach the returned pointer to the sample.
// A failed or throwing allocation leaves no sample. In every deallocating overload the sampler
// is told BEFORE the memory is released, so a recycled address cannot match a stale sample.
//
// Memory comes from malloc / aligned allocation and goes back through free, so the hooks can be
// mixed freely with code that uses malloc. Build this file with frame pointers
// (-fno-omit-frame-pointer): the unwinder walks the chain starting at each operator's frame.

#include <cstddef>
#include <cstdlib>
#include <new>

#include "sampler_core.hpp"

#if defined(_WIN32)
#include <malloc.h>
#endif

#if defined(__GNUC__)
#define AXMEM_FP() __builtin_frame_address(0)
#define AXMEM_RA() __builtin_return_address(0)
#define AXMEM_NOINLINE __attribute__((noinline))
#elif defined(_MSC_VER)
#define AXMEM_FP() nullptr
#define AXMEM_RA() nullptr
#define AXMEM_NOINLINE __declspec(noinline)
#else
#define AXMEM_FP() nullptr
#define AXMEM_RA() nullptr
#define AXMEM_NOINLINE
#endif

// The frame-pointer unwinder starts at the operator's own frame, so the operator must not
// compile into a tail call (which would pop that frame first). An empty asm statement after the
// call prevents it.
#if defined(__GNUC__)
#define AXMEM_RETURN(expr)                 \
  do {                                     \
    void *axmem_result = (expr);           \
    __asm__ __volatile__("" ::: "memory"); \
    return axmem_result;                   \
  } while (0)
#else
#define AXMEM_RETURN(expr) return (expr)
#endif

#if defined(__cpp_exceptions) || defined(_CPPUNWIND)
#define AXMEM_THROW_BAD_ALLOC() throw std::bad_alloc()
#define AXMEM_TRY try
#define AXMEM_CATCH_ALL catch (...)
#else
// Exceptions are disabled: a throwing new that cannot allocate terminates, as it would for an
// application built without exceptions.
#define AXMEM_THROW_BAD_ALLOC() std::abort()
#define AXMEM_TRY if (true)
#define AXMEM_CATCH_ALL else
#endif

namespace {

using axmem_internal::AllocKind;

void *platform_alloc(std::size_t size, std::size_t align) noexcept {
  if (size == 0) size = 1;  // a conforming operator new returns a unique non-null pointer
  if (align <= alignof(std::max_align_t)) return std::malloc(size);
#if defined(_WIN32)
  return _aligned_malloc(size, align);
#else
  void *p = nullptr;
  if (align < sizeof(void *)) align = sizeof(void *);
  if (posix_memalign(&p, align, size) != 0) return nullptr;
  return p;
#endif
}

void platform_free(void *p, std::size_t align) noexcept {
  if (p == nullptr) return;
#if defined(_WIN32)
  if (align > alignof(std::max_align_t)) {
    _aligned_free(p);
    return;
  }
#else
  (void)align;
#endif
  std::free(p);
}

// The standard allocation: retry through the installed new_handler until it succeeds or there
// is no handler left. The throwing forms throw bad_alloc; the nothrow forms return nullptr and
// also treat an exception escaping the handler as failure.
void *standard_allocate(std::size_t size, std::size_t align, bool nothrow) {
  for (;;) {
    if (void *p = platform_alloc(size, align)) return p;
    std::new_handler handler = std::get_new_handler();
    if (handler == nullptr) {
      if (nothrow) return nullptr;
      AXMEM_THROW_BAD_ALLOC();
    }
    if (nothrow) {
      AXMEM_TRY { handler(); }
      AXMEM_CATCH_ALL { return nullptr; }
    } else {
      handler();
    }
  }
}

// Clears the sampler's pending state if the allocation throws or fails.
struct PendingGuard {
  bool armed;
  ~PendingGuard() {
    if (armed) axmem_internal::sampler_abort();
  }
};

AXMEM_NOINLINE void *hooked_allocate(std::size_t size, std::size_t align, AllocKind kind,
                                     bool nothrow, void *fp, void *ra) {
  const bool sampled = axmem_internal::sampler_begin(size);
  if (sampled) axmem_internal::sampler_capture(fp, ra);  // stack first, before allocating
  PendingGuard guard{sampled};
  void *p = standard_allocate(size, align, nothrow);
  if (sampled) {
    guard.armed = false;
    if (p != nullptr) {
      axmem_internal::sampler_end(p, size, align, kind);
    } else {
      axmem_internal::sampler_abort();
    }
  }
  return p;
}

AXMEM_NOINLINE void hooked_release(void *p, std::size_t align) noexcept {
  axmem_internal::sampler_free(p);  // before the memory can be reused
  platform_free(p, align);
}

constexpr std::size_t kPlain = 0;  // alignment argument meaning "default alignment"

}  // namespace

// ---- allocation: plain -------------------------------------------------------------------------
void *operator new(std::size_t n) {
  AXMEM_RETURN(hooked_allocate(n, kPlain, axmem_internal::kKindNew, false, AXMEM_FP(), AXMEM_RA()));
}
void *operator new[](std::size_t n) {
  AXMEM_RETURN(hooked_allocate(n, kPlain, axmem_internal::kKindNewArray, false, AXMEM_FP(), AXMEM_RA()));
}
void *operator new(std::size_t n, const std::nothrow_t &) noexcept {
  AXMEM_RETURN(hooked_allocate(n, kPlain, axmem_internal::kKindNewNothrow, true, AXMEM_FP(), AXMEM_RA()));
}
void *operator new[](std::size_t n, const std::nothrow_t &) noexcept {
  AXMEM_RETURN(hooked_allocate(n, kPlain, axmem_internal::kKindNewArrayNothrow, true, AXMEM_FP(),
                         AXMEM_RA()));
}

// ---- allocation: over-aligned (C++17) ----------------------------------------------------------------
void *operator new(std::size_t n, std::align_val_t a) {
  AXMEM_RETURN(hooked_allocate(n, static_cast<std::size_t>(a), axmem_internal::kKindNewAligned, false,
                         AXMEM_FP(), AXMEM_RA()));
}
void *operator new[](std::size_t n, std::align_val_t a) {
  AXMEM_RETURN(hooked_allocate(n, static_cast<std::size_t>(a), axmem_internal::kKindNewArrayAligned, false,
                         AXMEM_FP(), AXMEM_RA()));
}
void *operator new(std::size_t n, std::align_val_t a, const std::nothrow_t &) noexcept {
  AXMEM_RETURN(hooked_allocate(n, static_cast<std::size_t>(a), axmem_internal::kKindNewAlignedNothrow,
                         true, AXMEM_FP(), AXMEM_RA()));
}
void *operator new[](std::size_t n, std::align_val_t a, const std::nothrow_t &) noexcept {
  AXMEM_RETURN(hooked_allocate(n, static_cast<std::size_t>(a),
                         axmem_internal::kKindNewArrayAlignedNothrow, true, AXMEM_FP(), AXMEM_RA()));
}

// ---- deallocation ------------------------------------------------------------------------------------
void operator delete(void *p) noexcept { hooked_release(p, kPlain); }
void operator delete[](void *p) noexcept { hooked_release(p, kPlain); }
void operator delete(void *p, std::size_t) noexcept { hooked_release(p, kPlain); }
void operator delete[](void *p, std::size_t) noexcept { hooked_release(p, kPlain); }
void operator delete(void *p, const std::nothrow_t &) noexcept { hooked_release(p, kPlain); }
void operator delete[](void *p, const std::nothrow_t &) noexcept { hooked_release(p, kPlain); }

void operator delete(void *p, std::align_val_t a) noexcept {
  hooked_release(p, static_cast<std::size_t>(a));
}
void operator delete[](void *p, std::align_val_t a) noexcept {
  hooked_release(p, static_cast<std::size_t>(a));
}
void operator delete(void *p, std::size_t, std::align_val_t a) noexcept {
  hooked_release(p, static_cast<std::size_t>(a));
}
void operator delete[](void *p, std::size_t, std::align_val_t a) noexcept {
  hooked_release(p, static_cast<std::size_t>(a));
}
void operator delete(void *p, std::align_val_t a, const std::nothrow_t &) noexcept {
  hooked_release(p, static_cast<std::size_t>(a));
}
void operator delete[](void *p, std::align_val_t a, const std::nothrow_t &) noexcept {
  hooked_release(p, static_cast<std::size_t>(a));
}
