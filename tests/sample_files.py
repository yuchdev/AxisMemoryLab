"""Writes synthetic ``alloc-samples-v1`` files for symbolization tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUN_ID = "00000000-0000-4000-8000-0000000000e9"


def module(name: str, build_id: str, base: int, size: int = 0x10000) -> dict[str, str]:
    return {"name": name, "build_id": build_id, "base": f"0x{base:x}", "size": f"0x{size:x}"}


def header(modules: list[dict[str, str]], **over: Any) -> dict[str, Any]:
    line: dict[str, Any] = {
        "schema": "alloc-samples-v1",
        "type": "header",
        "run_id": RUN_ID,
        "device_id": "synthetic-device-001",
        "pid": 100,
        "ts_utc_ns": 1,
        "ts_mono_ns": 1,
        "sample_interval_bytes": 4096,
        "max_stack_depth": 16,
        "pointer_bits": 64,
        "arch": "x86_64",
        "unwinder": "frame_pointer",
        "modules": modules,
    }
    line.update(over)
    return line


def alloc(
    id_: int,
    size: int,
    stack: list[int],
    *,
    weight: float | None = None,
    interval: int = 4096,
    kind: str = "new",
    thread: int = 1,
) -> dict[str, Any]:
    import math

    p = -math.expm1(-max(size, 1) / interval)
    return {
        "type": "alloc",
        "id": id_,
        "ts_mono_ns": id_ * 1000,
        "size": size,
        "align": 0,
        "kind": kind,
        "thread": thread,
        "weight_count": weight if weight is not None else 1.0 / p,
        "stack": [f"0x{pc:x}" for pc in stack],
    }


def free(id_: int) -> dict[str, Any]:
    return {"type": "free", "id": id_, "ts_mono_ns": id_ * 1000 + 1}


def summary(final: bool = True, **over: Any) -> dict[str, Any]:
    line: dict[str, Any] = {
        "type": "summary",
        "final": final,
        "ts_mono_ns": 999999,
        "alloc_requests": 0,
        "alloc_request_bytes": 0,
        "free_requests": 0,
        "samples_taken": 0,
        "frees_matched": 0,
        "live_samples": 0,
        "dropped_table_full": 0,
        "dropped_ring_full": 0,
        "dropped_free_events": 0,
        "dropped_output_cap": 0,
        "stack_failures": 0,
        "sample_interval_bytes": 4096,
    }
    line.update(over)
    return line


def write_samples(path: Path, lines: list[Any]) -> Path:
    path.write_text(
        "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines) + "\n",
        encoding="utf-8",
    )
    return path
