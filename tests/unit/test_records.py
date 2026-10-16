"""Schema and record serialization tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from axis_memlab.records import Metric, Record

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "tests/fixtures/runs/sample-run"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((ROOT / "schemas" / name).read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_schema_documents_and_valid_fixtures() -> None:
    for schema_file in (ROOT / "schemas").glob("*.schema.json"):
        schema = json.loads(schema_file.read_text())
        Draft202012Validator.check_schema(schema)
    manifest = json.loads((RUN / "manifest.json").read_text())
    assert not list(_validator("run-manifest-v1.schema.json").iter_errors(manifest))
    validator = _validator("record-v1.schema.json")
    records = [json.loads(line) for line in (RUN / "records.jsonl").read_text().splitlines()]
    assert len(records) == 3
    assert all(not list(validator.iter_errors(record)) for record in records)
    assert records[1]["metrics"]["system.mem.available_bytes"]["value"] == 0
    assert records[1]["metrics"]["process.pss_bytes"]["available"] is False


def test_invalid_fixture_reports_metric_path() -> None:
    validator = _validator("record-v1.schema.json")
    bad_record = json.loads((ROOT / "tests/fixtures/corrupt/invalid-record.json").read_text())
    error = next(validator.iter_errors(bad_record))
    assert list(error.absolute_path) == ["metrics", "process.pss_bytes"]


def test_record_roundtrip_preserves_zero_and_unavailable() -> None:
    record = Record(
        record_type="sample",
        run_id="00000000-0000-4000-8000-000000000001",
        producer="synthetic-test",
        ts_utc_ns=123,
        ts_mono_ns=None,
        identity={"device_id": "synthetic-device"},
        metrics={
            "system.mem.available_bytes": Metric(value=0, unit="bytes", source="synthetic"),
            "process.pss_bytes": Metric(available=False, reason="unsupported in fixture"),
        },
    )
    parsed = json.loads(record.to_json())
    assert parsed["schema_version"] == 1
    assert parsed["ts_utc_ns"] == 123
    assert parsed["metrics"]["system.mem.available_bytes"]["value"] == 0
    assert parsed["metrics"]["system.mem.available_bytes"]["unit"] == "bytes"
    assert parsed["metrics"]["process.pss_bytes"] == {
        "available": False,
        "reason": "unsupported in fixture",
    }
    assert not list(_validator("record-v1.schema.json").iter_errors(parsed))


def test_unavailable_requires_reason() -> None:
    with pytest.raises(ValueError, match="require a reason"):
        Metric(available=False).as_dict()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_record_rejects_non_finite_metric_values(value: float) -> None:
    record = Record(
        record_type="sample",
        run_id="00000000-0000-4000-8000-000000000001",
        producer="synthetic-test",
        ts_utc_ns=123,
        ts_mono_ns=None,
        identity={},
        metrics={"test.metric": Metric(value=value, unit="bytes", source="synthetic")},
    )
    with pytest.raises(ValueError):
        record.to_json()


def test_boolean_is_not_accepted_as_timestamp() -> None:
    record = Record(
        record_type="sample",
        run_id="00000000-0000-4000-8000-000000000001",
        producer="synthetic-test",
        ts_utc_ns=True,
        ts_mono_ns=None,
        identity={"device_id": "synthetic-device"},
        metrics={},
    )
    with pytest.raises(ValueError, match="ts_utc_ns"):
        record.as_dict()


def test_byte_metrics_require_bytes_unit() -> None:
    validator = _validator("record-v1.schema.json")
    record = json.loads((RUN / "records.jsonl").read_text().splitlines()[1])
    record["metrics"]["process.rss_anon_bytes"]["unit"] = "KiB"
    assert any(
        list(error.absolute_path) == ["metrics", "process.rss_anon_bytes", "unit"]
        for error in validator.iter_errors(record)
    )
