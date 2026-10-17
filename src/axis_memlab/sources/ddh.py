"""Device Data Hub (DDH) messages -> ``system.ddh.*`` samples, through an explicit mapping.

Axis lists CPU and memory utilization topics for AXIS OS 12 at *alpha* maturity, so their payload
shape may change between releases and this repository has not seen a real one. Nothing about a
topic is therefore hard-coded: the operator supplies a mapping file that says where the timestamp
and each value live (RFC 6901 JSON pointers), what to call the metric, and its unit. A message
that does not fit is reported, not guessed. Values are device-wide utilization only, never
per-process memory, and every sample carries the topic and its maturity as provenance.

Mapping file (``ddh-mapping-v1``)::

    {
      "schema_version": 1,
      "topic": "com.axis.device.memory-utilization.v1",
      "maturity": "alpha",
      "timestamp": {"pointer": "/time", "unit": "iso8601"},
      "metrics": [
        {"pointer": "/value", "name": "system.ddh.memory_utilization_percent",
         "unit": "percent", "scale": 1.0}
      ]
    }

The pointer values above are illustrative; take them from a message you captured.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axis_memlab.errors import RunDataError
from axis_memlab.records import Metric, Record
from axis_memlab.sources.common import unavailable, value

PRODUCER = "axis-memlab-ddh"
TIMESTAMP_UNITS = ("iso8601", "unix_s", "unix_ms", "unix_ns")
_NAME = re.compile(r"^system\.ddh\.[a-z0-9_.]+$")
_TOPIC = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_POINTER = re.compile(r"^(?:/(?:[^/~]|~[01])*)*$")


@dataclass(frozen=True)
class MetricMapping:
    pointer: str
    name: str
    unit: str
    scale: float


@dataclass(frozen=True)
class DdhMapping:
    topic: str
    maturity: str
    timestamp_pointer: str
    timestamp_unit: str
    metrics: tuple[MetricMapping, ...]


def load_mapping(path: str | Path) -> DdhMapping:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RunDataError(f"{source}: invalid JSON: {exc}") from None
    problems: list[str] = []
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise RunDataError(f"{source}: not a ddh-mapping-v1 document")
    topic = raw.get("topic")
    if not isinstance(topic, str) or not _TOPIC.match(topic):
        problems.append("topic is required")
    maturity = raw.get("maturity")
    if not isinstance(maturity, str) or not maturity:
        problems.append("maturity is required (for example alpha); it is recorded as provenance")
    ts = raw.get("timestamp")
    if (
        not isinstance(ts, dict)
        or not isinstance(ts.get("pointer"), str)
        or not _POINTER.match(ts["pointer"])
        or ts.get("unit") not in TIMESTAMP_UNITS
    ):
        problems.append(f"timestamp needs a JSON pointer and a unit from {TIMESTAMP_UNITS}")
    metrics: list[MetricMapping] = []
    items = raw.get("metrics")
    if not isinstance(items, list) or not items:
        problems.append("metrics must be a non-empty list")
    else:
        for item in items:
            if not isinstance(item, dict):
                problems.append("each metric mapping must be an object")
                continue
            pointer, name, unit = item.get("pointer"), item.get("name"), item.get("unit")
            scale = item.get("scale", 1.0)
            if (
                not isinstance(pointer, str)
                or not _POINTER.match(pointer)
                or not isinstance(name, str)
                or not _NAME.match(name)
                or not isinstance(unit, str)
                or not unit
                or isinstance(scale, bool)
                or not isinstance(scale, int | float)
                or not math.isfinite(scale)
                or scale <= 0
            ):
                problems.append(f"invalid metric mapping for {name!r}")
            elif name.endswith("_bytes") and unit != "bytes":
                problems.append(f"{name} must use unit 'bytes'")
            else:
                metrics.append(MetricMapping(pointer, name, unit, float(scale)))
    if problems:
        raise RunDataError(f"{source}: invalid mapping: " + "; ".join(problems))
    assert isinstance(ts, dict) and isinstance(topic, str) and isinstance(maturity, str)
    return DdhMapping(topic, maturity, ts["pointer"], ts["unit"], tuple(metrics))


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 lookup. Raises ``KeyError`` when the path does not exist."""
    current = document
    if pointer == "":
        return current
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise KeyError(pointer)
    return current


def _timestamp_ns(raw: Any, unit: str) -> int | None:
    if unit == "iso8601":
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp() * 1_000_000_000)
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        return None
    factor = {"unix_s": 1_000_000_000, "unix_ms": 1_000_000, "unix_ns": 1}[unit]
    nanoseconds = int(raw * factor)
    return nanoseconds if nanoseconds >= 0 else None


def convert(message: Any, mapping: DdhMapping, *, run_id: str, device_id: str) -> Record | str:
    """One captured message -> a ``sample`` record, or the reason it cannot be used."""
    if not isinstance(message, dict):
        return "message is not a JSON object"
    try:
        raw_ts = resolve_pointer(message, mapping.timestamp_pointer)
    except KeyError:
        return "timestamp not found at the mapped pointer"
    ts_ns = _timestamp_ns(raw_ts, mapping.timestamp_unit)
    if ts_ns is None:
        return "timestamp is not valid for the mapped unit"
    source = f"ddh:{mapping.topic}"
    metrics: dict[str, Metric] = {}
    for item in mapping.metrics:
        try:
            raw = resolve_pointer(message, item.pointer)
        except KeyError:
            metrics[item.name] = unavailable("missing", f"{item.pointer} not in the message")
            continue
        if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
            metrics[item.name] = unavailable("parse_error", f"{item.pointer} is not a number")
            continue
        scaled = raw * item.scale
        metrics[item.name] = value(
            int(scaled) if item.unit == "bytes" else float(scaled), item.unit, source
        )
    return Record(
        record_type="sample",
        run_id=run_id,
        producer=PRODUCER,
        ts_utc_ns=ts_ns,
        ts_mono_ns=None,
        identity={"device_id": device_id},
        metrics=metrics,
        source_metadata={
            "ddh_topic": mapping.topic,
            "maturity": mapping.maturity,
            "scope": "device-wide utilization; not per-process",
        },
    )
