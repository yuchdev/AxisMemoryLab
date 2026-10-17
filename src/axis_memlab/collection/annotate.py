"""Immutable phase and segment annotations.

An annotation is a new ``event`` record appended to the run. Existing records are never edited,
so an annotation made later cannot change what was measured, only add context for analysis.
"""

from __future__ import annotations

import re

from axis_memlab.collection.run_store import RunStore
from axis_memlab.collection.scheduler import Clock, SystemClock
from axis_memlab.errors import CollectionError
from axis_memlab.records import Record

PRODUCER = "axis-memlab-annotate"
_PHASE = re.compile(r"^[A-Za-z0-9_.:-]{1,48}$")
MAX_TEXT = 200


def _text(label: str, text: str) -> str:
    if len(text) > MAX_TEXT or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise CollectionError(f"{label} must be at most {MAX_TEXT} printable characters")
    return text


def annotate(
    store: RunStore,
    *,
    phase: str | None = None,
    boundary_reason: str | None = None,
    note: str | None = None,
    clock: Clock | None = None,
) -> Record:
    """Append a ``phase_start`` or ``segment_boundary`` event; exactly one must be given."""
    if (phase is None) == (boundary_reason is None):
        raise CollectionError("give exactly one of a phase or a segment boundary reason")
    clk = clock or SystemClock()
    annotations: dict[str, str]
    if phase is not None:
        if not _PHASE.match(phase):
            raise CollectionError("phase must match [A-Za-z0-9_.:-]{1,48}")
        annotations = {"event": "phase_start", "phase": phase}
    else:
        assert boundary_reason is not None
        annotations = {"event": "segment_boundary", "reason": _text("reason", boundary_reason)}
    if note is not None:
        annotations["note"] = _text("note", note)
    record = Record(
        record_type="event",
        run_id=store.run_id,
        producer=PRODUCER,
        ts_utc_ns=clk.utc_ns(),
        ts_mono_ns=None,
        identity={"device_id": str(store.manifest["device_identity"])},
        metrics={},
        annotations=annotations,
    )
    store.append(record)
    return record
