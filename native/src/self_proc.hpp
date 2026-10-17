#ifndef AXIS_MEMLAB_SELF_PROC_HPP
#define AXIS_MEMLAB_SELF_PROC_HPP

// Internal: parsing of this process's own /proc files. Pure functions are exposed so that
// they can be tested with synthetic text. Not part of the public ABI.

#include <cstdint>
#include <optional>
#include <string>

namespace axmem_internal {

struct StatusFields {
  std::optional<uint64_t> vm_rss_bytes;
  std::optional<uint64_t> rss_anon_bytes;
  std::optional<uint64_t> rss_file_bytes;
  std::optional<uint64_t> rss_shmem_bytes;
  std::optional<uint64_t> vm_swap_bytes;
  std::optional<uint64_t> threads;
};

// Parses /proc/PID/status text. kB values are converted to bytes; absent or malformed lines
// leave the field empty (the caller reports it as unavailable, never as zero).
StatusFields parse_status(const std::string &text);

struct SmapsRollupFields {
  std::optional<uint64_t> pss_bytes;
  std::optional<uint64_t> private_clean_bytes;
  std::optional<uint64_t> private_dirty_bytes;
  std::optional<uint64_t> anonymous_bytes;
  std::optional<uint64_t> swap_bytes;
};

// Parses /proc/PID/smaps_rollup text with the same conversion rules as parse_status.
SmapsRollupFields parse_smaps_rollup(const std::string &text);

// Number of open descriptors of this process, excluding the one used for the listing itself.
// Empty when /proc/self/fd cannot be listed (not Linux, or permission denied).
std::optional<uint64_t> count_open_fds();

// Kernel boot id (a UUID) or empty when unreadable or not in the expected shape.
std::optional<std::string> read_boot_id();

// Field 22 (starttime, clock ticks since boot) of /proc/PID/stat; the command name may
// contain spaces and parentheses, so parsing starts after the last ')'.
std::optional<uint64_t> parse_stat_start_ticks(const std::string &text);

// Reads at most `limit` bytes of a small file. Returns false if it cannot be opened.
bool read_small_file(const char *path, std::size_t limit, std::string &out);

}  // namespace axmem_internal

#endif
