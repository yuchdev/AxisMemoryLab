"""Advanced-diagnostics catalog, evidence record, fail-closed gate, DDH import, and the CLI."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from axis_memlab.advanced.catalog import BY_ID, CATALOG, TOOL_BLOCKED
from axis_memlab.advanced.evidence import check, load_evidence, skeleton
from axis_memlab.cli import main
from axis_memlab.errors import RunDataError
from axis_memlab.sources.ddh import convert, load_mapping, resolve_pointer

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/procfs/basic"
CONFIG = ROOT / "configs/default.toml"
MANIFEST = {
    "run_id": "00000000-0000-4000-8000-0000000000aa",
    "camera_model": "synthetic-model",
    "soc": "synthetic-soc",
    "firmware_version": "99.9.9",
}
CAPS = [{"name": "meminfo", "state": "available"}, {"name": "process_fd", "state": "denied"}]


def _evidence(tmp_path: Path, **over: Any) -> Path:
    data = skeleton(
        manifest=MANIFEST,
        capabilities=CAPS,
        authorized_by_reference="INC-2026-0042",
        lab_unit=over.pop("lab_unit", True),
        developer_mode=over.pop("developer_mode", True),
        account_type="restricted_non_root",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    for diagnostic, status in over.pop("verified", {}).items():
        entry = next(d for d in data["diagnostics"] if d["id"] == diagnostic)
        entry["status"] = status
        entry["method"] = "ran the documented procedure on the lab unit"
    data.update(over)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(data))
    return path


def _by_id(results: list[Any]) -> dict[str, Any]:
    return {r.diagnostic: r for r in results}


# ---- catalog ---------------------------------------------------------------------------------
def test_catalog_is_complete_and_honest() -> None:
    assert len({d.id for d in CATALOG}) == len(CATALOG) == len(BY_ID)
    for d in CATALOG:
        assert d.cannot_show and d.provides and d.risks and d.guide_section, d.id
        assert d.level in (3, 4)
    assert BY_ID["deep_smaps"].tool_support == TOOL_BLOCKED
    assert all(
        BY_ID[i].lab_unit_required for i in ("strace_scoped", "gdbserver", "ebpf", "core_dump")
    )
    assert BY_ID["gdbserver"].developer_mode_required


def test_every_catalog_entry_is_documented_in_the_guide() -> None:
    guide = (ROOT / "docs/13-advanced-diagnostics.md").read_text(encoding="utf-8")
    missing = [d.id for d in CATALOG if f"`{d.id}`" not in guide]
    assert not missing, f"undocumented diagnostics: {missing}"


# ---- evidence record ---------------------------------------------------------------------------------
def test_skeleton_has_every_diagnostic_untested_and_validates(tmp_path: Path) -> None:
    path = _evidence(tmp_path)
    evidence = load_evidence(path)
    assert {d["status"] for d in evidence.data["diagnostics"]} == {"not_tested"}
    assert [d["id"] for d in evidence.data["diagnostics"]] == [d.id for d in CATALOG]
    schema = json.loads((ROOT / "schemas/compat-evidence-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(evidence.data)


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda d: d["device"].pop("firmware_version"), "device.firmware_version"),
        (lambda d: d["device"].__setitem__("lab_unit", "yes"), "lab_unit"),
        (
            lambda d: d.__setitem__("authorized_by_reference", "alice@example.com"),
            "authorized_by_reference",
        ),
        (
            lambda d: d.__setitem__("authorized_by_reference", "Alice Smith"),
            "authorized_by_reference",
        ),
        (lambda d: d.__setitem__("recorded_at", "yesterday"), "recorded_at"),
        (lambda d: d["access"].__setitem__("account_type", "root"), "account_type"),
        (lambda d: d["diagnostics"].append({"id": "nope", "status": "not_tested"}), "known id"),
        (lambda d: d["diagnostics"].append(copy.deepcopy(d["diagnostics"][0])), "twice"),
        (lambda d: d["diagnostics"][0].__setitem__("status", "verified_available"), "no method"),
        (lambda d: d["capabilities"].append({"name": "x", "state": "great"}), "capability"),
        (lambda d: d.pop("limitations"), "limitations"),
    ],
)
def test_invalid_evidence_is_rejected_with_the_reason(
    tmp_path: Path, mutate: Any, fragment: str
) -> None:
    data = json.loads(_evidence(tmp_path).read_text())
    mutate(data)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(RunDataError, match=fragment):
        load_evidence(bad)
    junk = tmp_path / "junk.json"
    junk.write_text("[]")
    with pytest.raises(RunDataError):
        load_evidence(junk)


# ---- the gate ----------------------------------------------------------------------------------------------
def test_everything_is_blocked_until_verified(tmp_path: Path) -> None:
    results = check(load_evidence(_evidence(tmp_path)), now=datetime(2026, 1, 2, tzinfo=UTC))
    assert not any(r.allowed for r in results)
    assert all("not tested" in " ".join(r.reasons) for r in results)


def test_verified_available_allows_and_notes_intrusiveness(tmp_path: Path) -> None:
    evidence = load_evidence(
        _evidence(
            tmp_path,
            verified={"ddh_topics": "verified_available", "strace_scoped": "verified_available"},
        )
    )
    got = _by_id(check(evidence, now=datetime(2026, 1, 2, tzinfo=UTC)))
    assert got["ddh_topics"].allowed and not got["ddh_topics"].reasons
    assert got["strace_scoped"].allowed
    assert any("intrusive" in n for n in got["strace_scoped"].notes)
    assert not got["perf_stat"].allowed


def test_lab_unit_and_developer_mode_are_required_where_declared(tmp_path: Path) -> None:
    verified = {
        i: "verified_available" for i in ("strace_scoped", "gdbserver", "slabinfo", "ddh_topics")
    }
    evidence = load_evidence(
        _evidence(tmp_path, lab_unit=False, developer_mode=False, verified=verified)
    )
    got = _by_id(check(evidence, now=datetime(2026, 1, 2, tzinfo=UTC)))
    assert got["ddh_topics"].allowed  # needs neither
    assert "lab unit" in " ".join(got["strace_scoped"].reasons)
    assert "Developer Mode" in " ".join(got["gdbserver"].reasons)
    assert not got["slabinfo"].allowed


def test_deep_captures_stay_blocked_even_with_evidence(tmp_path: Path) -> None:
    evidence = load_evidence(_evidence(tmp_path, verified={"deep_smaps": "verified_available"}))
    result = _by_id(check(evidence, ["deep_smaps"], now=datetime(2026, 1, 2, tzinfo=UTC)))[
        "deep_smaps"
    ]
    assert not result.allowed and "safety model" in " ".join(result.reasons)


def test_evidence_is_per_firmware_and_verified_unavailable_blocks(tmp_path: Path) -> None:
    evidence = load_evidence(
        _evidence(
            tmp_path, verified={"perf_stat": "verified_available", "ebpf": "verified_unavailable"}
        )
    )
    now = datetime(2026, 1, 2, tzinfo=UTC)
    assert _by_id(check(evidence, ["perf_stat"], for_firmware="99.9.9", now=now))[
        "perf_stat"
    ].allowed
    other = _by_id(check(evidence, ["perf_stat"], for_firmware="100.0.0", now=now))["perf_stat"]
    assert not other.allowed and "never assumed across firmware" in " ".join(other.reasons)
    ebpf = _by_id(check(evidence, ["ebpf"], now=now))["ebpf"]
    assert not ebpf.allowed and "verified unavailable" in " ".join(ebpf.reasons)


def test_stale_evidence_is_flagged_not_silently_trusted(tmp_path: Path) -> None:
    evidence = load_evidence(_evidence(tmp_path, verified={"ddh_topics": "verified_available"}))
    late = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=400)
    result = _by_id(check(evidence, ["ddh_topics"], now=late))["ddh_topics"]
    assert result.allowed and any("older than" in n for n in result.notes)


# ---- DDH ---------------------------------------------------------------------------------------------------
def _mapping(tmp_path: Path, **over: Any) -> Path:
    data: dict[str, Any] = {
        "schema_version": 1,
        "topic": "com.axis.device.memory-utilization.v1",
        "maturity": "alpha",
        "timestamp": {"pointer": "/time", "unit": "unix_ms"},
        "metrics": [
            {
                "pointer": "/data/used",
                "name": "system.ddh.memory_used_bytes",
                "unit": "bytes",
                "scale": 1024,
            },
            {
                "pointer": "/data/percent",
                "name": "system.ddh.memory_utilization_percent",
                "unit": "percent",
            },
        ],
    }
    data.update(over)
    path = tmp_path / "map.json"
    path.write_text(json.dumps(data))
    return path


def test_pointer_resolution() -> None:
    doc = {"a": {"b/c": [10, {"d~": 5}]}}
    assert resolve_pointer(doc, "/a/b~1c/1/d~0") == 5
    assert resolve_pointer(doc, "") == doc
    for bad in ("/a/x", "/a/b~1c/9", "/a/b~1c/x"):
        with pytest.raises(KeyError):
            resolve_pointer(doc, bad)


@pytest.mark.parametrize(
    "over",
    [
        {"schema_version": 2},
        {"topic": ""},
        {"maturity": ""},
        {"timestamp": {"pointer": "time", "unit": "unix_ms"}},
        {"timestamp": {"pointer": "/t", "unit": "fortnights"}},
        {"metrics": []},
        {"metrics": [{"pointer": "/v", "name": "app.not_ddh", "unit": "count"}]},
        {"metrics": [{"pointer": "/v", "name": "system.ddh.x_bytes", "unit": "KiB"}]},
        {"metrics": [{"pointer": "/v", "name": "system.ddh.x", "unit": "count", "scale": 0}]},
    ],
)
def test_bad_mappings_are_rejected(tmp_path: Path, over: dict[str, Any]) -> None:
    with pytest.raises(RunDataError):
        load_mapping(_mapping(tmp_path, **over))


def test_conversion_keeps_provenance_and_never_invents_values(tmp_path: Path) -> None:
    mapping = load_mapping(_mapping(tmp_path))
    run_id = MANIFEST["run_id"]
    record = convert(
        {"time": 1700000000123, "data": {"used": 2048, "percent": 37.5}},
        mapping, run_id=run_id, device_id="demo-1",
    )  # fmt: skip
    assert not isinstance(record, str)
    body = record.as_dict()
    assert body["ts_utc_ns"] == 1700000000123 * 1_000_000 and body["ts_mono_ns"] is None
    assert body["metrics"]["system.ddh.memory_used_bytes"] == {
        "value": 2048 * 1024, "unit": "bytes", "source": "ddh:com.axis.device.memory-utilization.v1",
    }  # fmt: skip
    assert body["source_metadata"]["maturity"] == "alpha"
    assert "not per-process" in body["source_metadata"]["scope"]

    partial = convert(
        {"time": 5, "data": {"percent": "n/a"}}, mapping, run_id=run_id, device_id="d"
    )
    assert not isinstance(partial, str)
    metrics = partial.as_dict()["metrics"]
    assert metrics["system.ddh.memory_used_bytes"]["reason_code"] == "missing"
    assert metrics["system.ddh.memory_utilization_percent"]["reason_code"] == "parse_error"
    boolean = convert({"time": 5, "data": {"used": True, "percent": float("inf")}}, mapping, run_id=run_id, device_id="d")  # fmt: skip
    assert not isinstance(boolean, str)
    assert all(not m["available"] if "available" in m else False for m in boolean.as_dict()["metrics"].values())  # fmt: skip


@pytest.mark.parametrize(
    ("unit", "raw", "expected"),
    [
        ("iso8601", "2026-01-01T00:00:00Z", 1767225600 * 10**9),
        ("unix_s", 2, 2 * 10**9),
        ("unix_ns", 7, 7),
    ],
)
def test_timestamp_units(tmp_path: Path, unit: str, raw: Any, expected: int) -> None:
    mapping = load_mapping(_mapping(tmp_path, timestamp={"pointer": "/t", "unit": unit}))
    record = convert({"t": raw, "data": {}}, mapping, run_id=MANIFEST["run_id"], device_id="d")
    assert not isinstance(record, str) and record.ts_utc_ns == expected
    for bad in (None, "x", True, -1, [1]):
        assert isinstance(
            convert({"t": bad}, mapping, run_id=MANIFEST["run_id"], device_id="d"), str
        )
    assert isinstance(convert({"other": 1}, mapping, run_id=MANIFEST["run_id"], device_id="d"), str)
    assert isinstance(convert([1], mapping, run_id=MANIFEST["run_id"], device_id="d"), str)


# ---- CLI -------------------------------------------------------------------------------------------------------
def _collected_run(
    tmp_path: Path, *, facts: bool = True, classification: str = "synthetic"
) -> Path:
    args = ["collect", "--procfs-root", str(FIXTURE), "--app", "synthetic_app", "--config", str(CONFIG),
            "--out", str(tmp_path / "runs"), "--device-id", "demo-device-1", "--scenario", "unit",
            "--privacy-classification", classification, "--max-samples", "2", "--no-wait"]  # fmt: skip
    if facts:
        args += ["--camera-model", "synthetic-model", "--soc", "synthetic-soc",
                 "--firmware-version", "99.9.9"]  # fmt: skip
    assert main(args) == 0
    return next(p for p in (tmp_path / "runs").iterdir() if p.is_dir())


def test_cli_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["advanced", "list"]) == 0
    assert "deep_smaps" in capsys.readouterr().out
    assert main(["advanced", "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [d["id"] for d in listed] == [d.id for d in CATALOG]


def test_cli_evidence_check_flow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run = _collected_run(tmp_path)
    capsys.readouterr()
    out = tmp_path / "evidence.json"
    base = [
        "advanced",
        "evidence",
        "--run",
        str(run),
        "--authorized-by-reference",
        "INC-1",
        "--out",
        str(out),
    ]
    assert main([*base, "--lab-unit"]) == 0
    assert main(base) == 4  # never overwritten
    data = json.loads(out.read_text())
    assert data["device"]["firmware_version"] == "99.9.9" and data["device"]["lab_unit"] is True
    assert {c["name"] for c in data["capabilities"]} >= {"meminfo", "process_smaps_rollup"}

    capsys.readouterr()
    assert main(["advanced", "check", "--evidence", str(out)]) == 3  # nothing verified yet
    assert "BLOCKED" in capsys.readouterr().out
    entry = next(d for d in data["diagnostics"] if d["id"] == "ddh_topics")
    entry.update(status="verified_available", method="subscribed on the lab unit for 5 minutes")
    out.write_text(json.dumps(data))
    ok = ["advanced", "check", "--evidence", str(out), "--diagnostic", "ddh_topics"]
    assert main(ok) == 0
    assert main([*ok, "--for-firmware", "1.0.0"]) == 3
    capsys.readouterr()
    assert main([*ok, "--json"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert results[0]["diagnostic"] == "ddh_topics" and results[0]["allowed"] is True
    out.write_text("{")
    assert main(["advanced", "check", "--evidence", str(out)]) == 4


def test_cli_evidence_needs_exact_device_facts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _collected_run(tmp_path, facts=False)
    capsys.readouterr()
    code = main(["advanced", "evidence", "--run", str(run), "--authorized-by-reference", "INC-1",
                 "--out", str(tmp_path / "e.json")])  # fmt: skip
    assert code == 2 and "firmware_version" in capsys.readouterr().err
    assert not (tmp_path / "e.json").exists()


def test_cli_import_ddh_appends_valid_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _collected_run(tmp_path)
    capsys.readouterr()
    messages = tmp_path / "ddh.jsonl"
    lines = [
        json.dumps(
            {"time": 1700000000000 + i * 1000, "data": {"used": 100 + i, "percent": 10.0 + i}}
        )
        for i in range(3)
    ]
    messages.write_text("\n".join([*lines, "{broken", json.dumps({"no": "time"})]) + "\n")
    cmd = [
        "advanced",
        "import-ddh",
        "--input",
        str(messages),
        "--mapping",
        str(_mapping(tmp_path)),
        "--run",
        str(run),
    ]
    assert main(cmd) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["accepted"] == 3 and len(report["rejected"]) == 2
    schema = json.loads((ROOT / "schemas/record-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    ddh = [
        json.loads(x)
        for x in (run / "records.jsonl").read_text().splitlines()
        if "axis-memlab-ddh" in x
    ]
    assert len(ddh) == 3
    for record in ddh:
        assert not list(validator.iter_errors(record))
    nothing = tmp_path / "none.jsonl"
    nothing.write_text("{broken\n")
    assert main([*cmd[:3], str(nothing), *cmd[4:]]) == 4
