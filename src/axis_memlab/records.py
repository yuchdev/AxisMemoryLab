"""Typed provisional JSON record envelope; protocol refinement belongs to M0001."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

RECORD_SCHEMA = "record-v1.schema.json"


@dataclass(frozen=True)
class Metric:
    """A measured metric or explicit unavailable reason."""

    value: int | float | str | bool | None = None
    unit: str | None = None
    source: str | None = None
    available: bool = True
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        if self.available:
            if self.value is None or self.unit is None or self.source is None:
                raise ValueError("available metrics require value, unit, and source")
            return {"value": self.value, "unit": self.unit, "source": self.source}
        if self.value is not None or self.unit is not None or self.source is not None:
            raise ValueError("unavailable metrics cannot include value, unit, or source")
        if not self.reason:
            raise ValueError("unavailable metrics require a reason")
        return {"available": False, "reason": self.reason}


@dataclass(frozen=True)
class Record:
    """One provisional record; timestamps are integer nanoseconds."""

    record_type: str
    run_id: str
    producer: str
    ts_utc_ns: int
    ts_mono_ns: int | None
    identity: dict[str, Any]
    metrics: dict[str, Metric]
    annotations: dict[str, Any] | None = None
    source_metadata: dict[str, Any] | None = None
    schema_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        UUID(self.run_id)
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if type(self.ts_utc_ns) is not int or self.ts_utc_ns < 0:
            raise ValueError("ts_utc_ns must be a nonnegative integer")
        if self.ts_mono_ns is not None and (
            type(self.ts_mono_ns) is not int or self.ts_mono_ns < 0
        ):
            raise ValueError("timestamps must be nonnegative")
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "record_type": self.record_type,
            "run_id": self.run_id,
            "producer": self.producer,
            "ts_utc_ns": self.ts_utc_ns,
            "ts_mono_ns": self.ts_mono_ns,
            "identity": self.identity,
            "metrics": {name: metric.as_dict() for name, metric in self.metrics.items()},
        }
        if self.annotations is not None:
            result["annotations"] = self.annotations
        if self.source_metadata is not None:
            result["source_metadata"] = self.source_metadata
        return result

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
