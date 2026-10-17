#ifndef AXIS_MEMLAB_VALIDATE_HPP
#define AXIS_MEMLAB_VALIDATE_HPP

// Internal: input validation shared by the probe and the sampler. Anything that ends up in an
// output file is checked against a small character set first, so no escaping is needed and no
// free text can carry identifying or payload data.

#include <cstring>

namespace axmem_internal {

inline bool valid_uuid_text(const char *text) {
  if (text == nullptr || std::strlen(text) != 36) return false;
  for (int i = 0; i < 36; ++i) {
    const char c = text[i];
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (c != '-') return false;
    } else if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) {
      return false;
    }
  }
  return true;
}

// Pseudonymous device label: [A-Za-z0-9._-], at most 64 characters.
inline bool valid_device_label(const char *text) {
  if (text == nullptr) return false;
  const std::size_t length = std::strlen(text);
  if (length == 0 || length > 64) return false;
  for (std::size_t i = 0; i < length; ++i) {
    const char c = text[i];
    const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                    c == '.' || c == '_' || c == '-';
    if (!ok) return false;
  }
  return true;
}

}  // namespace axmem_internal

#endif
