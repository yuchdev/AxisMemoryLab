#include "axis_memlab/probe.hpp"
#include "check.hpp"

static std::string snapshot_text(const char *name) {
  const std::string path = temp_path(name);
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = kRunId;
  config.device_id = "synthetic-device-001";
  CHECK(axmem_init(&config) == AXMEM_OK);
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_shutdown();
  return slurp(path);
}

int main() {
  CHECK(axmem_mode() == AXMEM_MODE_ID_LEDGER);
  axis_memlab::ResourceKind frame("frame");
  axis_memlab::ResourceKind tensor("tensor");
  CHECK(frame.valid() && tensor.valid() && frame.id() != tensor.id());

  for (uint64_t id = 1; id <= 5; ++id) frame.acquire(id, 100);
  tensor.acquire(1, 50);   // same numeric id, different kind: a distinct resource
  frame.acquire(3, 999);   // duplicate of a live resource: counted, not applied
  frame.release(99);       // never acquired
  frame.release(2);
  frame.release(4);
  tensor.release(2);       // acquired as a frame, released as a tensor: not matched
  { axis_memlab::ResourceGuard guard(7, frame.id(), 10); }  // scoped: net zero

  const std::string text = snapshot_text("ledger");
  CHECK(value_of(text, "app.resource.frame.in_flight_count") == 3);
  CHECK(value_of(text, "app.resource.frame.in_flight_bytes") == 300);
  CHECK(value_of(text, "app.resource.frame.high_watermark_bytes") == 500);
  CHECK(value_of(text, "app.resource.frame.acquired_total_count") == 6);
  CHECK(value_of(text, "app.resource.frame.released_total_count") == 3);
  CHECK(value_of(text, "app.resource.tensor.in_flight_count") == 1);
  CHECK(value_of(text, "app.resource.tensor.in_flight_bytes") == 50);
  CHECK(value_of(text, "app.ledger.live_count") == 4);
  CHECK(value_of(text, "app.ledger.duplicate_acquire_count") == 1);
  CHECK(value_of(text, "app.ledger.unmatched_release_count") == 2);
  CHECK(value_of(text, "app.ledger.events_dropped_count") == 0);
  CHECK(value_of(text, "app.ledger.degraded") == 0);
  // The oldest live resources are listed by acquisition order, with ids for follow-up.
  CHECK(contains(text, "\"oldest_live\":[{\"kind\":\"frame\",\"id\":1,\"seq\":1,\"bytes\":100,"));
  CHECK(contains(text, "{\"kind\":\"frame\",\"id\":3,\"seq\":3,"));
  CHECK(!contains(text, "\"id\":2,"));
  return 0;
}
