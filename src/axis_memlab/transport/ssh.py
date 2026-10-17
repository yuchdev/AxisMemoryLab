"""Read-only SSH reader that drives the system OpenSSH client (``ssh``).

Safety properties, all enforced here rather than left to callers:

* Only allowlisted ``/proc`` and cgroup paths are ever put in a remote command, and only inside
  fixed templates (``cat``, ``ls -l``, one read loop). No caller text reaches the remote shell.
* The local side never uses a shell: ``ssh`` is started with an argument list.
* Host keys are always verified (``StrictHostKeyChecking=yes``); no password prompts
  (``BatchMode=yes``); no agent or port forwarding; the SSH user must already be trusted in
  ``known_hosts``. Nothing here weakens those options.
* Time and size are bounded per call, and connection failures are reported as
  :class:`~axis_memlab.errors.TransportError` so the scheduler can back off instead of hammering
  a camera.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from axis_memlab.errors import CollectionError, TransportError
from axis_memlab.sources import fd as fd_source
from axis_memlab.transport import DEFAULT_MAX_BYTES, ReadError, fd_dir_pid, require_allowed

_TARGET = re.compile(r"^(?:[A-Za-z0-9._-]{1,64}@)?[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
_BATCH_BLOCK = re.compile(r"@@AXMEM (\S+)\n(.*?)\n@@AXMEM-RC (\d+)\n", re.DOTALL)
_COMM_LINE = re.compile(r"^/proc/(\d+)/comm (.*)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_SCAN_COMM_COMMAND = (
    'for f in /proc/[0-9]*/comm; do c=$(cat "$f" 2>/dev/null) && printf "%s %s\\n" "$f" "$c"; done'
)


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


Runner = Callable[[Sequence[str], float], RunResult]


def default_runner(argv: Sequence[str], timeout: float) -> RunResult:
    """Run ``argv`` without a shell. Missing client -> TransportError; timeout -> ReadError."""
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise ReadError("timeout", f"remote command exceeded {timeout:g} s") from None
    except FileNotFoundError:
        raise TransportError("the OpenSSH client 'ssh' was not found on PATH") from None
    return RunResult(done.returncode, done.stdout, done.stderr)


@dataclass(frozen=True)
class SshSettings:
    target: str
    port: int | None = None
    identity_file: Path | None = None
    known_hosts_file: Path | None = None
    connect_timeout_seconds: int = 5
    command_timeout_seconds: int = 10
    max_bytes: int = DEFAULT_MAX_BYTES

    def validate(self) -> None:
        if not _TARGET.match(self.target):
            raise CollectionError("SSH target must look like [user@]host (no options or spaces)")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise CollectionError("SSH port must be between 1 and 65535")
        for field in (self.identity_file, self.known_hosts_file):
            if field is not None and str(field).startswith("-"):
                raise CollectionError("SSH file paths must not start with '-'")


def _sanitize(text: bytes, limit: int = 160) -> str:
    cleaned = _CONTROL.sub(" ", text.decode("utf-8", errors="replace")).strip()
    return cleaned.splitlines()[0][:limit] if cleaned else ""


def _classify_failure(text: str, returncode: int) -> ReadError:
    lowered = text.lower()
    if "no such file" in lowered or "not found" in lowered or "no such process" in lowered:
        return ReadError("missing", "path does not exist on the device")
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return ReadError("permission_denied", "path is not readable by the SSH user")
    return ReadError("unsupported", f"remote read failed (exit {returncode})")


class SshReader:
    def __init__(self, settings: SshSettings, runner: Runner = default_runner) -> None:
        settings.validate()
        self._s = settings
        self._run = runner

    def describe(self) -> str:
        return "ssh"  # deliberately without the host: logs and manifests stay pseudonymous

    def _argv(self, remote_command: str) -> list[str]:
        s = self._s
        argv = [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"ConnectTimeout={s.connect_timeout_seconds}",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
        ]
        if s.port is not None:
            argv += ["-p", str(s.port)]
        if s.identity_file is not None:
            argv += ["-i", str(s.identity_file), "-o", "IdentitiesOnly=yes"]
        if s.known_hosts_file is not None:
            argv += ["-o", f"UserKnownHostsFile={s.known_hosts_file}"]
        return [*argv, s.target, remote_command]

    def _exec(self, remote_command: str) -> RunResult:
        timeout = self._s.connect_timeout_seconds + self._s.command_timeout_seconds
        result = self._run(self._argv(remote_command), float(timeout))
        if result.returncode == 255:  # ssh's own failure: connect, auth, host key
            detail = _sanitize(result.stderr) or "connection failed"
            raise TransportError(f"SSH connection failed: {detail}")
        return result

    def read_text(self, path: str) -> str:
        require_allowed(path)
        result = self._exec(f"cat {path}")
        if result.returncode != 0:
            raise _classify_failure(
                _sanitize(result.stdout + result.stderr, 400), result.returncode
            )
        if len(result.stdout) > self._s.max_bytes:
            raise ReadError("not_collected", f"{path} exceeds the {self._s.max_bytes}-byte cap")
        return result.stdout.decode("utf-8", errors="replace")

    def read_many(self, paths: Iterable[str]) -> dict[str, str | ReadError]:
        wanted = list(dict.fromkeys(paths))
        for path in wanted:
            require_allowed(path)
        if not wanted:
            return {}
        script = (
            f"for p in {' '.join(wanted)}; do "
            'printf "@@AXMEM %s\\n" "$p"; cat "$p" 2>&1; printf "\\n@@AXMEM-RC %s\\n" "$?"; done'
        )
        result = self._exec(script)
        text = result.stdout.decode("utf-8", errors="replace")
        out: dict[str, str | ReadError] = {}
        for path, body, rc in _BATCH_BLOCK.findall(text):
            if path not in wanted or path in out:
                continue
            if int(rc) != 0:
                out[path] = _classify_failure(body, int(rc))
            elif len(body.encode("utf-8")) > self._s.max_bytes:
                out[path] = ReadError("not_collected", f"{path} exceeds the byte cap")
            else:
                out[path] = body
        for path in wanted:
            out.setdefault(path, ReadError("parse_error", "missing section in batched output"))
        return out

    def read_fd_targets(self, pid: int) -> dict[str, str]:
        path = f"/proc/{int(pid)}/fd"
        if fd_dir_pid(path) is None:
            raise ReadError("unsupported", "invalid pid")
        result = self._exec(f"ls -l {path} 2>&1")
        text = result.stdout.decode("utf-8", errors="replace")
        if result.returncode != 0:
            raise _classify_failure(text[:400], result.returncode)
        if len(result.stdout) > self._s.max_bytes:
            raise ReadError("not_collected", "fd listing exceeds the byte cap")
        return fd_source.parse_ls_long(text)

    def scan_comm(self) -> dict[int, str]:
        result = self._exec(_SCAN_COMM_COMMAND)
        text = result.stdout.decode("utf-8", errors="replace")
        found: dict[int, str] = {}
        for line in text.splitlines()[:4096]:
            match = _COMM_LINE.match(line)
            if match:
                found[int(match.group(1))] = match.group(2).strip()
        return found
