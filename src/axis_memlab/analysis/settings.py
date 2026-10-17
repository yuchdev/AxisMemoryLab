"""Analysis settings taken from the validated ``[analysis]`` config section."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisSettings:
    warmup_seconds: int
    minimum_samples: int
    metrics: tuple[str, ...]
    normalization: tuple[str, ...]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AnalysisSettings:
        section = config["analysis"]
        return cls(
            warmup_seconds=section["warmup_seconds"],
            minimum_samples=section["minimum_samples"],
            metrics=tuple(section["metrics"]),
            normalization=tuple(section["normalization"]),
        )
