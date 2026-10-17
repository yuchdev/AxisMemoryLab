#ifndef AXMEM_TEST_SAMPLER_UTIL_HPP
#define AXMEM_TEST_SAMPLER_UTIL_HPP

// Minimal reader for alloc-samples-v1 files, enough for assertions. Not a general JSON parser.

#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "axis_memlab/sampler.h"

struct AllocRec {
  unsigned long long id = 0;
  unsigned long long size = 0;
  unsigned long long align = 0;
  double weight = 0;
  unsigned depth = 0;
  unsigned thread = 0;
  std::string kind;
};

struct ParsedSamples {
  std::vector<AllocRec> allocs;
  std::vector<unsigned long long> frees;
  std::map<std::string, unsigned long long> summary;  // last summary record
  unsigned headers = 0, modules = 0, summaries = 0;
  bool final_summary = false;
  std::string header;
  bool all_lines_end_cleanly = true;
};

inline bool field(const std::string &line, const char *key, std::string &out) {
  const std::string k = std::string("\"") + key + "\":";
  const std::size_t pos = line.find(k);
  if (pos == std::string::npos) return false;
  std::size_t b = pos + k.size();
  std::size_t e = b;
  if (line[b] == '"') {
    ++b;
    e = line.find('"', b);
  } else {
    while (e < line.size() && line[e] != ',' && line[e] != '}' && line[e] != ']') ++e;
  }
  out = line.substr(b, e - b);
  return true;
}

inline unsigned long long ull(const std::string &line, const char *key) {
  std::string v;
  return field(line, key, v) ? std::strtoull(v.c_str(), nullptr, 10) : 0ull;
}

inline ParsedSamples parse_samples(const std::string &path) {
  ParsedSamples out;
  std::ifstream in(path, std::ios::binary);
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    if (line.front() != '{' || line.back() != '}') out.all_lines_end_cleanly = false;
    std::string type;
    field(line, "type", type);
    if (type == "header") {
      ++out.headers;
      out.header = line;
    } else if (type == "modules") {
      ++out.modules;
    } else if (type == "alloc") {
      AllocRec r;
      r.id = ull(line, "id");
      r.size = ull(line, "size");
      r.align = ull(line, "align");
      r.thread = static_cast<unsigned>(ull(line, "thread"));
      std::string w, kind;
      if (field(line, "weight_count", w)) r.weight = std::strtod(w.c_str(), nullptr);
      if (field(line, "kind", kind)) r.kind = kind;
      const std::size_t s = line.find("\"stack\":[");
      if (s != std::string::npos) {
        const std::size_t e = line.find(']', s);
        for (std::size_t p = s; p < e; ++p) {
          if (line[p] == 'x') ++r.depth;  // each "0x..." address
        }
      }
      out.allocs.push_back(r);
    } else if (type == "free") {
      out.frees.push_back(ull(line, "id"));
    } else if (type == "summary") {
      ++out.summaries;
      std::string f;
      out.final_summary = field(line, "final", f) && f == "true";
      for (const char *key : {"alloc_requests", "alloc_request_bytes", "free_requests",
                              "samples_taken", "frees_matched", "live_samples",
                              "dropped_table_full", "dropped_ring_full", "dropped_free_events",
                              "dropped_output_cap", "stack_failures", "sample_interval_bytes"}) {
        out.summary[key] = ull(line, key);
      }
    }
  }
  return out;
}

inline axmem_sampler_config sampler_config(const char *path, unsigned long long interval,
                                           unsigned long long seed) {
  axmem_sampler_config c{};
  c.struct_size = sizeof c;
  c.output_path = path;
  c.run_id = "00000000-0000-4000-8000-0000000000c4";
  c.device_id = "synthetic-device-001";
  c.sample_interval_bytes = interval;
  c.seed = seed;
  c.max_output_bytes = 64u * 1024u * 1024u;
  return c;
}

#endif
