#ifndef AXIS_MEMLAB_STACK_HPP
#define AXIS_MEMLAB_STACK_HPP

// Internal: bounded call-stack capture for the allocation sampler.
//
// Rules: no heap allocation, no locks, no symbolization, no demangling, no backtrace() from
// libc. Linux x86-64 and AArch64 walk the frame-pointer chain (the code that calls the hook
// must be built with frame pointers, for example -fno-omit-frame-pointer); every frame record
// is checked against the thread's stack bounds before it is read. Windows uses
// CaptureStackBackTrace. Other targets record only the call site of the hook.

#include <cstddef>
#include <cstdint>

namespace axmem_internal {

constexpr unsigned kMaxStackDepth = 32;
constexpr std::uintptr_t kMaxFrameStride = 1u << 20;  // a caller frame farther than 1 MiB is junk

// Walks frame records starting at `fp` (a frame whose first word is the caller's frame pointer
// and whose second word is the return address). Stops at the first record that is misaligned,
// outside [lo, hi), has a null return address, or does not move strictly up the stack. Pure and
// deterministic so it can be tested on a synthetic stack.
unsigned walk_frame_chain(std::uintptr_t fp, std::uintptr_t lo, std::uintptr_t hi, void **out,
                          unsigned max);

// Captures the stack of the *caller of the hook function* whose frame is `hook_fp`.
// `hook_ra` is the hook's own return address, used where only the call site can be recorded.
// Returns the number of frames written to `out` (at most `max`).
unsigned capture_stack(void *hook_fp, void *hook_ra, void **out, unsigned max);

// Name of the unwinder compiled in: "frame_pointer", "capture_stack_back_trace", "caller_only".
const char *unwinder_name();

}  // namespace axmem_internal

#endif
