"""Import device-generated JSON Lines (for example the in-app probe's file) into a run.

Each line is validated against the record contract before it is copied; invalid lines are
reported with their line number and reason and are never written. Values are preserved as
given (no rounding, no unit guessing), and absent values stay explicitly unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from axis_memlab.collection.run_store import RunStore
from axis_memlab.errors import RunDataError

MAX_LINE_BYTES = 1024 * 1024
RECORD_TYPES = {"sample", "event", "capability", "artifact", "error", "run_start", "run_stop"}
_METRIC_NAME = re.compile(r"^(system|process|app|collector)\.[a-z0-9_.]+$")
_TOP_LEVEL = {
    "schema_version",
    "record_type",
    "run_id",
    "producer",
    "ts_utc_ns",
    "ts_mono_ns",
    "identity",
    "metrics",
    "annotations",
    "source_metadata",
}
_REASON_CODES = {
    "missing",
    "permission_denied",
    "timeout",
    "parse_error",
    "unsupported",
    "not_collected",
}


@dataclass
class ImportSummary:
    accepted: int = 0
    rejected: list[tuple[int, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejected": [{"line": n, "reason": why} for n, why in self.rejected],
        }


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def _is_uint(value: Any) -> bool:
    return type(value) is int and value >= 0


def _check_metric(name: str, metric: Any) -> str | None:
    if not _METRIC_NAME.match(name):
        return f"metric name {name!r} is not namespaced"
    if not isinstance(metric, dict):
        return f"metric {name} is not an object"
    if metric.get("available") is False:
        extra = set(metric) - {"available", "reason", "reason_code"}
        if extra or not isinstance(metric.get("reason"), str) or not metric["reason"]:
            return f"unavailable metric {name} needs a reason and nothing else"
        if "reason_code" in metric and metric["reason_code"] not in _REASON_CODES:
            return f"metric {name} has an unknown reason_code"
        return None
    if set(metric) != {"value", "unit", "source"}:
        return f"metric {name} must have exactly value, unit, and source"
    if isinstance(metric["value"], bool) or not isinstance(metric["value"], int | float | str):
        return f"metric {name} has an unsupported value type"
    if not all(isinstance(metric[k], str) and metric[k] for k in ("unit", "source")):
        return f"metric {name} needs a non-empty unit and source"
    if name.endswith("_bytes") and metric["unit"] != "bytes":
        return f"metric {name} must use unit 'bytes'"
    return None


def validate_record(raw: Any, run_id: str, device_id: str) -> str | None:
    """Return a reason the record must be rejected, or ``None`` if it is acceptable."""
    if not isinstance(raw, dict):
        return "not a JSON object"
    if set(raw) - _TOP_LEVEL:
        return f"unknown fields: {', '.join(sorted(set(raw) - _TOP_LEVEL))}"
    if raw.get("schema_version") != 1:
        return "schema_version must be 1"
    if raw.get("record_type") not in RECORD_TYPES:
        return "unknown record_type"
    if raw.get("run_id") != run_id:
        return "run_id does not match this run"
    if not isinstance(raw.get("producer"), str) or not raw["producer"]:
        return "producer is required"
    if not _is_uint(raw.get("ts_utc_ns")):
        return "ts_utc_ns must be a nonnegative integer"
    if raw.get("ts_mono_ns") is not None and not _is_uint(raw["ts_mono_ns"]):
        return "ts_mono_ns must be null or a nonnegative integer"
    identity = raw.get("identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("device_id"), str):
        return "identity.device_id is required"
    if identity["device_id"] != device_id:
        return "identity.device_id does not match the run's device"
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict):
        return "metrics must be an object"
    for name, metric in metrics.items():
        problem = _check_metric(name, metric)
        if problem:
            return problem
    for key in ("annotations", "source_metadata"):
        if key in raw and not isinstance(raw[key], dict):
            return f"{key} must be an object"
    annotations = raw.get("annotations") or {}
    kind = raw["record_type"]
    if kind == "event" and not isinstance(annotations.get("event"), str):
        return "event records need annotations.event"
    if kind == "capability" and not (
        isinstance(annotations.get("capability"), str) and isinstance(annotations.get("state"), str)
    ):
        return "capability records need annotations.capability and state"
    if kind == "error" and not (
        isinstance(annotations.get("source"), str)
        and annotations.get("reason_code") in _REASON_CODES
    ):
        return "error records need annotations.source and a valid reason_code"
    return None


def peek_run_id(path: Path) -> str:
    """The ``run_id`` of the first valid-looking line, used to name a new run."""
    with path.open("rb") as stream:
        for _ in range(1000):
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            try:
                raw = json.loads(line, parse_constant=_reject_constant)
                return str(UUID(str(raw["run_id"])))
            except (ValueError, KeyError, TypeError):
                continue
    raise RunDataError(f"{path}: no record with a valid run_id was found")


def import_records(path: Path, store: RunStore) -> ImportSummary:
    summary = ImportSummary()
    device_id = str(store.manifest["device_identity"])
    with path.open("rb") as stream:
        number = 0
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            number += 1
            if len(line) > MAX_LINE_BYTES:
                summary.rejected.append((number, "line exceeds the 1 MiB limit"))
                while line and not line.endswith(b"\n"):  # skip the rest of the oversized line
                    line = stream.readline(MAX_LINE_BYTES)
                continue
            if not line.strip():
                continue
            try:
                raw = json.loads(line, parse_constant=_reject_constant)
            except (ValueError, UnicodeDecodeError) as exc:
                summary.rejected.append((number, f"invalid JSON: {str(exc)[:80]}"))
                continue
            problem = validate_record(raw, store.run_id, device_id)
            if problem:
                summary.rejected.append((number, problem))
                continue
            store.append(raw)
            summary.accepted += 1
    return summary
