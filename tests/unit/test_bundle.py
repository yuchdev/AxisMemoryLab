"""Redaction patterns, bundle contents, refusals, and verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axis_memlab.bundle.redact import KINDS, redact, scan
from axis_memlab.cli import main

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/procfs/basic"
CONFIG = ROOT / "configs/default.toml"

LEAKY = """\
host=camera-lobby-3 serial number: ACCC8E123456
ip 192.168.10.44 and fe80::1ff:fe23:4567:890a or 2001:db8::1
mac aa:bb:cc:dd:ee:ff, contact ops.person@example.com
url https://admin:hunter2@10.0.0.9/path
password=hunter2 token: abc123
-----BEGIN RSA PRIVATE KEY-----
MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu
-----END RSA PRIVATE KEY-----
"""


# ---- detection and redaction -------------------------------------------------------------------------
def test_every_kind_is_detected_without_returning_the_text() -> None:
    found = scan(LEAKY)
    for kind in ("private_key", "url_credentials", "secret_assignment", "serial_label",
                 "hostname_label", "email", "mac_address", "ipv6_address", "ipv4_address"):  # fmt: skip
        assert found[kind] >= 1, kind
    assert all(isinstance(v, int) for v in found.values())  # counts only


def test_redaction_removes_the_values_and_rescans_clean() -> None:
    cleaned, counts = redact(LEAKY)
    for secret in ("camera-lobby-3", "ACCC8E123456", "192.168.10.44", "fe80::1ff", "2001:db8::1",
                   "aa:bb:cc:dd:ee:ff", "ops.person@example.com", "hunter2", "abc123",
                   "MIIBOgIBAAJBAKj34"):  # fmt: skip
        assert secret not in cleaned, secret
    assert sum(counts.values()) >= 9
    assert not scan(cleaned)  # placeholders are never re-flagged
    assert "password=[REDACTED-SECRET]" in cleaned  # the label is kept, the value is not


@pytest.mark.parametrize(
    "benign",
    [
        "12:34:56 up 3 days",  # a time of day, not an IPv6 address
        "std::string and axis::memlab::probe",  # C++ scopes
        "AXIS OS 10.11.65 build 2026-01-01",  # three-part version
        "run 00000000-0000-4000-8000-0000000000aa",  # a UUID (lowercase)
        "sha256 " + "ab" * 32,  # a hash
        "version 12.2.50 and 1234567890",  # plain numbers
        "app.resource.frame.in_flight_count = 123456",
    ],
)
def test_ordinary_text_is_not_flagged(benign: str) -> None:
    assert not scan(benign), benign


def test_protected_strings_survive_redaction() -> None:
    text = "firmware 11.11.65.7 on host 10.1.2.3"
    cleaned, counts = redact(text, protect={"11.11.65.7"})
    assert "11.11.65.7" in cleaned and "10.1.2.3" not in cleaned
    assert counts["ipv4_address"] == 1
    assert scan(text, protect={"11.11.65.7"})["ipv4_address"] == 1


def test_kinds_are_documented() -> None:
    assert "ipv4_address" in KINDS and "private_key" in KINDS and len(set(KINDS)) == len(KINDS)


# ---- bundle -------------------------------------------------------------------------------------------------
def _run(tmp_path: Path, classification: str = "synthetic") -> Path:
    args = ["collect", "--procfs-root", str(FIXTURE), "--app", "synthetic_app", "--config", str(CONFIG),
            "--out", str(tmp_path / "runs"), "--device-id", "demo-device-1", "--scenario", "unit",
            "--privacy-classification", classification, "--max-samples", "3", "--no-wait",
            "--firmware-version", "99.9.9", "--camera-model", "synthetic-model", "--soc", "synthetic-soc"]  # fmt: skip
    assert main(args) == 0
    return next(p for p in (tmp_path / "runs").iterdir() if p.is_dir())


def _bundle(run: Path, out: Path, *extra: str) -> int:
    return main(["bundle", "--run", str(run), "--config", str(CONFIG), "--out", str(out), *extra])


def test_bundle_contents_hashes_and_verification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run(tmp_path)
    capsys.readouterr()
    out = tmp_path / "bundle"
    assert _bundle(run, out) == 0
    descriptor = json.loads((out / "BUNDLE.json").read_text())
    names = {f["path"] for f in descriptor["files"]}
    assert {"manifest.json", "analysis/report.json", "analysis/report.md", "limitations.md",
            "context/capabilities-errors-events.json", "README.txt"} <= names  # fmt: skip
    assert "records.jsonl" not in names and descriptor["includes_raw_records"] is False
    assert descriptor["run_id"] == json.loads((run / "manifest.json").read_text())["run_id"]
    assert descriptor["review_required"] is True
    assert any("contact" in item for item in descriptor["not_included"])
    assert "sha256" in descriptor["files"][0]
    assert main(["bundle", "--verify", str(out)]) == 0

    (out / "limitations.md").write_text("edited")
    (out / "stray.txt").write_text("not listed")
    capsys.readouterr()
    assert main(["bundle", "--verify", str(out)]) == 4
    err = capsys.readouterr().err
    assert "changed since" in err and "not listed" in err
    assert main(["bundle", "--verify", str(tmp_path / "nothing")]) == 4


def test_bundle_never_overwrites_and_needs_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run(tmp_path)
    out = tmp_path / "bundle"
    assert _bundle(run, out) == 0
    assert _bundle(run, out) == 2 and "already exists" in capsys.readouterr().err
    assert main(["bundle", "--run", str(run)]) == 2
    assert main(["bundle", "--run", str(run), "--out", str(tmp_path / "b2")]) == 2


def test_sensitive_runs_need_a_review_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run(tmp_path, classification="sensitive")
    capsys.readouterr()
    assert _bundle(run, tmp_path / "b1") == 2
    assert "sensitive" in capsys.readouterr().err and not (tmp_path / "b1").exists()
    assert _bundle(run, tmp_path / "b2", "--reviewed") == 0
    assert json.loads((tmp_path / "b2" / "BUNDLE.json").read_text())["reviewed"] is True


def test_identifying_text_blocks_the_bundle_unless_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run(tmp_path)
    report = tmp_path / "server.txt"
    report.write_text("Firmware 99.9.9\n" + LEAKY)
    capsys.readouterr()
    code = _bundle(run, tmp_path / "b1", "--server-report", str(report))
    err = capsys.readouterr().err
    assert code == 2 and "identifying text remains" in err
    assert "server-report.txt" in err and "ipv4_address" in err
    assert "192.168.10.44" not in err and "hunter2" not in err  # the refusal does not leak either
    assert not (tmp_path / "b1").exists()

    assert (
        _bundle(run, tmp_path / "b2", "--server-report", str(report), "--redact-server-report") == 0
    )
    stored = (tmp_path / "b2" / "context" / "server-report.txt").read_text()
    assert "Firmware 99.9.9" in stored  # the run's own firmware is protected from IPv4 redaction
    assert "[REDACTED-IPV4]" in stored and "192.168.10.44" not in stored
    descriptor = json.loads((tmp_path / "b2" / "BUNDLE.json").read_text())
    assert descriptor["redactions"]["ipv4_address"] >= 1
    assert "hunter2" not in json.dumps(descriptor)


def test_context_files_are_scanned_and_can_be_redacted(tmp_path: Path) -> None:
    run = _run(tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text("Steps: connect to 10.9.8.7 and run T2\n")
    assert _bundle(run, tmp_path / "b1", "--plan", str(plan)) == 2
    assert _bundle(run, tmp_path / "b2", "--plan", str(plan), "--redact-context") == 0
    assert "[REDACTED-IPV4]" in (tmp_path / "b2" / "context" / "test-plan.md").read_text()


def test_binary_and_oversized_inputs_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run(tmp_path)
    capsys.readouterr()
    binary = tmp_path / "report.bin"
    binary.write_bytes(b"PK\x03\x04\x00\x00archive")
    assert _bundle(run, tmp_path / "b1", "--server-report", str(binary)) == 2
    assert "binary" in capsys.readouterr().err
    big = tmp_path / "plan.md"
    big.write_text("x" * (300 * 1024))
    assert _bundle(run, tmp_path / "b2", "--plan", str(big)) == 2


def test_raw_records_are_opt_in_and_boot_id_is_hashed(tmp_path: Path) -> None:
    run = _run(tmp_path)
    assert _bundle(run, tmp_path / "b1", "--include-records") == 0
    text = (tmp_path / "b1" / "records.jsonl").read_text()
    assert "11111111-2222-4333-8444-555555555555" not in text  # the fixture's boot id
    assert "hash-" in text and "demo-device-1" in text
    caps = (tmp_path / "b1" / "context" / "capabilities-errors-events.json").read_text()
    assert "11111111-2222-4333-8444-555555555555" not in caps


def test_existing_report_and_evidence_are_included(tmp_path: Path) -> None:
    run = _run(tmp_path)
    report = tmp_path / "report.json"
    assert main(["analyze", "--run", str(run), "--config", str(CONFIG), "--out", str(report)]) == 0
    evidence = tmp_path / "ev.json"
    assert main(["advanced", "evidence", "--run", str(run), "--authorized-by-reference", "INC-9",
                 "--out", str(evidence)]) == 0  # fmt: skip
    out = tmp_path / "bundle"
    assert main(["bundle", "--run", str(run), "--report", str(report), "--evidence", str(evidence),
                 "--out", str(out)]) == 0  # fmt: skip
    assert (out / "context" / "compatibility-evidence.json").is_file()
    assert json.loads((out / "analysis" / "report.json").read_text())["run_references"]
    junk = tmp_path / "junk.json"
    junk.write_text("[]")
    assert (
        main(["bundle", "--run", str(run), "--report", str(junk), "--out", str(tmp_path / "x")])
        == 4
    )
