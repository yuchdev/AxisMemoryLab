"""Trigger and abort decisions, kept pure so they are testable without a clock or a device.

A trigger never starts anything intrusive on its own. It requests a sparse snapshot
(``smaps_rollup`` + fd inventory) and an event record. Under memory pressure the snapshot is
skipped, because reading page tables during an emergency can make it worse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Trigger:
    name: str
    detail: dict[str, int]
    snapshot_allowed: bool


@dataclass(frozen=True)
class Decision:
    abort: bool
    triggers: tuple[Trigger, ...]


class TriggerEvaluator:
    def __init__(
        self,
        *,
        pss_growth_bytes: int,
        mem_available_below_bytes: int,
        abort_mem_available_below_bytes: int,
        cooldown_seconds: float,
    ) -> None:
        self._growth = pss_growth_bytes
        self._low = mem_available_below_bytes
        self._abort = abort_mem_available_below_bytes
        self._cooldown = cooldown_seconds
        self._baseline: int | None = None
        self._last_fired: float | None = None

    def reset_process(self) -> None:
        """Forget the PSS baseline after a process restart; growth is per process instance."""
        self._baseline = None

    def _cooling(self, now_s: float) -> bool:
        return self._last_fired is not None and now_s - self._last_fired < self._cooldown

    def evaluate(
        self, now_s: float, pss_bytes: int | None, available_bytes: int | None
    ) -> Decision:
        if available_bytes is not None and available_bytes < self._abort:
            return Decision(True, ())
        fired: list[Trigger] = []
        low = available_bytes is not None and available_bytes < self._low
        if pss_bytes is not None and self._baseline is None:
            self._baseline = pss_bytes
        if not self._cooling(now_s):
            if low:
                fired.append(
                    Trigger(
                        "mem_available_low",
                        {"available_bytes": int(available_bytes or 0), "threshold": self._low},
                        snapshot_allowed=False,
                    )
                )
            if pss_bytes is not None and self._baseline is not None:
                grown = pss_bytes - self._baseline
                if grown >= self._growth:
                    fired.append(
                        Trigger(
                            "pss_growth",
                            {"grown_bytes": grown, "threshold": self._growth},
                            snapshot_allowed=not low,
                        )
                    )
                    self._baseline = pss_bytes
            if fired:
                self._last_fired = now_s
        return Decision(False, tuple(fired))
