#ifndef AXMEM_TEST_CHECK_HPP
#define AXMEM_TEST_CHECK_HPP

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>

// Always-on assertion (CTest builds may be Release with NDEBUG).
#define CHECK(cond)                                                          \
  do {                                                                       \
    if (!(cond)) {                                                           \
      std::fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
      std::exit(1);                                                          \
    }                                                                        \
  } while (0)

// Equality check that prints both values on failure.
#define CHECK_EQ(a, b)                                                                 \
  do {                                                                                 \
    const auto axmem_a = (a);                                                          \
    const auto axmem_b = (b);                                                          \
    if (!(axmem_a == axmem_b)) {                                                       \
      std::fprintf(stderr, "%s:%d: CHECK_EQ failed: %s == %s (%llu vs %llu)\n",       \
                   __FILE__, __LINE__, #a, #b, static_cast<unsigned long long>(axmem_a), \
                   static_cast<unsigned long long>(axmem_b));                          \
      std::exit(1);                                                                    \
    }                                                                                  \
  } while (0)

inline std::string slurp(const std::string &path) {
  std::ifstream in(path, std::ios::binary);
  std::ostringstream buffer;
  buffer << in.rdbuf();
  return buffer.str();
}

inline bool contains(const std::string &text, const std::string &needle) {
  return text.find(needle) != std::string::npos;
}

// Value of `"name":{"value":N` in the last snapshot of `text`, or -1 when absent/unavailable.
inline long long value_of(const std::string &text, const std::string &name) {
  const std::string key = "\"" + name + "\":{\"value\":";
  const std::size_t pos = text.rfind(key);
  if (pos == std::string::npos) return -1;
  return std::atoll(text.c_str() + pos + key.size());
}

inline std::string temp_path(const char *name) {
  std::string path = std::string("axmem_test_") + name + ".jsonl";
  std::remove(path.c_str());
  return path;
}

constexpr const char *kRunId = "00000000-0000-4000-8000-0000000000c3";

#endif
