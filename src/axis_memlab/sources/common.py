"""Shared helpers for turning procfs text into typed metrics.

Rules every parser follows: sizes become bytes at parse time (kernel ``kB`` is 1024 bytes),
a value that is present is kept even when it is zero, and anything that cannot be read is an
explicit unavailable metric with a closed ``reason_code``, never a zero.
"""

from __future__ import annotations

from axis_memlab.records import REASON_CODES, Metric

KB = 1024


def unavailable(code: str, detail: str) -> Metric:
    """An explicit absence with a machine-readable code and a human-readable reason."""
    if code not in REASON_CODES:
        raise ValueError(f"unknown reason code: {code}")
    return Metric(available=False, reason=detail, reason_code=code)


def value(number: int | float, unit: str, source: str) -> Metric:
    return Metric(value=number, unit=unit, source=source)


def split_key_value(line: str) -> tuple[str, str] | None:
    """``Key:   value`` -> (``Key``, ``value``), or ``None`` for lines without a colon."""
    key, sep, rest = line.partition(":")
    if not sep or not key or " " in key.strip():
        return None
    return key.strip(), rest.strip()


def parse_kb(text: str) -> int | None:
    """``"1234 kB"`` -> 1263616 bytes. Anything else (missing unit, sign, junk) -> ``None``.

    A bare number is refused on purpose: the unit is part of the evidence, and guessing
    "bytes" for a ``kB`` field would silently change values by a factor of 1024.
    """
    parts = text.split()
    if len(parts) != 2 or parts[1] != "kB" or not parts[0].isdigit():
        return None
    return int(parts[0]) * KB


def parse_count(text: str) -> int | None:
    parts = text.split()
    if len(parts) != 1 or not parts[0].isdigit():
        return None
    return int(parts[0])


def all_unavailable(names: list[str], code: str, detail: str) -> dict[str, Metric]:
    return {name: unavailable(code, detail) for name in names}
