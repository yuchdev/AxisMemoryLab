"""Tolerant, offline loading of a run archive (``manifest.json`` + ``records.jsonl``)."""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from axis_memlab.errors import RunDataError
from axis_memlab.records import Metric

_RECORD_TYPES = {"sample", "event", "capability", "artifact", "error", "run_start", "run_stop"}


@dataclass(frozen=True)
class Sample:
    """One ``sample`` record with parsed metrics."""

    ts_utc_ns: int
    ts_mono_ns: int | None
    identity: dict[str, Any]
    metrics: dict[str, Metric]
    line: int


@dataclass(frozen=True)
class Event:
    """One ``event`` record; phase and segment markers live in ``annotations``."""

    ts_utc_ns: int
    annotations: dict[str, Any]
    line: int


@dataclass
class LoadedRun:
    path: Path
    manifest: dict[str, Any]
    samples: list[Sample]
    events: list[Event]
    errors: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return str(self.manifest["run_id"])


def _int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _parse_metric(raw: Any) -> Metric:
    if isinstance(raw, dict):
        if raw.get("available") is False and isinstance(raw.get("reason"), str) and raw["reason"]:
            return Metric(available=False, reason=raw["reason"])
        value, unit, source = raw.get("value"), raw.get("unit"), raw.get("source")
        if (
            isinstance(value, int | float | str | bool)
            and not (isinstance(value, float) and not math.isfinite(value))
            and isinstance(unit, str)
            and unit
            and isinstance(source, str)
            and source
        ):
            return Metric(value=value, unit=unit, source=source)
    return Metric(available=False, reason="malformed metric in record")


def load_run(path: str | Path) -> LoadedRun:
    """Load a run; per-line defects become ``problems`` rather than silent drops.

    Raises ``OSError`` if a file cannot be read and ``RunDataError`` if the manifest is invalid.
    """
    root = Path(path)
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        UUID(str(manifest["run_id"]))
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RunDataError(f"{root}: invalid manifest.json: {exc}") from None
    if not isinstance(manifest, dict):
        raise RunDataError(f"{root}: manifest.json must be an object")
    plain = root / "records.jsonl"
    if plain.exists():
        text = plain.read_text(encoding="utf-8", errors="replace")
    else:
        with gzip.open(root / "records.jsonl.gz", "rb") as compressed:
            text = compressed.read().decode("utf-8", errors="replace")

    run = LoadedRun(path=root, manifest=manifest, samples=[], events=[])
    last_ts = -1
    out_of_order = False
    seen: set[int] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            run.problems.append(f"line {number}: invalid JSON; skipped")
            continue
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != 1
            or raw.get("record_type") not in _RECORD_TYPES
            or raw.get("run_id") != manifest["run_id"]
            or not _int(raw.get("ts_utc_ns"))
        ):
            run.problems.append(f"line {number}: not a valid record for this run; skipped")
            continue
        ts = raw["ts_utc_ns"]
        if ts < last_ts:
            out_of_order = True
        last_ts = max(last_ts, ts)
        mono = raw.get("ts_mono_ns")
        if raw["record_type"] == "sample":
            metrics_raw = raw.get("metrics")
            if not isinstance(metrics_raw, dict):
                run.problems.append(f"line {number}: sample without metrics object; skipped")
                continue
            if ts in seen:
                run.problems.append(f"line {number}: duplicate sample timestamp; skipped")
                continue
            seen.add(ts)
            identity: dict[str, Any] = (
                raw["identity"] if isinstance(raw.get("identity"), dict) else {}
            )
            run.samples.append(
                Sample(
                    ts_utc_ns=ts,
                    ts_mono_ns=mono if _int(mono) else None,
                    identity=identity,
                    metrics={name: _parse_metric(m) for name, m in metrics_raw.items()},
                    line=number,
                )
            )
        elif raw["record_type"] == "error":
            ann = raw.get("annotations")
            if isinstance(ann, dict):
                run.errors.append(ann)
        elif raw["record_type"] == "event":
            ann = raw.get("annotations")
            if isinstance(ann, dict) and isinstance(ann.get("event"), str):
                run.events.append(Event(ts_utc_ns=ts, annotations=ann, line=number))
    if out_of_order:
        run.problems.append("records were not in timestamp order; sorted by ts_utc_ns")
        run.samples.sort(key=lambda s: s.ts_utc_ns)
        run.events.sort(key=lambda e: e.ts_utc_ns)
    return run
