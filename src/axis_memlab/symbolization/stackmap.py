"""Allocation-sample files (``alloc-samples-v1``): loading, module maps, and build identity.

A file may hold several *sessions* (the sampler was started more than once with the same output
path); ids restart in each session, so sessions are never mixed. A session's ``modules`` tables
say where each binary was loaded, which is what turns a raw program counter into
``(module, address in that module's file)``. Lines that do not validate are reported and
skipped, never silently repaired.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

from axis_memlab.errors import RunDataError

MAX_LINE_BYTES = 256 * 1024
_HEX = re.compile(r"^0x[0-9a-f]{1,16}$")
_BUILD_ID = re.compile(r"^[0-9a-f]*$")
_KINDS = {
    "new",
    "new[]",
    "new_nothrow",
    "new[]_nothrow",
    "new_aligned",
    "new[]_aligned",
    "new_aligned_nothrow",
    "new[]_aligned_nothrow",
    "manual",
}
_SUMMARY_FIELDS = (
    "alloc_requests",
    "alloc_request_bytes",
    "free_requests",
    "samples_taken",
    "frees_matched",
    "live_samples",
    "dropped_table_full",
    "dropped_ring_full",
    "dropped_free_events",
    "dropped_output_cap",
    "stack_failures",
    "sample_interval_bytes",
)


@dataclass(frozen=True)
class Module:
    name: str
    build_id: str | None  # lower-case hex, or None when the binary has no build-id
    base: int
    size: int

    def contains(self, pc: int) -> bool:
        return self.base <= pc < self.base + self.size


@dataclass(frozen=True)
class AllocSample:
    id: int
    ts_mono_ns: int
    size: int
    align: int
    kind: str
    thread: int
    weight_count: float
    stack: tuple[int, ...]


@dataclass
class Session:
    index: int  # 1-based position in the file
    header: dict[str, Any]
    module_tables: list[list[Module]] = field(default_factory=list)
    allocs: list[AllocSample] = field(default_factory=list)
    ids: set[int] = field(default_factory=set)
    freed: set[int] = field(default_factory=set)
    unknown_frees: int = 0
    duplicate_frees: int = 0
    duplicate_ids: int = 0
    summary: dict[str, int] | None = None
    summary_final: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def interval(self) -> int:
        return int(self.header["sample_interval_bytes"])

    def locate(self, pc: int) -> tuple[Module, int] | None:
        """(module, address inside the module's file) for a program counter, newest table first."""
        for table in reversed(self.module_tables):
            for module in table:
                if module.contains(pc):
                    return module, pc - module.base
        return None

    def all_modules(self) -> list[Module]:
        seen: dict[tuple[str, str | None, int], Module] = {}
        for table in self.module_tables:
            for module in table:
                seen[(module.name, module.build_id, module.base)] = module
        return list(seen.values())


@dataclass
class SampleFile:
    path: Path
    sessions: list[Session]
    problems: list[str]


def _uint(value: Any) -> TypeGuard[int]:
    return type(value) is int and value >= 0


def _hex(value: Any) -> int | None:
    if isinstance(value, str) and _HEX.match(value):
        return int(value, 16)
    return None


def _parse_modules(raw: Any) -> list[Module] | None:
    if not isinstance(raw, list):
        return None
    modules = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        base, size = _hex(item.get("base")), _hex(item.get("size"))
        name, build_id = item.get("name"), item.get("build_id")
        if (
            base is None
            or size is None
            or not isinstance(name, str)
            or not name
            or not isinstance(build_id, str)
            or not _BUILD_ID.match(build_id)
        ):
            return None
        modules.append(Module(name, build_id or None, base, size))
    return modules


def _parse_alloc(raw: dict[str, Any], max_depth: int) -> AllocSample | str:
    for key in ("id", "ts_mono_ns", "size", "align", "thread"):
        if not _uint(raw.get(key)):
            return f"alloc field {key} must be a nonnegative integer"
    if raw["id"] < 1:
        return "alloc id must be at least 1"
    weight = raw.get("weight_count")
    if (
        isinstance(weight, bool)
        or not isinstance(weight, int | float)
        or not math.isfinite(weight)
        or weight < 1
    ):
        return "alloc weight_count must be a finite number >= 1"
    if raw.get("kind") not in _KINDS:
        return "alloc kind is unknown"
    stack_raw = raw.get("stack")
    if not isinstance(stack_raw, list) or len(stack_raw) > max_depth:
        return "alloc stack must be a list within the declared depth"
    stack = []
    for item in stack_raw:
        pc = _hex(item)
        if pc is None:
            return "alloc stack holds a non-address"
        stack.append(pc)
    return AllocSample(
        id=raw["id"],
        ts_mono_ns=raw["ts_mono_ns"],
        size=raw["size"],
        align=raw["align"],
        kind=raw["kind"],
        thread=raw["thread"],
        weight_count=float(weight),
        stack=tuple(stack),
    )


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def load_samples(path: str | Path) -> SampleFile:
    """Read an allocation-samples file. Raises ``OSError`` or ``RunDataError`` (no header)."""
    source = Path(path)
    result = SampleFile(path=source, sessions=[], problems=[])
    current: Session | None = None
    with source.open("rb") as stream:
        number = 0
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            number += 1
            if len(line) > MAX_LINE_BYTES:
                (current.problems if current else result.problems).append(
                    f"line {number}: too long; skipped"
                )
                while line and not line.endswith(b"\n"):
                    line = stream.readline(MAX_LINE_BYTES)
                continue
            if not line.strip():
                continue
            try:
                raw = json.loads(line, parse_constant=_reject_constant)
            except (ValueError, UnicodeDecodeError):
                (current.problems if current else result.problems).append(
                    f"line {number}: invalid JSON; skipped"
                )
                continue
            if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
                (current.problems if current else result.problems).append(
                    f"line {number}: not a sample record; skipped"
                )
                continue
            kind = raw["type"]
            if kind == "header":
                modules = _parse_modules(raw.get("modules"))
                depth = raw.get("max_stack_depth")
                interval = raw.get("sample_interval_bytes")
                if (
                    raw.get("schema") != "alloc-samples-v1"
                    or modules is None
                    or not _uint(depth)
                    or not 1 <= depth <= 32
                    or not _uint(interval)
                    or interval < 1
                    or raw.get("pointer_bits") not in (32, 64)
                ):
                    result.problems.append(f"line {number}: invalid header; skipped")
                    current = None
                    continue
                current = Session(index=len(result.sessions) + 1, header=raw)
                current.module_tables.append(modules)
                result.sessions.append(current)
                continue
            if current is None:
                result.problems.append(f"line {number}: record before any header; skipped")
                continue
            if kind == "modules":
                modules = _parse_modules(raw.get("modules"))
                if modules is None:
                    current.problems.append(f"line {number}: invalid modules record; skipped")
                else:
                    current.module_tables.append(modules)
            elif kind == "alloc":
                parsed = _parse_alloc(raw, int(current.header["max_stack_depth"]))
                if isinstance(parsed, str):
                    current.problems.append(f"line {number}: {parsed}; skipped")
                elif parsed.id in current.ids:
                    current.duplicate_ids += 1
                    current.problems.append(f"line {number}: duplicate alloc id; skipped")
                else:
                    current.ids.add(parsed.id)
                    current.allocs.append(parsed)
            elif kind == "free":
                free_id = raw.get("id")
                if not _uint(free_id) or free_id < 1:
                    current.problems.append(f"line {number}: invalid free; skipped")
                elif free_id in current.freed:
                    current.duplicate_frees += 1
                else:
                    current.freed.add(free_id)
            elif kind == "summary":
                values: dict[str, int] = {}
                for key in _SUMMARY_FIELDS:
                    item = raw.get(key)
                    if _uint(item):
                        values[key] = item
                if len(values) == len(_SUMMARY_FIELDS) and isinstance(raw.get("final"), bool):
                    current.summary = values
                    current.summary_final = raw["final"]
                else:
                    current.problems.append(f"line {number}: invalid summary; skipped")
            else:
                current.problems.append(f"line {number}: unknown record type; skipped")
    if not result.sessions:
        raise RunDataError(f"{source}: no valid alloc-samples-v1 header found")
    for session in result.sessions:
        session.unknown_frees = len(session.freed - session.ids)
    return result
