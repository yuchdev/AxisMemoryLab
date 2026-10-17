"""Rendering of ``report-v1`` documents; renderers never add conclusions of their own."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axis_memlab.errors import RunDataError


def load_report(path: str | Path) -> dict[str, Any]:
    """Read a report document and check the envelope the renderers rely on."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RunDataError(f"{path}: invalid report JSON: {exc}") from None
    if (
        not isinstance(doc, dict)
        or doc.get("schema_version") != 1
        or not isinstance(doc.get("run_references"), list)
        or not isinstance(doc.get("limitations"), list)
        or not isinstance(doc.get("findings"), list)
        or not all(isinstance(f, dict) and isinstance(f.get("type"), str) for f in doc["findings"])
    ):
        raise RunDataError(f"{path}: not a report-v1 document")
    return doc


def by_type(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [f for f in doc["findings"] if f["type"] == kind]
