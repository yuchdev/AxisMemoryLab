#include "modules.hpp"

#include <cstring>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#elif defined(__linux__)
#include <link.h>
#include <unistd.h>
#endif

namespace axmem_internal {
namespace {

void copy_base_name(const char *path, char *out, std::size_t cap) {
  const char *base = path;
  for (const char *p = path; *p != '\0'; ++p) {
    if (*p == '/' || *p == '\\') base = p + 1;
  }
  std::size_t i = 0;
  for (; base[i] != '\0' && i + 1 < cap; ++i) {
    const char c = base[i];
    // Only characters that are safe in the output file; anything else becomes '_'.
    const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                    c == '.' || c == '_' || c == '-' || c == '+';
    out[i] = ok ? c : '_';
  }
  out[i] = '\0';
}

void hex_encode(const unsigned char *bytes, std::size_t n, char *out, std::size_t cap) {
  static const char digits[] = "0123456789abcdef";
  std::size_t o = 0;
  for (std::size_t i = 0; i < n && o + 2 < cap; ++i) {
    out[o++] = digits[bytes[i] >> 4];
    out[o++] = digits[bytes[i] & 15];
  }
  out[o] = '\0';
}

}  // namespace

#if defined(__linux__) && !defined(_WIN32)

namespace {

struct Collect {
  ModuleInfo *out;
  unsigned max;
  unsigned n;
};

// NT_GNU_BUILD_ID notes live in PT_NOTE segments; each note is name + descriptor, 4-aligned.
void find_build_id(const dl_phdr_info *info, ModuleInfo &m) {
  for (int i = 0; i < info->dlpi_phnum; ++i) {
    const ElfW(Phdr) &ph = info->dlpi_phdr[i];
    if (ph.p_type != PT_NOTE) continue;
    const unsigned char *p = reinterpret_cast<const unsigned char *>(info->dlpi_addr + ph.p_vaddr);
    const unsigned char *end = p + ph.p_memsz;
    while (p + sizeof(ElfW(Nhdr)) <= end) {
      const ElfW(Nhdr) *nh = reinterpret_cast<const ElfW(Nhdr) *>(p);
      const unsigned char *name = p + sizeof(ElfW(Nhdr));
      const std::size_t name_len = (nh->n_namesz + 3u) & ~3u;
      const std::size_t desc_len = (nh->n_descsz + 3u) & ~3u;
      const unsigned char *desc = name + name_len;
      if (desc + desc_len > end) break;
      if (nh->n_type == NT_GNU_BUILD_ID && nh->n_namesz == 4 &&
          std::memcmp(name, "GNU", 4) == 0 && nh->n_descsz > 0 && nh->n_descsz <= 32) {
        hex_encode(desc, nh->n_descsz, m.build_id, sizeof m.build_id);
        return;
      }
      p = desc + desc_len;
    }
  }
}

int on_module(dl_phdr_info *info, std::size_t, void *data) {
  Collect &c = *static_cast<Collect *>(data);
  if (c.n >= c.max) return 1;
  ModuleInfo &m = c.out[c.n];
  std::memset(&m, 0, sizeof m);
  if (info->dlpi_name != nullptr && info->dlpi_name[0] != '\0') {
    copy_base_name(info->dlpi_name, m.name, sizeof m.name);
  } else {
    char exe[256];
    const ssize_t len = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (len > 0) {
      exe[len] = '\0';
      copy_base_name(exe, m.name, sizeof m.name);
    } else {
      copy_base_name("main", m.name, sizeof m.name);
    }
  }
  m.base = info->dlpi_addr;
  std::uintptr_t high = 0;
  for (int i = 0; i < info->dlpi_phnum; ++i) {
    const ElfW(Phdr) &ph = info->dlpi_phdr[i];
    if (ph.p_type == PT_LOAD && ph.p_vaddr + ph.p_memsz > high) high = ph.p_vaddr + ph.p_memsz;
  }
  m.size = high;
  find_build_id(info, m);
  if (m.name[0] == '\0') copy_base_name("unnamed", m.name, sizeof m.name);
  ++c.n;
  return 0;
}

}  // namespace

unsigned collect_modules(ModuleInfo *out, unsigned max) {
  Collect c{out, max, 0};
  dl_iterate_phdr(on_module, &c);
  return c.n;
}

#elif defined(_WIN32)

unsigned collect_modules(ModuleInfo *out, unsigned max) {
  HMODULE handles[kMaxModules];
  DWORD needed = 0;
  if (!EnumProcessModules(GetCurrentProcess(), handles, sizeof handles, &needed)) return 0;
  unsigned count = static_cast<unsigned>(needed / sizeof(HMODULE));
  if (count > kMaxModules) count = kMaxModules;
  unsigned n = 0;
  for (unsigned i = 0; i < count && n < max; ++i) {
    ModuleInfo &m = out[n];
    std::memset(&m, 0, sizeof m);
    char path[MAX_PATH];
    if (GetModuleFileNameA(handles[i], path, MAX_PATH) == 0) continue;
    copy_base_name(path, m.name, sizeof m.name);
    MODULEINFO mi{};
    if (!GetModuleInformation(GetCurrentProcess(), handles[i], &mi, sizeof mi)) continue;
    m.base = reinterpret_cast<std::uintptr_t>(mi.lpBaseOfDll);
    m.size = mi.SizeOfImage;
    // PE identity: link timestamp and image size. Enough to detect a different build; the host
    // resolver for PE files is not provided (ELF only).
    const auto *dos = reinterpret_cast<const IMAGE_DOS_HEADER *>(mi.lpBaseOfDll);
    if (dos->e_magic == IMAGE_DOS_SIGNATURE) {
      const auto *nt = reinterpret_cast<const IMAGE_NT_HEADERS *>(
          reinterpret_cast<const unsigned char *>(mi.lpBaseOfDll) + dos->e_lfanew);
      if (nt->Signature == IMAGE_NT_SIGNATURE) {
        const unsigned char raw[8] = {
            static_cast<unsigned char>(nt->FileHeader.TimeDateStamp >> 24),
            static_cast<unsigned char>(nt->FileHeader.TimeDateStamp >> 16),
            static_cast<unsigned char>(nt->FileHeader.TimeDateStamp >> 8),
            static_cast<unsigned char>(nt->FileHeader.TimeDateStamp),
            static_cast<unsigned char>(nt->OptionalHeader.SizeOfImage >> 24),
            static_cast<unsigned char>(nt->OptionalHeader.SizeOfImage >> 16),
            static_cast<unsigned char>(nt->OptionalHeader.SizeOfImage >> 8),
            static_cast<unsigned char>(nt->OptionalHeader.SizeOfImage)};
        hex_encode(raw, sizeof raw, m.build_id, sizeof m.build_id);
      }
    }
    ++n;
  }
  return n;
}

#else

unsigned collect_modules(ModuleInfo *, unsigned) { return 0; }

#endif

std::uint64_t modules_fingerprint(const ModuleInfo *mods, unsigned n) {
  std::uint64_t h = 1469598103934665603ull;
  auto mix = [&h](const void *data, std::size_t len) {
    const unsigned char *p = static_cast<const unsigned char *>(data);
    for (std::size_t i = 0; i < len; ++i) {
      h ^= p[i];
      h *= 1099511628211ull;
    }
  };
  for (unsigned i = 0; i < n; ++i) {
    mix(mods[i].name, std::strlen(mods[i].name));
    mix(mods[i].build_id, std::strlen(mods[i].build_id));
    mix(&mods[i].base, sizeof mods[i].base);
    mix(&mods[i].size, sizeof mods[i].size);
  }
  return h;
}

}  // namespace axmem_internal
