// Built against a ledger with capacity 8 so that overflow and backward-shift deletion with
// wrap-around are exercised. A reference model checks every counter the ledger exports.
#include <set>
#include <utility>

#include "axis_memlab/probe.hpp"
#include "check.hpp"

int main() {
  axis_memlab::ResourceKind kind("slot");
  CHECK(kind.valid());

  // Phase 1: explicit overflow.
  for (uint64_t id = 1; id <= 12; ++id) kind.acquire(id, 1);
  for (uint64_t id = 1; id <= 12; ++id) kind.release(id);

  // Phase 2: pseudo-random acquire/release over a small id space, mirrored by a model.
  std::set<uint64_t> live;
  long long dups = 0, unmatched = 0, dropped = 0;  // phase 1 contributes below
  dropped += 4;    // ids 9..12 did not fit
  unmatched += 4;  // and their releases found nothing
  uint64_t state = 12345;
  for (int step = 0; step < 20000; ++step) {
    state = state * 6364136223846793005ull + 1442695040888963407ull;
    const uint64_t id = (state >> 33) % 24;
    if ((state >> 20) & 1) {
      if (live.count(id)) {
        ++dups;
      } else if (live.size() >= 8) {
        ++dropped;
      } else {
        live.insert(id);
      }
      kind.acquire(id, 3);
    } else {
      if (live.count(id)) {
        live.erase(id);
      } else {
        ++unmatched;
      }
      kind.release(id);
    }
  }

  const std::string path = temp_path("ledger_overflow");
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = kRunId;
  config.device_id = "synthetic-device-001";
  CHECK(axmem_init(&config) == AXMEM_OK);
  CHECK(axmem_emit_snapshot() == AXMEM_OK);
  axmem_shutdown();
  const std::string text = slurp(path);
  CHECK(value_of(text, "app.ledger.capacity_count") == 8);
  CHECK(value_of(text, "app.ledger.live_count") == static_cast<long long>(live.size()));
  CHECK(value_of(text, "app.resource.slot.in_flight_count") == static_cast<long long>(live.size()));
  CHECK(value_of(text, "app.resource.slot.in_flight_bytes") == static_cast<long long>(live.size()) * 3);
  CHECK(value_of(text, "app.ledger.duplicate_acquire_count") == dups);
  CHECK(value_of(text, "app.ledger.unmatched_release_count") == unmatched);
  CHECK(value_of(text, "app.ledger.events_dropped_count") == dropped);
  CHECK(value_of(text, "app.ledger.degraded") == 1);  // overflow is never silent
  return 0;
}
