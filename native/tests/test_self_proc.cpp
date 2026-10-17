#include "check.hpp"
#include "self_proc.hpp"

int main() {
  using namespace axmem_internal;
  const std::string status =
      "Name:\tsynthetic (proc)\nVmRSS:\t    2048 kB\nRssAnon:\t    1024 kB\nRssFile:\t 512 kB\n"
      "RssShmem:\t0 kB\nVmSwap:\t 4 kB\nThreads:\t7\n";
  StatusFields f = parse_status(status);
  CHECK(f.vm_rss_bytes && *f.vm_rss_bytes == 2048u * 1024u);
  CHECK(f.rss_anon_bytes && *f.rss_anon_bytes == 1024u * 1024u);
  CHECK(f.rss_shmem_bytes && *f.rss_shmem_bytes == 0);  // zero is a real value
  CHECK(f.threads && *f.threads == 7);

  // Missing fields stay empty; an unknown unit is not guessed; garbage is ignored.
  StatusFields g = parse_status("VmRSS:\t12 MB\nRssAnon:\tabc kB\nThreads:\t\n");
  CHECK(!g.vm_rss_bytes);
  CHECK(!g.rss_anon_bytes);
  CHECK(!g.threads);
  CHECK(!g.vm_swap_bytes);
  CHECK(!parse_status("").rss_file_bytes);

  // Overflow of kB -> bytes must not wrap.
  CHECK(!parse_status("VmRSS:\t18446744073709551615 kB\n").vm_rss_bytes);

  // starttime is field 22; the command name may contain spaces and parentheses.
  const std::string stat =
      "42 (a b) c) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 987654 23 24\n";
  auto ticks = parse_stat_start_ticks(stat);
  CHECK(ticks && *ticks == 987654u);
  CHECK(!parse_stat_start_ticks("42 (short) S 1 2"));
  CHECK(!parse_stat_start_ticks("no parenthesis"));

  const std::string rollup =
      "00400000-7fff00000000 ---p 00000000 00:00 0   [rollup]\n"
      "Rss:\t 900 kB\nPss:\t 600 kB\nPss_Anon:\t 100 kB\n"
      "Private_Clean:\t 50 kB\nPrivate_Dirty:\t 70 kB\nAnonymous:\t 100 kB\nSwap:\t 0 kB\n";
  SmapsRollupFields r = parse_smaps_rollup(rollup);
  CHECK(r.pss_bytes && *r.pss_bytes == 600u * 1024u);  // Pss_Anon must not shadow Pss
  CHECK(r.private_clean_bytes && *r.private_clean_bytes == 50u * 1024u);
  CHECK(r.private_dirty_bytes && *r.private_dirty_bytes == 70u * 1024u);
  CHECK(r.anonymous_bytes && *r.anonymous_bytes == 100u * 1024u);
  CHECK(r.swap_bytes && *r.swap_bytes == 0);  // a real zero
  CHECK(!parse_smaps_rollup("Rss: 1 kB\n").pss_bytes);

  std::string text;
  CHECK(!read_small_file("this/path/does/not/exist", 64, text));
  return 0;
}
