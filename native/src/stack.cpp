#include "stack.hpp"

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#define AXMEM_UNWIND_WINDOWS 1
#elif defined(__linux__) && (defined(__x86_64__) || defined(__aarch64__))
#include <pthread.h>
#define AXMEM_UNWIND_FP 1
#endif

namespace axmem_internal {

unsigned walk_frame_chain(std::uintptr_t fp, std::uintptr_t lo, std::uintptr_t hi, void **out,
                          unsigned max) {
  constexpr std::uintptr_t word = sizeof(std::uintptr_t);
  unsigned n = 0;
  while (n < max) {
    if ((fp & (word - 1)) != 0) break;
    if (fp < lo || fp > hi || hi - fp < 2 * word) break;
    const std::uintptr_t next = *reinterpret_cast<const std::uintptr_t *>(fp);
    const std::uintptr_t ra = *reinterpret_cast<const std::uintptr_t *>(fp + word);
    if (ra == 0) break;
    out[n++] = reinterpret_cast<void *>(ra);
    if (next <= fp || next - fp > kMaxFrameStride) break;  // must climb the stack, in small steps
    fp = next;
  }
  return n;
}

#if defined(AXMEM_UNWIND_FP)

namespace {

struct Bounds {
  std::uintptr_t lo = 0;
  std::uintptr_t hi = 0;
  int state = 0;  // 0 unknown, 1 ready, 2 unavailable
};
thread_local Bounds t_bounds;

bool stack_bounds(std::uintptr_t &lo, std::uintptr_t &hi) {
  Bounds &b = t_bounds;
  if (b.state == 0) {
    pthread_attr_t attr;
    b.state = 2;
    if (pthread_getattr_np(pthread_self(), &attr) == 0) {
      void *addr = nullptr;
      std::size_t size = 0;
      if (pthread_attr_getstack(&attr, &addr, &size) == 0 && addr != nullptr && size > 0) {
        b.lo = reinterpret_cast<std::uintptr_t>(addr);
        b.hi = b.lo + size;
        b.state = 1;
      }
      pthread_attr_destroy(&attr);
    }
  }
  lo = b.lo;
  hi = b.hi;
  return b.state == 1;
}

}  // namespace

unsigned capture_stack(void *hook_fp, void *hook_ra, void **out, unsigned max) {
  (void)hook_ra;
  std::uintptr_t lo = 0, hi = 0;
  if (hook_fp == nullptr || !stack_bounds(lo, hi)) return 0;
  return walk_frame_chain(reinterpret_cast<std::uintptr_t>(hook_fp), lo, hi, out, max);
}

const char *unwinder_name() { return "frame_pointer"; }

#elif defined(AXMEM_UNWIND_WINDOWS)

#ifndef AXMEM_MSVC_SKIP_FRAMES
// Frames between CaptureStackBackTrace and the caller of operator new: capture_stack,
// sampler_capture, the common allocation helper, and the operator itself. Inlining can change
// this; the offset only affects which frames lead the stack, not whether the sample is recorded.
#define AXMEM_MSVC_SKIP_FRAMES 4
#endif

__declspec(noinline) unsigned capture_stack(void *hook_fp, void *hook_ra, void **out,
                                            unsigned max) {
  (void)hook_fp;
  (void)hook_ra;
  return static_cast<unsigned>(CaptureStackBackTrace(AXMEM_MSVC_SKIP_FRAMES, max, out, nullptr));
}

const char *unwinder_name() { return "capture_stack_back_trace"; }

#else

unsigned capture_stack(void *hook_fp, void *hook_ra, void **out, unsigned max) {
  (void)hook_fp;
  if (max == 0 || hook_ra == nullptr) return 0;
  out[0] = hook_ra;  // only the call site of operator new is known without an unwinder
  return 1;
}

const char *unwinder_name() { return "caller_only"; }

#endif

}  // namespace axmem_internal
