"""Deterministic synthetic run archives for analysis tests; no device data of any kind."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

RUN_ID = "00000000-0000-4000-8000-0000000000aa"
BASE_UTC_NS = 1_767_225_600_000_000_000

Spec = Callable[[float], float | None]  # seconds since start -> value (None = unavailable)


def linear(start: float, per_second: float, noise: float = 0.0) -> Callable[[float], float]:
    """Value ramp with small deterministic jitter (no randomness)."""

    def value(t: float) -> float:
        jitter = (((int(t) * 7) % 5) - 2) * noise
        return start + per_second * t + jitter

    return value


def ramp_then_flat(
    start: float, per_second: float, ramp_seconds: float
) -> Callable[[float], float]:
    return lambda t: start + per_second * min(t, ramp_seconds)


def write_run(
    root: Path,
    metrics: dict[str, Spec],
    *,
    run_id: str = RUN_ID,
    seconds: int = 600,
    interval: int = 5,
    events: list[tuple[float, dict[str, Any]]] | None = None,
    pid_at: Callable[[float], int] | None = None,
    manifest: dict[str, Any] | None = None,
    extra_lines: list[str] | None = None,
) -> Path:
    """Write ``manifest.json`` and ``records.jsonl`` under ``root`` and return ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    base_manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": "2026-01-01T00:00:00Z",
        "device_identity": "synthetic-device-001",
        "scenario": "synthetic-trace",
        "privacy_classification": "synthetic",
        "status": "complete",
    }
    base_manifest.update(manifest or {})
    (root / "manifest.json").write_text(json.dumps(base_manifest), encoding="utf-8")

    lines: list[tuple[float, str]] = []
    for t, marker in events or []:
        lines.append(
            (
                t - 0.001,
                json.dumps(
                    {
                        "schema_version": 1,
                        "record_type": "event",
                        "run_id": run_id,
                        "producer": "synthetic",
                        "ts_utc_ns": BASE_UTC_NS + int(t * 1e9),
                        "ts_mono_ns": 10**9 + int(t * 1e9),
                        "identity": {"device_id": "synthetic-device-001"},
                        "metrics": {},
                        "annotations": marker,
                    }
                ),
            )
        )
    for t in range(0, seconds + 1, interval):
        encoded: dict[str, Any] = {}
        for name, spec in metrics.items():
            value = spec(float(t))
            unit = "bytes" if name.endswith("_bytes") else "count"
            encoded[name] = (
                {"available": False, "reason": "synthetic: not readable"}
                if value is None
                else {"value": value, "unit": unit, "source": "synthetic"}
            )
        identity: dict[str, Any] = {"device_id": "synthetic-device-001"}
        if pid_at is not None:
            identity["pid"] = pid_at(float(t))
        lines.append(
            (
                float(t),
                json.dumps(
                    {
                        "schema_version": 1,
                        "record_type": "sample",
                        "run_id": run_id,
                        "producer": "synthetic",
                        "ts_utc_ns": BASE_UTC_NS + t * 10**9,
                        "ts_mono_ns": 10**9 + t * 10**9,
                        "identity": identity,
                        "metrics": encoded,
                    }
                ),
            )
        )
    lines.sort(key=lambda item: item[0])
    body = [text for _, text in lines] + (extra_lines or [])
    (root / "records.jsonl").write_text("\n".join(body) + "\n", encoding="utf-8")
    return root
