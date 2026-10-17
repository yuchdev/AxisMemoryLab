"""Compatibility evidence and the fail-closed gate for advanced diagnostics.

An *evidence record* states what was actually tested on one device and firmware: who authorized
it (a reference, not a person's data), the device facts, the access level, the capability states
seen by ``discover``, and for each advanced diagnostic whether it was verified available,
verified unavailable, or not tested. ``check`` allows a diagnostic only when the record says it was
verified available **for that firmware**, the unit is a declared lab unit where required, and the
safety model does not forbid it. Anything else is blocked with the reason. The gate is advisory:
the toolset never runs these diagnostics itself, it only refuses to call them permitted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axis_memlab.advanced.catalog import BY_ID, CATALOG, TOOL_BLOCKED
from axis_memlab.errors import RunDataError

SCHEMA_VERSION = 1
DIAGNOSTIC_STATUSES = ("verified_available", "verified_unavailable", "not_tested")
ACCOUNT_TYPES = ("dynamic_acap_user", "restricted_non_root", "developer_mode", "other")
CAPABILITY_STATES = ("available", "denied", "missing", "timeout", "unsupported", "unknown")
STALE_AFTER_DAYS = 365
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,79}$")
_FACT = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")


@dataclass(frozen=True)
class GateResult:
    diagnostic: str
    allowed: bool
    reasons: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "diagnostic": self.diagnostic,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
        }


@dataclass
class Evidence:
    data: dict[str, Any]
    problems: list[str] = field(default_factory=list)

    @property
    def device(self) -> dict[Any, Any]:
        return dict(self.data["device"])

    @property
    def diagnostics(self) -> dict[str, dict[str, Any]]:
        return {d["id"]: d for d in self.data["diagnostics"]}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(_FACT.match(value))


def _validate(data: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(data, dict):
        return ["evidence must be a JSON object"]
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version must be 1")
    if not isinstance(data.get("evidence_id"), str) or not data["evidence_id"]:
        problems.append("evidence_id is required")
    recorded = data.get("recorded_at")
    try:
        datetime.fromisoformat(str(recorded).replace("Z", "+00:00"))
    except ValueError:
        problems.append("recorded_at must be an ISO 8601 timestamp")
    reference = data.get("authorized_by_reference")
    if not isinstance(reference, str) or not _REFERENCE.match(reference):
        problems.append(
            "authorized_by_reference must be an approved incident or consent reference "
            "(letters, digits, . _ : / # -), not a name or contact"
        )
    device = data.get("device")
    if not isinstance(device, dict):
        problems.append("device is required")
    else:
        for key in ("camera_model", "soc", "firmware_version"):
            if not _text(device.get(key)):
                problems.append(f"device.{key} is required")
        for key in ("sdk_generation", "libc"):
            if key in device and not _text(device[key]):
                problems.append(f"device.{key} is malformed")
        if not isinstance(device.get("lab_unit"), bool):
            problems.append("device.lab_unit must be true or false")
    access = data.get("access")
    if not isinstance(access, dict):
        problems.append("access is required")
    else:
        if access.get("account_type") not in ACCOUNT_TYPES:
            problems.append("access.account_type is not recognized")
        if not isinstance(access.get("developer_mode"), bool):
            problems.append("access.developer_mode must be true or false")
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        problems.append("capabilities must be a list")
    else:
        for item in capabilities:
            if (
                not isinstance(item, dict)
                or not _text(item.get("name"))
                or item.get("state") not in CAPABILITY_STATES
            ):
                problems.append("each capability needs a name and a known state")
                break
    diagnostics = data.get("diagnostics")
    if not isinstance(diagnostics, list):
        problems.append("diagnostics must be a list")
    else:
        seen: set[str] = set()
        for item in diagnostics:
            if not isinstance(item, dict) or item.get("id") not in BY_ID:
                problems.append("each diagnostic needs a known id")
                break
            if item["id"] in seen:
                problems.append(f"diagnostic {item['id']} is listed twice")
            seen.add(item["id"])
            status = item.get("status")
            if status not in DIAGNOSTIC_STATUSES:
                problems.append(f"diagnostic {item['id']} has an unknown status")
            elif status != "not_tested" and not _text(item.get("method")):
                problems.append(
                    f"diagnostic {item['id']} claims a result but gives no method; say how it "
                    "was tested"
                )
    if not isinstance(data.get("limitations"), list):
        problems.append("limitations must be a list")
    return problems


def load_evidence(path: str | Path) -> Evidence:
    """Read and validate an evidence record. Raises ``RunDataError`` listing every problem."""
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RunDataError(f"{source}: invalid JSON: {exc}") from None
    problems = _validate(data)
    if problems:
        raise RunDataError(f"{source}: invalid evidence: " + "; ".join(problems))
    return Evidence(data=data)


def skeleton(
    *,
    manifest: dict[str, Any],
    capabilities: list[dict[str, str]],
    authorized_by_reference: str,
    lab_unit: bool,
    developer_mode: bool,
    account_type: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """An evidence record with every diagnostic ``not_tested``; the operator fills in results."""
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    device = {
        key: manifest[key]
        for key in ("camera_model", "soc", "firmware_version", "sdk_generation", "libc")
        if isinstance(manifest.get(key), str) and manifest[key]
    }
    device["lab_unit"] = lab_unit
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": f"ev-{manifest['run_id'][:8]}-{stamp[:10]}",
        "recorded_at": stamp,
        "authorized_by_reference": authorized_by_reference,
        "source_run_id": manifest["run_id"],
        "device": device,
        "access": {"account_type": account_type, "developer_mode": developer_mode},
        "capabilities": capabilities,
        "diagnostics": [
            {"id": d.id, "status": "not_tested", "method": "", "notes": ""} for d in CATALOG
        ],
        "limitations": [],
    }


def check(
    evidence: Evidence,
    diagnostic_ids: list[str] | None = None,
    *,
    for_firmware: str | None = None,
    now: datetime | None = None,
) -> list[GateResult]:
    """Evaluate the gate. Unknown ids raise ``KeyError``; everything else is a result."""
    wanted = diagnostic_ids or [d.id for d in CATALOG]
    current = now or datetime.now(UTC)
    recorded = datetime.fromisoformat(str(evidence.data["recorded_at"]).replace("Z", "+00:00"))
    device = evidence.device
    access = evidence.data["access"]
    statuses = evidence.diagnostics
    results = []
    for diagnostic_id in wanted:
        spec = BY_ID[diagnostic_id]
        reasons: list[str] = []
        notes: list[str] = []
        if spec.tool_support == TOOL_BLOCKED:
            reasons.append(
                "the safety model forbids this capture (allow_deep_snapshot must stay false; "
                "docs/decisions/0003-advanced-diagnostics.md); evidence cannot enable it"
            )
        entry = statuses.get(diagnostic_id)
        status = entry["status"] if entry else "not_tested"
        if status == "not_tested":
            reasons.append("not tested on this firmware: no evidence that it works or is safe")
        elif status == "verified_unavailable":
            reasons.append(
                "verified unavailable on this firmware"
                + (f" ({entry['method']})" if entry and entry.get("method") else "")
            )
        if for_firmware is not None and for_firmware != device["firmware_version"]:
            reasons.append(
                f"evidence is for firmware {device['firmware_version']!r}, not {for_firmware!r}; "
                "compatibility is never assumed across firmware"
            )
        if spec.lab_unit_required and not device["lab_unit"]:
            reasons.append("requires a declared lab unit (device.lab_unit is false)")
        if spec.developer_mode_required and not access["developer_mode"]:
            reasons.append("requires Developer Mode, which the evidence does not record")
        if (current - recorded).days > STALE_AFTER_DAYS:
            notes.append(f"evidence is older than {STALE_AFTER_DAYS} days; consider re-verifying")
        if spec.intrusive and not reasons:
            notes.append(
                "intrusive: the toolset does not run it; follow the guide, with the owner's "
                "approval, on the lab unit only"
            )
        results.append(GateResult(diagnostic_id, not reasons, tuple(reasons), tuple(notes)))
    return results


def capabilities_from_records(records: list[dict[Any, Any]]) -> list[dict[str, str]]:
    """The latest state of each capability seen in a run's ``capability`` records."""
    latest: dict[str, dict[str, str]] = {}
    for record in records:
        annotations = record.get("annotations") or {}
        if record.get("record_type") == "capability" and isinstance(annotations, dict):
            name, state = annotations.get("capability"), annotations.get("state")
            if isinstance(name, str) and state in CAPABILITY_STATES:
                item = {"name": name, "state": state}
                reason = annotations.get("reason")
                if isinstance(reason, str) and reason:
                    item["reason"] = reason[:200]
                latest[name] = item
    return list(latest.values())
