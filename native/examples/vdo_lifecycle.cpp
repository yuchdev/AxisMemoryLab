// Pattern only: where acquire/release hooks belong around a camera-SDK style buffer API.
//
// FakeStream below is a STAND-IN with the usual "get a buffer, use it, give it back" shape. It is
// not the VDO API. Real integrations must follow the exact free/unref sequence and ownership
// rules of the application's own SDK generation, and must not let the hooks change them.
//
//   usage: axis_memlab_vdo_lifecycle_example [OUTPUT.jsonl]
#include <cstdio>
#include <string>

#include "axis_memlab/probe.hpp"

namespace {

struct FakeBuffer {
  uint64_t id;
  std::size_t bytes;
};

class FakeStream {
 public:
  bool get_buffer(FakeBuffer &out) {
    if (next_ > 10) return false;  // end of stream
    out = FakeBuffer{next_++, 4096};
    return true;
  }
  void give_back(const FakeBuffer &) {}

 private:
  uint64_t next_ = 1;
};

// Hook at the ownership boundary: acquired when the SDK hands the buffer over, released where the
// application gives it back, on every path including the error path.
bool process_one(FakeStream &stream, const axis_memlab::ResourceKind &frames, bool fail_midway) {
  FakeBuffer buffer{};
  if (!stream.get_buffer(buffer)) return false;
  frames.acquire(buffer.id, buffer.bytes);
  if (fail_midway) {
    stream.give_back(buffer);       // the SDK call that returns ownership
    frames.release(buffer.id);      // mirrored immediately after it, same as the success path
    return true;                    // early return no longer skips the release
  }
  // ... decode, convert, hand to inference ...
  stream.give_back(buffer);
  frames.release(buffer.id);
  return true;
}

}  // namespace

int main(int argc, char **argv) {
  const std::string path = argc > 1 ? argv[1] : "vdo_lifecycle_example.jsonl";
  std::remove(path.c_str());
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = "00000000-0000-4000-8000-0000000000e6";
  config.device_id = "synthetic-device-001";
  if (axmem_init(&config) != AXMEM_OK) return 1;

  axis_memlab::ResourceKind frames("frame");
  axis_memlab::Counter processed("app.frames_total_count");
  FakeStream stream;
  int index = 0;
  while (process_one(stream, frames, (index++ % 3) == 2)) processed.add();

  const int status = axmem_emit_snapshot();
  axmem_shutdown();
  return status == AXMEM_OK ? 0 : 1;
}
