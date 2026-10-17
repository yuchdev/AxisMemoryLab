#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "stack.hpp"

using axmem_internal::walk_frame_chain;

namespace {

std::uintptr_t addr(const std::uintptr_t *p) { return reinterpret_cast<std::uintptr_t>(p); }

#if defined(_MSC_VER)
__declspec(noinline)
#else
__attribute__((noinline))
#endif
unsigned capture_here(void **out, unsigned max) {
#if defined(__GNUC__)
  return axmem_internal::capture_stack(__builtin_frame_address(0), __builtin_return_address(0), out,
                                       max);
#else
  return axmem_internal::capture_stack(nullptr, nullptr, out, max);
#endif
}

}  // namespace

int main() {
  // A synthetic stack: three frame records laid out in an array, innermost first.
  alignas(sizeof(std::uintptr_t)) std::uintptr_t stack[8] = {};
  stack[0] = addr(&stack[2]);
  stack[1] = 0x1111;
  stack[2] = addr(&stack[4]);
  stack[3] = 0x2222;
  stack[4] = 0;  // the outermost frame has no caller frame pointer
  stack[5] = 0x3333;
  const std::uintptr_t lo = addr(&stack[0]);
  const std::uintptr_t hi = addr(&stack[8]);
  void *out[8] = {};

  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 8) == 3);
  CHECK(out[0] == reinterpret_cast<void *>(0x1111));
  CHECK(out[1] == reinterpret_cast<void *>(0x2222));
  CHECK(out[2] == reinterpret_cast<void *>(0x3333));

  // Depth is bounded.
  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 2) == 2);
  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 0) == 0);

  // A misaligned frame pointer is refused without reading memory.
  CHECK(walk_frame_chain(addr(&stack[0]) + 1, lo, hi, out, 8) == 0);
  // Frame pointers outside the stack, or without room for a full record, are refused.
  CHECK(walk_frame_chain(lo - sizeof(std::uintptr_t), lo, hi, out, 8) == 0);
  CHECK(walk_frame_chain(hi, lo, hi, out, 8) == 0);
  CHECK(walk_frame_chain(addr(&stack[7]), lo, hi, out, 8) == 0);
  CHECK(walk_frame_chain(0, lo, hi, out, 8) == 0);

  // A null return address ends the walk before it is recorded.
  stack[1] = 0;
  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 8) == 0);
  stack[1] = 0x1111;

  // A chain that does not climb (self-loop or downward link) records one frame and stops.
  stack[0] = addr(&stack[0]);
  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 8) == 1);
  stack[0] = addr(&stack[2]);
  stack[2] = addr(&stack[0]);
  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 8) == 2);
  stack[2] = addr(&stack[4]);

  // A link that leaves the stack range is followed by one more check and rejected.
  stack[2] = hi + 4096;
  CHECK(walk_frame_chain(addr(&stack[0]), lo, hi, out, 8) == 2);
  stack[2] = addr(&stack[4]);

  // A link that jumps farther than the stride limit is junk.
  static std::uintptr_t big[(2u << 20) / sizeof(std::uintptr_t)];
  big[0] = addr(&big[(1u << 20) / sizeof(std::uintptr_t) + 64]);
  big[1] = 0xAAAA;
  CHECK(walk_frame_chain(addr(&big[0]), addr(&big[0]), addr(&big[0]) + sizeof big, out, 8) == 1);

  // The real unwinder returns at least one frame on supported targets.
  void *frames[axmem_internal::kMaxStackDepth] = {};
  const unsigned n = capture_here(frames, axmem_internal::kMaxStackDepth);
  const std::string name = axmem_internal::unwinder_name();
  if (name == "caller_only") {
    CHECK(n <= 1);
  } else {
    CHECK(n >= 1);
    for (unsigned i = 0; i < n; ++i) CHECK(frames[i] != nullptr);
  }
  return 0;
}
