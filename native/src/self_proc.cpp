#include "self_proc.hpp"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <system_error>
#include <vector>

namespace axmem_internal {
namespace {

bool parse_u64(const char *text, uint64_t &value) {
  while (*text == ' ' || *text == '\t') ++text;
  if (*text < '0' || *text > '9') return false;
  char *end = nullptr;
  unsigned long long parsed = std::strtoull(text, &end, 10);
  if (end == text) return false;
  value = static_cast<uint64_t>(parsed);
  return true;
}

// Matches "Key:" at the start of `line`; returns the pointer after the colon or nullptr.
const char *after_key(const std::string &line, const char *key) {
  std::size_t n = 0;
  while (key[n] != '\0') ++n;
  if (line.compare(0, n, key) != 0) return nullptr;
  return line.c_str() + n;
}

void set_kb(const std::string &line, const char *key, std::optional<uint64_t> &field) {
  const char *rest = after_key(line, key);
  uint64_t value = 0;
  if (rest == nullptr || !parse_u64(rest, value)) return;
  const char *unit = rest;
  while (*unit == ' ' || *unit == '\t' || (*unit >= '0' && *unit <= '9')) ++unit;
  if (unit[0] != 'k' || unit[1] != 'B') return;  // unknown unit: do not guess
  if (value > UINT64_MAX / 1024) return;
  field = value * 1024;
}

}  // namespace

StatusFields parse_status(const std::string &text) {
  StatusFields out;
  std::size_t pos = 0;
  while (pos < text.size()) {
    std::size_t eol = text.find('\n', pos);
    if (eol == std::string::npos) eol = text.size();
    std::string line = text.substr(pos, eol - pos);
    pos = eol + 1;
    set_kb(line, "VmRSS:", out.vm_rss_bytes);
    set_kb(line, "RssAnon:", out.rss_anon_bytes);
    set_kb(line, "RssFile:", out.rss_file_bytes);
    set_kb(line, "RssShmem:", out.rss_shmem_bytes);
    set_kb(line, "VmSwap:", out.vm_swap_bytes);
    if (const char *rest = after_key(line, "Threads:")) {
      uint64_t value = 0;
      if (parse_u64(rest, value)) out.threads = value;
    }
  }
  return out;
}

SmapsRollupFields parse_smaps_rollup(const std::string &text) {
  SmapsRollupFields out;
  std::size_t pos = 0;
  while (pos < text.size()) {
    std::size_t eol = text.find('\n', pos);
    if (eol == std::string::npos) eol = text.size();
    const std::string line = text.substr(pos, eol - pos);
    pos = eol + 1;
    set_kb(line, "Pss:", out.pss_bytes);
    set_kb(line, "Private_Clean:", out.private_clean_bytes);
    set_kb(line, "Private_Dirty:", out.private_dirty_bytes);
    set_kb(line, "Anonymous:", out.anonymous_bytes);
    set_kb(line, "Swap:", out.swap_bytes);
  }
  return out;
}

std::optional<uint64_t> count_open_fds() {
  std::error_code ec;
  std::filesystem::directory_iterator it("/proc/self/fd", ec);
  if (ec) return std::nullopt;
  uint64_t count = 0;
  for (const std::filesystem::directory_iterator end; it != end; it.increment(ec)) {
    if (ec) return std::nullopt;
    ++count;
  }
  return count > 0 ? count - 1 : count;  // the listing holds one descriptor itself
}

std::optional<std::string> read_boot_id() {
  std::string text;
  if (!read_small_file("/proc/sys/kernel/random/boot_id", 64, text)) return std::nullopt;
  while (!text.empty() && (text.back() == '\n' || text.back() == ' ')) text.pop_back();
  if (text.size() != 36) return std::nullopt;
  for (char c : text) {
    const bool ok = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || c == '-';
    if (!ok) return std::nullopt;
  }
  return text;
}

std::optional<uint64_t> parse_stat_start_ticks(const std::string &text) {
  std::size_t close = text.rfind(')');
  if (close == std::string::npos) return std::nullopt;
  // After ')' the fields start at number 3 (state); starttime is field 22, i.e. index 19.
  std::vector<std::string> fields;
  std::size_t i = close + 1;
  while (i < text.size()) {
    while (i < text.size() && (text[i] == ' ' || text[i] == '\n')) ++i;
    std::size_t start = i;
    while (i < text.size() && text[i] != ' ' && text[i] != '\n') ++i;
    if (i > start) fields.push_back(text.substr(start, i - start));
  }
  if (fields.size() < 20) return std::nullopt;
  uint64_t value = 0;
  if (!parse_u64(fields[19].c_str(), value)) return std::nullopt;
  return value;
}

bool read_small_file(const char *path, std::size_t limit, std::string &out) {
  std::FILE *file = std::fopen(path, "rb");
  if (file == nullptr) return false;
  char buffer[1024];
  out.clear();
  while (out.size() < limit) {
    std::size_t want = limit - out.size();
    if (want > sizeof buffer) want = sizeof buffer;
    std::size_t got = std::fread(buffer, 1, want, file);
    if (got == 0) break;
    out.append(buffer, got);
  }
  std::fclose(file);
  return true;
}

}  // namespace axmem_internal
