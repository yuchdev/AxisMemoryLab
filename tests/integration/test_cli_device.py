"""End to end through the CLI: fixture procfs and a fake `ssh` that emulates a remote shell."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from axis_memlab.cli import main

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/procfs/basic"
CONFIG = ROOT / "configs/default.toml"
SCHEMA = json.loads((ROOT / "schemas/record-v1.schema.json").read_text())
MANIFEST_SCHEMA = json.loads((ROOT / "schemas/run-manifest-v1.schema.json").read_text())
COMMON = [
    "--device-id",
    "demo-device-1",
    "--scenario",
    "unit",
    "--privacy-classification",
    "synthetic",
]


def _run_dir(out: Path) -> Path:
    dirs = [p for p in out.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def _records(run: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (run / "records.jsonl").read_text().splitlines()]


def _assert_valid(run: Path) -> None:
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    for number, record in enumerate(_records(run), start=1):
        errors = list(validator.iter_errors(record))
        assert not errors, f"line {number}: {errors[0].message}"
    manifest = json.loads((run / "manifest.json").read_text())
    Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker()).validate(manifest)


def _collect(out: Path, *extra: str, source: list[str] | None = None) -> int:
    where = source or ["--procfs-root", str(FIXTURE), "--app", "synthetic_app"]
    return main(["collect", *where, "--config", str(CONFIG), "--out", str(out), *COMMON, *extra])


# ---- discover --------------------------------------------------------------------------------
def test_discover_json_and_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discover", "--procfs-root", str(FIXTURE), "--pid", "4242", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {c["state"] for c in data["capabilities"]} == {"available"}
    assert "not_probed" in data and data["facts"]["pid"] == 4242
    assert main(["discover", "--procfs-root", str(FIXTURE), "--app", "synthetic_app"]) == 0
    assert "process_status" in capsys.readouterr().out


def test_discover_bad_selection_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discover", "--procfs-root", str(FIXTURE), "--app", "nothing"]) == 2
    assert "no visible process" in capsys.readouterr().err
    with pytest.raises(SystemExit) as both:
        main(["discover", "--procfs-root", str(FIXTURE), "--pid", "1", "--app", "x"])
    assert both.value.code == 2
    with pytest.raises(SystemExit) as neither:
        main(["discover"])
    assert neither.value.code == 2


# ---- collect ---------------------------------------------------------------------------------
def test_collect_offline_produces_valid_records_and_is_analysable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "runs"
    code = _collect(out, "--max-samples", "6", "--no-wait", "--camera-model", "synthetic-model",
                    "--workload-fps", "15", "--workload-resolution", "1920x1080")  # fmt: skip
    summary = json.loads(capsys.readouterr().out)
    assert code == 0 and summary["status"] == "complete" and summary["samples"] == 6
    run = _run_dir(out)
    _assert_valid(run)
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["workload"] == {"fps": 15.0, "resolution": "1920x1080"}
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["config_sha256"])
    assert manifest["status"] == "complete" and manifest["device_identity"] == "demo-device-1"
    assert main(["analyze", "--run", str(run), "--config", str(CONFIG)]) == 0
    assert "limitations" in capsys.readouterr().out


def test_collect_records_missing_sources_and_still_validates(tmp_path: Path) -> None:
    root = tmp_path / "proc-root"
    shutil.copytree(FIXTURE, root)
    (root / "proc/pressure/memory").unlink()
    (root / "proc/4242/smaps_rollup").unlink()
    out = tmp_path / "runs"
    assert _collect(out, "--max-samples", "3", "--no-wait", source=["--procfs-root", str(root), "--pid", "4242"]) == 0  # fmt: skip
    run = _run_dir(out)
    _assert_valid(run)
    records = _records(run)
    states = {r["annotations"]["capability"]: r["annotations"]["state"] for r in records if r["record_type"] == "capability"}  # fmt: skip
    assert states["pressure_memory"] == "missing" and states["process_smaps_rollup"] == "missing"
    first = next(r for r in records if r["record_type"] == "sample")
    assert first["metrics"]["process.pss_bytes"]["reason_code"] == "missing"
    assert {r["annotations"]["source"] for r in records if r["record_type"] == "error"} == {"psi", "smaps_rollup"}  # fmt: skip


def test_collect_refuses_unsafe_or_unbounded_requests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "runs"
    assert _collect(out, "--no-wait") == 2  # no bound
    assert "bounded" in capsys.readouterr().err
    bad = ["--device-id", "10.1.2.3", "--scenario", "s"]
    code = main(["collect", "--procfs-root", str(FIXTURE), "--pid", "4242", "--config", str(CONFIG),
                 "--out", str(out), *bad, "--max-samples", "1"])  # fmt: skip
    assert code == 2 and "pseudonym" in capsys.readouterr().err
    inapp = ROOT / "configs/inapp-only.toml"
    code = main(["collect", "--procfs-root", str(FIXTURE), "--pid", "4242", "--config", str(inapp),
                 "--out", str(out), *COMMON, "--max-samples", "1"])  # fmt: skip
    assert code == 2 and "import" in capsys.readouterr().err
    code = main(["collect", "--ssh", "svc@host", "--pid", "1", "--config", str(CONFIG), "--out", str(out),
                 *COMMON, "--max-samples", "1", "--no-wait"])  # fmt: skip
    assert code == 2 and "offline" in capsys.readouterr().err
    assert not out.exists() or not any(out.iterdir())  # nothing was created by refused requests


def test_collect_compress_option(tmp_path: Path) -> None:
    out = tmp_path / "runs"
    assert _collect(out, "--max-samples", "2", "--no-wait", "--compress") == 0
    run = _run_dir(out)
    assert (run / "records.jsonl.gz").exists() and not (run / "records.jsonl").exists()
    assert main(["analyze", "--run", str(run), "--config", str(CONFIG)]) == 0


# ---- through the real SSH reader -------------------------------------------------------------
class FakeSsh:
    """Stands in for the `ssh` binary: checks the hardening flags and emulates the remote shell."""

    def __init__(self, down: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.down = down

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(argv))
        assert argv[0] == "ssh" and kwargs.get("stdin") == subprocess.DEVNULL
        assert "StrictHostKeyChecking=yes" in argv and "BatchMode=yes" in argv
        assert not any("StrictHostKeyChecking=no" in a for a in argv)
        if self.down:
            return subprocess.CompletedProcess(
                argv, 255, b"", b"ssh: connect to host: Connection refused\n"
            )
        command = argv[-1]
        out = self._remote(command)
        return subprocess.CompletedProcess(argv, out[0], out[1], b"")

    @staticmethod
    def _cat(path: str) -> tuple[int, bytes]:
        file = FIXTURE / path.lstrip("/")
        if file.is_file():
            return 0, file.read_bytes()
        return 1, f"cat: can't open '{path}': No such file or directory\n".encode()

    def _remote(self, command: str) -> tuple[int, bytes]:
        if command.startswith("cat /proc") or command.startswith("cat /sys"):
            return self._cat(command.split(" ", 1)[1])
        if command.startswith("for p in "):
            paths = command[len("for p in ") : command.index("; do")].split()
            chunks = b""
            for path in paths:
                rc, body = self._cat(path)
                chunks += f"@@AXMEM {path}\n".encode() + body + f"\n@@AXMEM-RC {rc}\n".encode()
            return 0, chunks
        if command.startswith("ls -l /proc/"):
            pid = command.split("/")[2]
            return 0, (FIXTURE / f"proc/{pid}/fd.ls").read_bytes()
        if command.startswith("for f in /proc/[0-9]*/comm"):
            lines = b"".join(
                f"/proc/{d.name}/comm {(d / 'comm').read_text().strip()}\n".encode()
                for d in sorted((FIXTURE / "proc").iterdir())
                if d.name.isdigit()
            )
            return 0, lines
        raise AssertionError(f"unexpected remote command: {command!r}")


def test_collect_over_ssh_uses_batched_hardened_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSsh()
    monkeypatch.setattr("axis_memlab.transport.ssh.subprocess.run", fake)
    monkeypatch.setattr("axis_memlab.collection.scheduler.time.sleep", lambda _s: None)
    out = tmp_path / "runs"
    code = _collect(out, "--max-samples", "3", source=["--ssh", "svc@camera.example", "--app", "synthetic_app"])  # fmt: skip
    assert code == 0
    _assert_valid(_run_dir(out))
    # discovery (scan, batch, fd, cgroup file) + 3 cycles of one batched read + 1 sparse set
    assert len(fake.calls) <= 12
    commands = [c[-1] for c in fake.calls]
    assert all(c.startswith(("cat /", "for ", "ls -l /proc/")) for c in commands)
    assert not any("camera.example" in str(c) for c in commands)  # host never reaches the remote
    manifest_text = (_run_dir(out) / "manifest.json").read_text() + (_run_dir(out) / "records.jsonl").read_text()  # fmt: skip
    assert "camera.example" not in manifest_text and "svc@" not in manifest_text


def test_unreachable_device_is_exit_5_and_manifest_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("axis_memlab.transport.ssh.subprocess.run", FakeSsh(down=True))
    out = tmp_path / "runs"
    code = _collect(out, "--max-samples", "3", source=["--ssh", "svc@camera.example", "--pid", "4242"])  # fmt: skip
    assert code == 5
    run = _run_dir(out)
    assert json.loads((run / "manifest.json").read_text())["status"] == "failed"
    assert "Connection refused" in capsys.readouterr().out + (run / "records.jsonl").read_text()
    assert main(["discover", "--ssh", "svc@camera.example", "--pid", "1"]) == 5


# ---- annotate / snapshot / import / purge ---------------------------------------------------------
def test_annotate_snapshot_and_deep_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "runs"
    assert _collect(out, "--max-samples", "2", "--no-wait") == 0
    run = _run_dir(out)
    capsys.readouterr()
    before = (run / "records.jsonl").read_bytes()
    assert main(["annotate", "--run", str(run), "--phase", "T2", "--note", "constant fps"]) == 0
    assert main(["annotate", "--run", str(run), "--segment-boundary", "config change"]) == 0
    assert main(["annotate", "--run", str(run)]) == 2
    assert main(["annotate", "--run", str(run), "--phase", "bad phase"]) == 2
    after = (run / "records.jsonl").read_bytes()
    assert after.startswith(before) and after.count(b"\n") == before.count(b"\n") + 2

    snap = [
        "--procfs-root",
        str(FIXTURE),
        "--pid",
        "4242",
        "--run",
        str(run),
        "--config",
        str(CONFIG),
    ]
    assert main(["snapshot", *snap]) == 0
    assert _records(run)[-1]["record_type"] == "sample"
    sizes = (run / "records.jsonl").stat().st_size
    assert main(["snapshot", *snap, "--level", "deep"]) == 3
    assert "not available" in capsys.readouterr().err
    assert (run / "records.jsonl").stat().st_size == sizes  # nothing was captured
    _assert_valid(run)


def test_import_creates_and_appends(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_id = "00000000-0000-4000-8000-0000000000aa"

    def line(ts: int, **over: Any) -> str:
        record = {
            "schema_version": 1, "record_type": "sample", "run_id": run_id, "producer": "axmem-probe",
            "ts_utc_ns": ts, "ts_mono_ns": ts, "identity": {"device_id": "demo-device-1", "pid": 9},
            "metrics": {"app.frames_total_count": {"value": ts, "unit": "count", "source": "axmem_counter"}},
        }  # fmt: skip
        record.update(over)
        return json.dumps(record)

    source = tmp_path / "probe.jsonl"
    source.write_text("\n".join([line(1), line(2), "{broken"]) + "\n")
    out = tmp_path / "runs"
    new = ["import", "--input", str(source), "--run", str(out / "new"), "--out", str(out), *COMMON]
    assert main(new) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["accepted"] == 2 and summary["rejected"][0]["line"] == 3
    run = Path(summary["run_dir"])
    assert run.name == run_id
    _assert_valid(run)
    assert json.loads((run / "manifest.json").read_text())["status"] == "incomplete"  # had rejects
    more = tmp_path / "more.jsonl"
    more.write_text(line(3) + "\n")
    assert main(["import", "--input", str(more), "--run", str(run)]) == 0
    assert len(_records(run)) == 3
    assert main(["analyze", "--run", str(run), "--config", str(CONFIG)]) == 0
    capsys.readouterr()
    nothing = tmp_path / "bad.jsonl"
    nothing.write_text(line(1, run_id="x") + "\n")
    assert main(["import", "--input", str(nothing), "--run", str(run)]) == 4
    assert (
        main(["import", "--input", str(source), "--run", str(tmp_path / "x"), "--scenario", "s"])
        == 2
    )


def test_purge_is_a_dry_run_unless_confirmed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "runs"
    assert _collect(out, "--max-samples", "1", "--no-wait") == 0
    run = _run_dir(out)
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["created_at"] = "2020-01-01T00:00:00Z"
    (run / "manifest.json").write_text(json.dumps(manifest))
    capsys.readouterr()
    assert main(["purge", "--root", str(out), "--older-than-days", "30"]) == 0
    assert "would delete" in capsys.readouterr().out and run.exists()
    assert main(["purge", "--root", str(out), "--older-than-days", "30", "--confirm"]) == 0
    assert not run.exists()
    assert main(["purge", "--root", str(out), "--older-than-days", "0"]) == 2
