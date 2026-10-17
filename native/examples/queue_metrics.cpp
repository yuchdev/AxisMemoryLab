// Pattern: a bounded work queue with depth, bytes, high-watermark, and drop accounting.
// SDK-free and application-agnostic. The gauges are updated at the queue's own boundaries
// (push, pop, drop), so they cannot double count work that is merely in a later stage.
//
//   usage: axis_memlab_queue_metrics_example [OUTPUT.jsonl]
#include <cstdio>
#include <deque>
#include <string>

#include "axis_memlab/probe.hpp"

namespace {

template <typename Item>
class InstrumentedQueue {
 public:
  InstrumentedQueue(const char *depth_name, const char *bytes_name, const char *watermark_name,
                    const char *dropped_name, std::size_t max_items)
      : depth_(depth_name),
        bytes_(bytes_name),
        watermark_(watermark_name),
        dropped_(dropped_name),
        max_items_(max_items) {}

  // Returns false (and counts a drop) instead of growing without bound.
  bool push(Item item, std::size_t item_bytes) {
    if (items_.size() >= max_items_) {
      dropped_.add();
      return false;
    }
    items_.push_back(std::move(item));
    sizes_.push_back(item_bytes);
    queued_bytes_ += item_bytes;
    publish();
    return true;
  }

  bool pop(Item &out) {
    if (items_.empty()) return false;
    out = std::move(items_.front());
    items_.pop_front();
    queued_bytes_ -= sizes_.front();
    sizes_.pop_front();
    publish();
    return true;
  }

  std::size_t size() const { return items_.size(); }

 private:
  void publish() {
    depth_.set(items_.size());
    bytes_.set(queued_bytes_);
    watermark_.watermark(queued_bytes_);
  }

  axis_memlab::Gauge depth_;
  axis_memlab::Gauge bytes_;
  axis_memlab::Gauge watermark_;
  axis_memlab::Counter dropped_;
  std::deque<Item> items_;
  std::deque<std::size_t> sizes_;
  std::size_t queued_bytes_ = 0;
  std::size_t max_items_;
};

}  // namespace

int main(int argc, char **argv) {
  const std::string path = argc > 1 ? argv[1] : "queue_metrics_example.jsonl";
  std::remove(path.c_str());
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = "00000000-0000-4000-8000-0000000000e5";
  config.device_id = "synthetic-device-001";
  if (axmem_init(&config) != AXMEM_OK) return 1;

  InstrumentedQueue<int> results("app.queue.results_depth_count", "app.queue.results_bytes",
                                 "app.queue.results_high_watermark_bytes",
                                 "app.queue.results_dropped_count", 4);
  for (int i = 0; i < 6; ++i) results.push(i, 100);  // 4 fit, 2 are dropped
  int value = 0;
  results.pop(value);
  const bool ok = results.size() == 3 && value == 0;
  const int status = axmem_emit_snapshot();
  axmem_shutdown();
  return ok && status == AXMEM_OK ? 0 : 1;
}
