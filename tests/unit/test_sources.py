"""Parsers: kernel variations, unit conversion, zero versus unavailable, malformed input."""

from __future__ import annotations

from pathlib import Path

import pytest

from axis_memlab.sources import cgroup, fd, meminfo, proc_status, psi, smaps, vmstat
from axis_memlab.sources.common import parse_kb, unavailable

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/procfs/basic"


def _read(rel: str) -> str:
    return (FIXTURE / rel).read_text(encoding="utf-8")


def _value(metrics: dict, name: str) -> int | float:  # type: ignore[type-arg]
    metric = metrics[name]
    assert metric.available, f"{name}: {metric.reason}"
    return metric.value  # type: ignore[no-any-return]


# ---- units ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [("1 kB", 1024), ("0 kB", 0), ("  262144   kB ", 262144 * 1024)],
)
def test_kb_is_1024_bytes_and_zero_is_a_value(text: str, expected: int) -> None:
    assert parse_kb(text) == expected


@pytest.mark.parametrize("text", ["12", "12 MB", "-1 kB", "1.5 kB", "kB", "", "1 2 kB"])
def test_unitless_or_odd_sizes_are_refused_not_guessed(text: str) -> None:
    assert parse_kb(text) is None


def test_unknown_reason_code_is_rejected() -> None:
    with pytest.raises(ValueError):
        unavailable("whatever", "x")


# ---- meminfo -------------------------------------------------------------------------------
def test_meminfo_fixture() -> None:
    m = meminfo.parse(_read("proc/meminfo"))
    assert _value(m, "system.mem.total_bytes") == 262144 * 1024
    assert _value(m, "system.mem.available_bytes") == 98304 * 1024
    assert _value(m, "system.mem.swap_total_bytes") == 0  # a real zero
    assert m["system.mem.available_bytes"].unit == "bytes"


def test_meminfo_without_memavailable_is_unsupported_not_zero() -> None:
    text = "MemTotal: 1000 kB\nMemFree: 500 kB\n"
    m = meminfo.parse(text)
    missing = m["system.mem.available_bytes"]
    assert not missing.available and missing.reason_code == "unsupported"
    assert _value(m, "system.mem.free_bytes") == 500 * 1024


def test_meminfo_field_order_whitespace_and_crlf() -> None:
    text = "Cached:\t 8 kB\r\nMemTotal:      4 kB\r\nMemFree: 2 kB \r\n"
    m = meminfo.parse(text)
    assert _value(m, "system.mem.cached_bytes") == 8 * 1024
    assert _value(m, "system.mem.total_bytes") == 4 * 1024


@pytest.mark.parametrize("text", ["", "garbage\n", "<html>no</html>"])
def test_meminfo_garbage_is_parse_error_everywhere(text: str) -> None:
    m = meminfo.parse(text)
    assert all(not x.available and x.reason_code == "parse_error" for x in m.values())


def test_meminfo_bad_value_only_affects_that_field() -> None:
    m = meminfo.parse("MemTotal: lots kB\nMemFree: 2 kB\n")
    assert m["system.mem.total_bytes"].reason_code == "parse_error"
    assert _value(m, "system.mem.free_bytes") == 2048


# ---- vmstat / psi ----------------------------------------------------------------------------
def test_vmstat_fixture_and_missing_counters() -> None:
    m = vmstat.parse(_read("proc/vmstat"))
    assert _value(m, "system.vmstat.pgfault_count") == 123456
    assert m["system.vmstat.slab_unreclaimable_pages"].unit == "pages"
    sparse = vmstat.parse("pgfault 5\n")
    assert sparse["system.vmstat.oom_kill_count"].reason_code == "unsupported"
    assert _value(sparse, "system.vmstat.pgfault_count") == 5


def test_vmstat_empty_is_parse_error() -> None:
    assert vmstat.parse("")["system.vmstat.pgfault_count"].reason_code == "parse_error"


def test_psi_fixture() -> None:
    m = psi.parse(_read("proc/pressure/memory"))
    assert _value(m, "system.psi.memory_some_avg10_percent") == pytest.approx(0.12)
    assert _value(m, "system.psi.memory_full_total_us") == 123
    assert m["system.psi.memory_some_total_us"].unit == "microseconds"


def test_psi_only_some_line_marks_full_unsupported() -> None:
    m = psi.parse("some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
    assert _value(m, "system.psi.memory_some_total_us") == 0
    assert m["system.psi.memory_full_total_us"].reason_code == "unsupported"


def test_psi_garbage() -> None:
    assert psi.parse("nope")["system.psi.memory_some_avg10_percent"].reason_code == "parse_error"


# ---- process ---------------------------------------------------------------------------------
def test_status_fixture() -> None:
    m = proc_status.parse_status(_read("proc/4242/status"))
    assert _value(m, "process.rss_anon_bytes") == 30720 * 1024
    assert _value(m, "process.vm_swap_bytes") == 0
    assert _value(m, "process.threads_count") == 8
    assert "Name" not in str(m)  # the command name is not copied into metrics


def test_status_older_kernel_without_rss_breakdown() -> None:
    m = proc_status.parse_status("VmRSS:\t 100 kB\nThreads:\t3\n")
    assert m["process.rss_anon_bytes"].reason_code == "unsupported"
    assert _value(m, "process.rss_bytes") == 100 * 1024


def test_status_is_not_confused_by_pid_in_name_or_other_keys() -> None:
    text = "Name:\tVmRSS: 1 kB\nVmRSS:\t 7 kB\nThreads:\t2\n"
    assert _value(proc_status.parse_status(text), "process.rss_bytes") == 7 * 1024


def test_stat_fixture_and_start_ticks() -> None:
    text = _read("proc/4242/stat")
    assert proc_status.parse_start_ticks(text) == 987654
    m = proc_status.parse_stat(text)
    assert _value(m, "process.minor_faults_count") == 1500
    assert _value(m, "process.cpu_user_ticks") == 350
    assert m["process.cpu_user_ticks"].unit == "ticks"


def test_stat_with_spaces_and_parentheses_in_command_name() -> None:
    text = "7 (a) b (c)) S 1 7 7 0 -1 0 11 0 22 0 33 44 0 0 20 0 1 0 555 1 2\n"
    assert proc_status.parse_start_ticks(text) == 555
    assert _value(proc_status.parse_stat(text), "process.major_faults_count") == 22


@pytest.mark.parametrize("text", ["", "no paren", "1 (x) S 1 2"])
def test_truncated_stat(text: str) -> None:
    assert proc_status.parse_start_ticks(text) is None
    assert all(not m.available for m in proc_status.parse_stat(text).values())


def test_smaps_rollup_fixture_uss_and_exact_key_match() -> None:
    m = smaps.parse(_read("proc/4242/smaps_rollup"))
    assert _value(m, "process.pss_bytes") == 6000 * 1024  # not Pss_Anon (4000)
    assert _value(m, "process.private_dirty_bytes") == 5000 * 1024
    assert _value(m, "process.uss_approx_bytes") == (1500 + 5000) * 1024
    assert _value(m, "process.swap_bytes") == 0


def test_smaps_rollup_missing_fields_do_not_invent_uss() -> None:
    m = smaps.parse("Pss: 10 kB\nPrivate_Clean: 4 kB\n")
    assert m["process.uss_approx_bytes"].reason_code == "unsupported"
    assert _value(m, "process.pss_bytes") == 10 * 1024


def test_smaps_rollup_garbage() -> None:
    assert smaps.parse("???")["process.pss_bytes"].reason_code == "parse_error"


# ---- fd --------------------------------------------------------------------------------------
def test_fd_listing_and_classes() -> None:
    targets = fd.parse_ls_long(_read("proc/4242/fd.ls"))
    assert set(targets) == {"0", "1", "3", "4", "5", "6", "7"}
    m = fd.metrics(targets)
    assert _value(m, "process.fd_count") == 7
    assert _value(m, "process.fd_dmabuf_count") == 2
    assert _value(m, "process.fd_socket_count") == 1
    assert _value(m, "process.fd_pipe_count") == 1
    assert _value(m, "process.fd_anon_inode_other_count") == 1
    assert _value(m, "process.fd_file_count") == 2  # /dev/null and the library
    assert sum(_value(m, f"process.fd_{c}_count") for c in fd.CLASSES) == 7


def test_fd_targets_are_not_stored_in_metrics() -> None:
    text = str(fd.metrics({"3": "socket:[12345]", "4": "/home/someone/secret.txt"}))
    assert "12345" not in text and "secret" not in text


def test_fd_deleted_and_empty() -> None:
    assert fd.classify("/dev/shm/x (deleted)") == "file"
    assert fd.classify("/dmabuf:video") == "dmabuf"
    assert _value(fd.metrics({}), "process.fd_count") == 0  # an empty fd table is a real zero
    assert fd.parse_ls_long("ls: cannot access") == {}


# ---- cgroup ----------------------------------------------------------------------------------
def test_cgroup_v2_paths_and_values() -> None:
    assert cgroup.parse_proc_cgroup("0::/synthetic.slice\n") == (2, "/synthetic.slice")
    files = cgroup.files_for(2, "/synthetic.slice")
    assert files["current"] == "/sys/fs/cgroup/synthetic.slice/memory.current"
    texts = {
        "current": _read("sys/fs/cgroup/synthetic.slice/memory.current"),
        "limit": "max\n",
        "events": _read("sys/fs/cgroup/synthetic.slice/memory.events"),
    }
    m = cgroup.parse(2, texts)
    assert _value(m, cgroup.CURRENT) == 41943040
    assert m[cgroup.LIMIT].reason_code == "unsupported"  # "max" is no limit, not a number
    assert _value(m, cgroup.OOM_KILL) == 0


def test_cgroup_v1_and_unlimited() -> None:
    assert cgroup.parse_proc_cgroup("4:memory:/app\n3:cpu:/x\n") == (1, "/app")
    files = cgroup.files_for(1, "/app")
    assert files["current"] == "/sys/fs/cgroup/memory/app/memory.usage_in_bytes"
    m = cgroup.parse(1, {"current": "1000\n", "limit": "9223372036854771712\n"})
    assert _value(m, cgroup.CURRENT) == 1000
    assert m[cgroup.LIMIT].reason_code == "unsupported"
    assert m[cgroup.OOM_KILL].reason_code == "unsupported"


@pytest.mark.parametrize("text", ["0::/../../etc\n", "0::/a b\n", "garbage\n", ""])
def test_cgroup_hostile_or_unusable_paths_are_refused(text: str) -> None:
    assert cgroup.parse_proc_cgroup(text) is None


def test_every_parser_metric_is_in_the_documented_registry() -> None:
    docs = (FIXTURE.parents[3] / "docs/03-metrics-semantics.md").read_text(encoding="utf-8")
    names = [
        *meminfo.metric_names(),
        *vmstat.metric_names(),
        *psi.metric_names(),
        *proc_status.status_metric_names(),
        *proc_status.stat_metric_names(),
        *smaps.metric_names(),
        *fd.metric_names(),
        *cgroup.metric_names(),
        "collector.cycle_duration_ns",
        "collector.reads_total_count",
        "collector.read_errors_count",
        "collector.bytes_read_bytes",
    ]
    missing = [n for n in names if f"`{n}`" not in docs]
    assert not missing, f"undocumented metrics: {missing}"
