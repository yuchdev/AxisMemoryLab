"""Split a run into segments at phase markers, process restarts, and boot changes.

Provisional event convention (M0001 owns the final definition): an ``event`` record whose
``annotations`` contain ``{"event": "phase_start", "phase": "<name>"}`` opens a named phase, and
``{"event": "segment_boundary", "reason": "<text>"}`` marks a configuration change or similar
discontinuity. Identity changes (``pid``, ``process_start_ticks``, ``boot_id``) also split.
"""

from __future__ import annotations

from dataclasses import dataclass

from axis_memlab.analysis.load import Event, LoadedRun, Sample

_IDENTITY_KEYS = ("boot_id", "pid", "process_start_ticks")


@dataclass(frozen=True)
class Segment:
    index: int
    phase: str | None
    start_reason: str
    samples: tuple[Sample, ...]
    time_basis: str  # "monotonic" only when every sample has ts_mono_ns, else "utc"

    def t_seconds(self, sample: Sample) -> float:
        """Seconds since the first sample of the segment, on the segment's clock."""
        first = self.samples[0]
        if self.time_basis == "monotonic":
            assert sample.ts_mono_ns is not None and first.ts_mono_ns is not None
            return (sample.ts_mono_ns - first.ts_mono_ns) / 1e9
        return (sample.ts_utc_ns - first.ts_utc_ns) / 1e9


def _identity_change(previous: Sample, current: Sample) -> str | None:
    for key in _IDENTITY_KEYS:
        old, new = previous.identity.get(key), current.identity.get(key)
        if old is not None and new is not None and old != new:
            return "boot_change" if key == "boot_id" else "process_restart"
    return None


def segment_run(run: LoadedRun) -> list[Segment]:
    """Return non-empty segments in time order."""
    items: list[tuple[int, int, Sample | Event]] = [(s.ts_utc_ns, 1, s) for s in run.samples]
    items += [(e.ts_utc_ns, 0, e) for e in run.events]  # markers sort before same-time samples
    items.sort(key=lambda item: (item[0], item[1]))

    groups: list[tuple[str | None, str, list[Sample]]] = []
    phase: str | None = None
    reason = "run_start"
    current: list[Sample] = []
    previous: Sample | None = None

    def close() -> None:
        if current:
            groups.append((phase, reason, list(current)))
            current.clear()

    for _, _, item in items:
        if isinstance(item, Sample):
            if previous is not None and current:
                change = _identity_change(previous, item)
                if change:
                    close()
                    reason = change
            current.append(item)
            previous = item
            continue
        ann = item.annotations
        if ann["event"] == "phase_start" and isinstance(ann.get("phase"), str) and ann["phase"]:
            close()
            phase, reason = ann["phase"], f"phase_start:{ann['phase']}"
        elif ann["event"] == "segment_boundary":
            close()
            text = ann.get("reason")
            reason = text if isinstance(text, str) and text else "segment_boundary"

    close()
    segments = []
    for index, (seg_phase, seg_reason, samples) in enumerate(groups):
        mono = all(s.ts_mono_ns is not None for s in samples)
        segments.append(
            Segment(
                index=index,
                phase=seg_phase,
                start_reason=seg_reason,
                samples=tuple(samples),
                time_basis="monotonic" if mono else "utc",
            )
        )
    return segments
