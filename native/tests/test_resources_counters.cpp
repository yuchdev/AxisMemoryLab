#include "axis_memlab/probe.hpp"
#include "check.hpp"

int main() {
  CHECK(axmem_mode() == AXMEM_MODE_ID_COUNTERS);
  CHECK(axmem_kind_register("Bad Kind") == 0);
  CHECK(axmem_kind_register("") == 0);
  axis_memlab::ResourceKind frame("frame");
  CHECK(frame.valid());
  CHECK(axmem_kind_register("frame") == frame.id());

  for (uint64_t i = 1; i <= 10; ++i) frame.acquire(i, 100);
  for (uint64_t i = 1; i <= 4; ++i) frame.release(i);
  axmem_resource_acquire(1, 0, 1);  // unregistered kind: counted, not applied
  axmem_resource_release(1, 99);

  const std::string path = temp_path("counters_resources");
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = kRunId;
  config.device_id = "synthetic-device-001";
  CHECK(axmem_init(&config) == AXMEM_OK);
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_shutdown();
  const std::string text = slurp(path);
  CHECK(contains(text, "\"app.resource.frame.acquired_total_count\":{\"value\":10,"));
  CHECK(contains(text, "\"app.resource.frame.released_total_count\":{\"value\":4,"));
  CHECK(contains(text, "\"app.resource.frame.in_flight_count\":{\"value\":6,"));
  // Bytes need identities; COUNTERS mode says so instead of exporting zero.
  CHECK(contains(text, "\"app.resource.frame.in_flight_bytes\":{\"available\":false,"));
  CHECK(contains(text, "\"app.probe.rejected_calls_count\":{\"value\":2,"));
  CHECK(!contains(text, "app.ledger."));
  return 0;
}
