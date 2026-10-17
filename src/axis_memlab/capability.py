"""Capability model: what can be read, and why not when it cannot.

Capabilities are recorded, never assumed. A missing or denied source is a normal, reportable
state, not an error; the collector continues with what it has.
"""

from __future__ import annotations

from dataclasses import dataclass

from axis_memlab.records import Record

STATES = ("available", "denied", "missing", "timeout", "unsupported", "unknown")

_STATE_FOR_CODE = {
    "missing": "missing",
    "permission_denied": "denied",
    "timeout": "timeout",
    "unsupported": "unsupported",
    "parse_error": "unsupported",
    "not_collected": "unknown",
}


@dataclass(frozen=True)
class Capability:
    name: str
    state: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown capability state: {self.state}")

    def annotations(self) -> dict[str, str]:
        out = {"capability": self.name, "state": self.state}
        if self.reason:
            out["reason"] = self.reason
        return out


def state_for_reason_code(code: str) -> str:
    return _STATE_FOR_CODE[code]


def capability_record(
    capability: Capability,
    *,
    run_id: str,
    device_id: str,
    producer: str,
    ts_utc_ns: int,
    ts_mono_ns: int | None,
    pid: int | None = None,
) -> Record:
    identity: dict[str, object] = {"device_id": device_id}
    if pid is not None:
        identity["pid"] = pid
    return Record(
        record_type="capability",
        run_id=run_id,
        producer=producer,
        ts_utc_ns=ts_utc_ns,
        ts_mono_ns=ts_mono_ns,
        identity=identity,
        metrics={},
        annotations=capability.annotations(),
    )
