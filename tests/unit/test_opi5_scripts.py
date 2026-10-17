"""The Orange Pi 5 deployment scripts: syntax, safety properties, and dry-run behaviour.

They cannot be run for real here (they need an aarch64 board, root, apt, QEMU). What can be
checked offline is that they parse, that they refuse unsafe input, and that the plans they print
contain the protections the guide promises.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "docs/device-optional/opi5"
SCRIPTS = [
    DIR / "provision-host.sh",
    DIR / "build-tools.sh",
    DIR / "run-virtual-camera.sh",
    DIR / "vm/make-image.sh",
    DIR / "vm/run-vm.sh",
]


def _find_shell() -> str | None:
    found = shutil.which("sh") or shutil.which("bash")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Git\usr\bin\sh.exe",
        r"C:\Program Files (x86)\Git\usr\bin\sh.exe",
    ):
        if Path(candidate).exists():  # Git for Windows ships a POSIX shell, often not on PATH
            return candidate
    return None


SH = _find_shell()
KEYGEN = shutil.which("ssh-keygen")

needs_sh = pytest.mark.skipif(SH is None, reason="no POSIX shell available")
needs_keygen = pytest.mark.skipif(KEYGEN is None or SH is None, reason="no ssh-keygen / shell")


def _sh(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert SH is not None
    env = os.environ.copy()
    # A shell found outside PATH (Git for Windows) needs its own tools (sed, grep, awk) on PATH.
    env["PATH"] = str(Path(SH).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [SH, script.as_posix(), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=env,
    )


@pytest.fixture
def keys(tmp_path: Path) -> tuple[Path, Path]:
    assert KEYGEN is not None
    private = tmp_path / "id_test"
    subprocess.run(
        [KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", "someone@example.com", "-f", str(private)],
        check=True,
    )
    return private, private.with_suffix(".pub")


# ---- static properties -------------------------------------------------------------------------
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_strict_and_free_of_dangerous_patterns(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "\nset -eu\n" in text
    assert "\r" not in text, "scripts must use LF line endings"
    for forbidden in ("| sh", "| bash", "curl -k", "--insecure", "chmod 777", "chmod -R 777",
                      "rm -rf /\n", "PasswordAuthentication yes", "PermitRootLogin yes",
                      "0.0.0.0", "StrictHostKeyChecking=no", "StrictHostKeyChecking no"):  # fmt: skip
        assert forbidden not in text, f"{script.name}: {forbidden!r}"
    assert "not run on" in text.lower() or "not been run" in text.lower()  # honest status


def test_user_data_template_has_no_password_and_locks_the_account() -> None:
    text = (DIR / "vm/user-data.template").read_text(encoding="utf-8")
    assert "lock_passwd: true" in text and "ssh_pwauth: false" in text
    assert "sudo: false" in text and "disable_root: true" in text
    assert "PasswordAuthentication no" in text and "AllowTcpForwarding no" in text
    assert not re.search(r"^\s*(passwd|plain_text_passwd|hashed_passwd):", text, re.MULTILINE)
    assert "chpasswd" not in text
    assert text.count("@@PUBKEY@@") == 1


def test_guide_covers_the_required_topics() -> None:
    guide = (ROOT / "docs/device-optional/README.md").read_text(encoding="utf-8")
    for needle in ("Orange Pi 5", "Tier 1", "Tier 2", "Optional and TODO", "KVM", "ProxyJump",
                   "provision-host.sh", "make-image.sh", "run-vm.sh", "run-virtual-camera.sh",
                   "not yet run on real hardware", "docs/13-advanced-diagnostics.md"):  # fmt: skip
        assert needle in guide, needle
    for script in SCRIPTS:
        assert script.name in guide, f"{script.name} is not described in the guide"


# ---- syntax and dry runs ---------------------------------------------------------------------------
@needs_sh
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script: Path) -> None:
    assert SH is not None
    done = subprocess.run(
        [SH, "-n", script.as_posix()], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


@needs_keygen
def test_provision_dry_run_prints_the_protections(tmp_path: Path, keys: tuple[Path, Path]) -> None:
    _, public = keys
    done = _sh(DIR / "provision-host.sh", "--dry-run", "--skip-arch-check", "--pubkey",
               public.as_posix(), "--user", "lab", "--with-vm")  # fmt: skip
    assert done.returncode == 0, done.stderr
    out = done.stdout
    for expected in ("would run: apt-get install", "qemu-system-arm", "would run: useradd",
                     "passwd --lock lab", "Match User lab", "PasswordAuthentication no",
                     "AllowTcpForwarding no", "loginctl enable-linger lab",
                     "/etc/ssh/sshd_config.d/90-axmem-lab.conf"):  # fmt: skip
        assert expected in out, expected
    assert "someone@example.com" not in out  # the key's comment is not echoed
    assert "would run" in out and "\n+ " not in out  # nothing was executed


@needs_keygen
def test_provision_refuses_unsafe_input(tmp_path: Path, keys: tuple[Path, Path]) -> None:
    private, public = keys
    base = ["--dry-run", "--skip-arch-check"]
    script = DIR / "provision-host.sh"
    assert _sh(script, *base, "--pubkey", private.as_posix()).returncode == 2  # a private key
    assert "PRIVATE" in _sh(script, *base, "--pubkey", private.as_posix()).stderr
    assert _sh(script, *base, "--pubkey", public.as_posix(), "--user", "root").returncode == 2
    assert _sh(script, *base, "--pubkey", public.as_posix(), "--user", "Bad Name").returncode == 2
    assert _sh(script, *base).returncode == 2  # no key given
    assert _sh(script, *base, "--pubkey", str(tmp_path / "missing.pub")).returncode == 2
    junk = tmp_path / "junk.pub"
    junk.write_text("not a key\n")
    assert _sh(script, *base, "--pubkey", junk.as_posix()).returncode == 2
    assert _sh(script, "--bogus").returncode == 2


@needs_sh
def test_run_virtual_camera_dry_run_confines_the_process() -> None:
    done = _sh(DIR / "run-virtual-camera.sh", "--dry-run", "--memory", "256M", "--cpus", "2",
               "--", "--defect", "release_miss", "--seconds", "60")  # fmt: skip
    assert done.returncode == 0, done.stderr
    out = done.stdout
    for expected in ("MemoryMax=256M", "MemorySwapMax=0", "NoNewPrivileges=yes", "TasksMax=64",
                     "CPUQuota=200%", "ProtectSystem=strict", "--uid=axmem-lab",
                     "--probe-out", "--sampler-out", "--defect release_miss"):  # fmt: skip
        assert expected in out, expected
    custom = _sh(DIR / "run-virtual-camera.sh", "--dry-run", "--", "--probe-out", "/tmp/x.jsonl")
    assert custom.stdout.count("--probe-out") == 1  # the caller's choice is not duplicated


@needs_sh
def test_run_virtual_camera_refuses_bad_input() -> None:
    script = DIR / "run-virtual-camera.sh"
    assert _sh(script, "--dry-run", "--user", "root").returncode == 2
    assert _sh(script, "--dry-run", "--memory", "5 12").returncode == 2
    assert _sh(script, "--dry-run", "--memory", "lots").returncode == 2
    assert _sh(script, "--dry-run", "--name", "a b;rm").returncode == 2
    assert _sh(script, "--dry-run", "--unknown").returncode == 2


@needs_keygen
def test_make_image_dry_run_renders_user_data_safely(keys: tuple[Path, Path]) -> None:
    _, public = keys
    done = _sh(DIR / "vm/make-image.sh", "--dry-run", "--pubkey", public.as_posix())
    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "ssh-ed25519 AAAA" in out
    assert "someone@example.com" not in out  # only key type and material are copied
    assert "lock_passwd: true" in out and "ssh_pwauth: false" in out
    assert "https://cloud.debian.org/" in out and "SHA512SUMS" in out
    assert "@@PUBKEY@@" not in out
    bad = _sh(DIR / "vm/make-image.sh", "--dry-run", "--pubkey", public.as_posix(),
              "--image-url", "http://example.com/x.qcow2")  # fmt: skip
    assert bad.returncode == 2 and "https" in bad.stderr


@needs_sh
def test_run_vm_dry_run_exposes_ssh_on_loopback_only() -> None:
    done = _sh(DIR / "vm/run-vm.sh", "--dry-run", "--ram", "256M", "--cpus", "1", "--port", "2300")
    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert "hostfwd=tcp:127.0.0.1:2300-:22" in out
    assert "-m 256M" in out and "-smp 1" in out and "-display none" in out
    assert "accelerator:" in out  # says whether it found KVM or fell back to emulation
    assert "0.0.0.0" not in out
    script = DIR / "vm/run-vm.sh"
    assert _sh(script, "--dry-run", "--port", "22").returncode == 2  # privileged port
    assert _sh(script, "--dry-run", "--port", "abc").returncode == 2
    assert _sh(script, "--dry-run", "--ram", "lots").returncode == 2
    background = _sh(script, "--dry-run", "--background")
    assert "-daemonize" in background.stdout and "qemu.pid" in background.stdout
