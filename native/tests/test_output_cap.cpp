#include "axis_memlab/probe.h"
#include "check.hpp"

int main() {
  const std::string path = temp_path("cap");
  axmem_config config{};
  config.struct_size = sizeof(axmem_config);
  config.output_path = path.c_str();
  config.run_id = kRunId;
  config.device_id = "synthetic-device-001";
  config.max_output_bytes = 6000;
  CHECK(axmem_init(&config) == AXMEM_OK);

  int written = 0;
  int refused = 0;
  for (int i = 0; i < 40; ++i) {
    const int status = axmem_emit_snapshot();
    if (status == AXMEM_OK) {
      ++written;
    } else if (status == AXMEM_ERR_LIMIT) {
      ++refused;
    } else {
      CHECK(false);
    }
  }
  axmem_shutdown();
  CHECK(written >= 1);
  CHECK(refused >= 1);
  const std::string text = slurp(path);
  CHECK(text.size() <= 6000);  // the cap is a hard limit, never exceeded
  CHECK(!text.empty() && text.back() == '\n');  // no partial record is ever written
  std::size_t lines = 0;
  for (char c : text) lines += (c == '\n');
  CHECK(lines == static_cast<std::size_t>(written));
  return 0;
}
