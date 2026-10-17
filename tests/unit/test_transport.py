"""Readers: allowlist, error mapping, SSH argument construction, batching, and limits."""

from __future__ import annotations

import shutil
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from axis_memlab.errors import CollectionError, TransportError
from axis_memlab.transport import ReadError, fd_dir_pid, is_allowed_file
from axis_memlab.transport.offline import LocalProcfsReader
from axis_memlab.transport.ssh import RunResult, SshReader, SshSettings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/procfs/basic"


# ---- allowlist -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/proc/meminfo",
        "/proc/vmstat",
        "/proc/pressure/memory",
        "/proc/sys/kernel/osrelease",
        "/proc/4242/status",
        "/proc/4242/smaps_rollup",
        "/proc/4242/cgroup",
        "/sys/fs/cgroup/memory.current",
        "/sys/fs/cgroup/app.slice/svc/memory.events",
        "/sys/fs/cgroup/memory/app/memory.usage_in_bytes",
    ],
)
def test_allowed_paths(path: str) -> None:
    assert is_allowed_file(path)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/proc/4242/environ",  # may contain secrets
        "/proc/4242/cmdline",  # may contain secrets
        "/proc/4242/maps",
        "/proc/4242/smaps",  # deep capture is not allowed
        "/proc/self/status",
        "/proc/../etc/passwd",
        "/proc/meminfo; rm -rf /",
        "/proc/meminfo $(id)",
        "/proc/4242/status\n/etc/passwd",
        "/sys/fs/cgroup/../../etc/shadow/memory.current",
        "/sys/fs/cgroup/a b/memory.current",
        "proc/meminfo",
        "",
    ],
)
def test_refused_paths(path: str) -> None:
    assert not is_allowed_file(path)


def test_fd_dir_pid() -> None:
    assert fd_dir_pid("/proc/12/fd") == 12
    assert fd_dir_pid("/proc/12/fd/3") is None
    assert fd_dir_pid("/proc/x/fd") is None


# ---- local reader ----------------------------------------------------------------------------
def test_local_reader_reads_fixture_and_scans_comm() -> None:
    reader = LocalProcfsReader(FIXTURE)
    assert "MemTotal" in reader.read_text("/proc/meminfo")
    assert reader.scan_comm() == {4242: "synthetic_app", 4243: "other_app"}
    assert set(reader.read_fd_targets(4242)) == {"0", "1", "3", "4", "5", "6", "7"}


def test_local_reader_error_codes(tmp_path: Path) -> None:
    reader = LocalProcfsReader(tmp_path)
    with pytest.raises(ReadError) as missing:
        reader.read_text("/proc/meminfo")
    assert missing.value.code == "missing"
    with pytest.raises(ReadError) as refused:
        reader.read_text("/etc/passwd")
    assert refused.value.code == "unsupported"
    with pytest.raises(ReadError) as fd_missing:
        reader.read_fd_targets(1)
    assert fd_missing.value.code == "missing"


def test_local_reader_byte_cap(tmp_path: Path) -> None:
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc/meminfo").write_text("x" * 2000)
    with pytest.raises(ReadError) as err:
        LocalProcfsReader(tmp_path, max_bytes=1000).read_text("/proc/meminfo")
    assert err.value.code == "not_collected"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_local_reader_permission_denied(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shutil.copytree(FIXTURE, root)
    target = root / "proc/vmstat"
    target.chmod(0)
    try:
        with pytest.raises(ReadError) as err:
            LocalProcfsReader(root).read_text("/proc/vmstat")
        if err.value.code != "permission_denied":  # running as root ignores modes
            pytest.skip("permissions are not enforced for this user")
    except Exception:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
        raise
    target.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_local_reader_read_many_mixes_values_and_errors() -> None:
    got = LocalProcfsReader(FIXTURE).read_many(["/proc/meminfo", "/proc/4242/smaps_rollup"])
    assert isinstance(got["/proc/meminfo"], str)
    modified = LocalProcfsReader(FIXTURE / "nowhere").read_many(["/proc/meminfo"])
    assert isinstance(modified["/proc/meminfo"], ReadError)


# ---- ssh reader ------------------------------------------------------------------------------
class FakeRunner:
    def __init__(self, result: RunResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, argv: Sequence[str], timeout: float) -> RunResult:
        self.calls.append((list(argv), timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _reader(runner: FakeRunner, **kw: object) -> SshReader:
    return SshReader(SshSettings(target="svc@camera.example", **kw), runner)  # type: ignore[arg-type]


def test_ssh_argv_is_hardened_and_has_no_shell() -> None:
    runner = FakeRunner(RunResult(0, b"MemTotal: 1 kB\n", b""))
    reader = _reader(
        runner,
        port=2222,
        identity_file=Path("/keys/id"),
        known_hosts_file=Path("/keys/kh"),
        connect_timeout_seconds=3,
        command_timeout_seconds=4,
    )
    assert reader.read_text("/proc/meminfo").startswith("MemTotal")
    argv, timeout = runner.calls[0]
    assert argv[0] == "ssh" and timeout == 7.0
    joined = " ".join(argv)
    for required in (
        "BatchMode=yes",
        "StrictHostKeyChecking=yes",
        "ConnectTimeout=3",
        "ForwardAgent=no",
        "ClearAllForwardings=yes",
        "IdentitiesOnly=yes",
        f"UserKnownHostsFile={Path('/keys/kh')}",
        "-p 2222",
        f"-i {Path('/keys/id')}",
    ):
        assert required in joined
    assert "StrictHostKeyChecking=no" not in joined and "UserKnownHostsFile=/dev/null" not in joined
    assert argv[-2] == "svc@camera.example" and argv[-1] == "cat /proc/meminfo"


@pytest.mark.parametrize(
    "target",
    ["-oProxyCommand=evil", "host name", "user@host;id", "", "-p", "a@b@c", "host$(x)"],
)
def test_ssh_target_injection_is_refused(target: str) -> None:
    with pytest.raises(CollectionError):
        SshReader(SshSettings(target=target), FakeRunner(RunResult(0, b"", b"")))


def test_ssh_option_values_are_validated() -> None:
    with pytest.raises(CollectionError):
        SshSettings(target="h", port=0).validate()
    with pytest.raises(CollectionError):
        SshSettings(target="h", identity_file=Path("-oBad")).validate()


def test_ssh_never_runs_a_non_allowlisted_path() -> None:
    runner = FakeRunner(RunResult(0, b"", b""))
    reader = _reader(runner)
    for call in (
        lambda: reader.read_text("/etc/passwd"),
        lambda: reader.read_many(["/proc/meminfo", "/proc/1/environ"]),
        lambda: reader.read_text("/proc/meminfo; id"),
    ):
        with pytest.raises(ReadError):
            call()
    assert runner.calls == []


def test_ssh_failure_mapping() -> None:
    cases = [
        (b"cat: can't open '/proc/x': No such file or directory", "missing"),
        (b"cat: /proc/x: Permission denied", "permission_denied"),
        (b"weird", "unsupported"),
    ]
    for stderr, code in cases:
        with pytest.raises(ReadError) as err:
            _reader(FakeRunner(RunResult(1, b"", stderr))).read_text("/proc/meminfo")
        assert err.value.code == code


def test_ssh_connection_failure_is_a_transport_error_without_leaking_noise() -> None:
    runner = FakeRunner(RunResult(255, b"", b"Host key verification failed.\n\x1b[31mred\n"))
    with pytest.raises(TransportError) as err:
        _reader(runner).read_text("/proc/meminfo")
    assert "Host key verification failed" in str(err.value)
    assert "\x1b" not in str(err.value)


def test_ssh_timeout_and_missing_client() -> None:
    with pytest.raises(ReadError) as err:
        _reader(FakeRunner(ReadError("timeout", "slow"))).read_text("/proc/meminfo")
    assert err.value.code == "timeout"
    from axis_memlab.transport.ssh import default_runner

    with pytest.raises(TransportError):
        default_runner(["definitely-not-an-ssh-binary-xyz"], 1.0)


def test_ssh_output_cap() -> None:
    runner = FakeRunner(RunResult(0, b"x" * 100, b""))
    with pytest.raises(ReadError) as err:
        _reader(runner, max_bytes=10).read_text("/proc/meminfo")
    assert err.value.code == "not_collected"


def test_ssh_batch_parsing_one_round_trip() -> None:
    stdout = (
        b"@@AXMEM /proc/meminfo\nMemTotal: 1 kB\n\n@@AXMEM-RC 0\n"
        b"@@AXMEM /proc/vmstat\ncat: can't open '/proc/vmstat': No such file or directory\n"
        b"\n@@AXMEM-RC 1\n"
        b"@@AXMEM /proc/pressure/memory\n\n@@AXMEM-RC 0\n"
    )
    runner = FakeRunner(RunResult(0, stdout, b""))
    got = _reader(runner).read_many(
        ["/proc/meminfo", "/proc/vmstat", "/proc/pressure/memory", "/proc/4/status"]
    )
    assert len(runner.calls) == 1  # one SSH connection for the whole batch
    assert got["/proc/meminfo"] == "MemTotal: 1 kB\n"
    assert isinstance(got["/proc/vmstat"], ReadError) and got["/proc/vmstat"].code == "missing"  # type: ignore[union-attr]
    assert got["/proc/pressure/memory"] == ""  # an empty file is a value
    lost = got["/proc/4/status"]
    assert isinstance(lost, ReadError) and lost.code == "parse_error"


def test_ssh_fd_listing_and_comm_scan() -> None:
    listing = b"total 0\nlrwx------ 1 u g 64 Jan 1 00:00 3 -> socket:[9]\n"
    assert _reader(FakeRunner(RunResult(0, listing, b""))).read_fd_targets(7) == {"3": "socket:[9]"}
    with pytest.raises(ReadError) as err:
        _reader(
            FakeRunner(RunResult(1, b"ls: /proc/7/fd: Permission denied\n", b""))
        ).read_fd_targets(7)
    assert err.value.code == "permission_denied"
    comm = b"/proc/10/comm app\n/proc/11/comm  other \nnoise\n"
    assert _reader(FakeRunner(RunResult(0, comm, b""))).scan_comm() == {10: "app", 11: "other"}


def test_ssh_describe_does_not_contain_the_host() -> None:
    assert "camera" not in _reader(FakeRunner(RunResult(0, b"", b""))).describe()


@pytest.mark.skipif(shutil.which("ssh") is None, reason="OpenSSH client not installed")
def test_real_openssh_accepts_the_options_and_resolves_them_as_hardened(tmp_path: Path) -> None:
    import subprocess

    key = tmp_path / "key"
    key.write_text("not a real key")
    hosts = tmp_path / "known_hosts"
    hosts.write_text("")
    reader = SshReader(
        SshSettings(
            target="svc@camera.example",
            port=2222,
            identity_file=key,
            known_hosts_file=hosts,
            connect_timeout_seconds=3,
        ),
        FakeRunner(RunResult(0, b"", b"")),
    )
    argv = reader._argv("cat /proc/meminfo")
    argv.insert(1, "-G")  # print the effective configuration; makes no connection
    done = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)
    assert done.returncode == 0, done.stderr
    config = {
        line.split(" ", 1)[0]: line.split(" ", 1)[1]
        for line in done.stdout.splitlines()
        if " " in line
    }
    assert config["stricthostkeychecking"] == "true"
    assert config["batchmode"] == "yes"
    assert config["forwardagent"] == "no"
    assert config["identitiesonly"] == "yes"
    assert config["connecttimeout"] == "3"
    assert config["port"] == "2222"
    assert config["user"] == "svc" and config["hostname"] == "camera.example"
