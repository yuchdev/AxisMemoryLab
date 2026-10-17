"""Best-effort detection and redaction of identifying text.

This is a safety net, not a guarantee. Patterns catch the common ways a device or a person leaks
into text (addresses, serial numbers, e-mail addresses, credentials in URLs or assignments, key
material, host names after a label). A human must still review anything before it leaves the
machine. Detection never returns the matched text, only the kind and the count, so a report of
what was found cannot itself leak it. Redacted text rescans clean: placeholders are never
re-flagged.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection

_I = re.IGNORECASE
_NOT_PLACEHOLDER = r"(?!\[REDACTED)"

# (kind, pattern, replacement). Order matters: specific patterns first, so a MAC is not also
# reported as IPv6 and a labelled value is not also reported as an address.
PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
        ),
        "[REDACTED-PRIVATE-KEY]",
    ),
    (
        "url_credentials",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", _I),
        "[REDACTED-URL-CREDENTIALS]@",
    ),
    (
        "secret_assignment",
        re.compile(
            r"\b((?:password|passwd|pwd|secret|token|api[_-]?key|authorization))\b"
            r"(\s*[=:]\s*)" + _NOT_PLACEHOLDER + r"(?:Bearer\s+|Basic\s+)?[^\s,;\"']+",
            _I,
        ),
        r"\1\2[REDACTED-SECRET]",
    ),
    (
        "serial_label",
        re.compile(
            r"\b(serial(?:\s*(?:number|no\.?|nr\.?))?)(\s*[=:]\s*)"
            + _NOT_PLACEHOLDER
            + r"[^\s,;\"']+",
            _I,
        ),
        r"\1\2[REDACTED-SERIAL]",
    ),
    (
        "hostname_label",
        re.compile(r"\b(host(?:name)?)(\s*[=:]\s*)" + _NOT_PLACEHOLDER + r"[^\s,;\"']+", _I),
        r"\1\2[REDACTED-HOSTNAME]",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),
        "[REDACTED-EMAIL]",
    ),
    (
        "mac_address",
        re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
        "[REDACTED-MAC]",
    ),
    (
        "ipv6_address",
        re.compile(
            r"(?<![\w:])(?:(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
            r"|(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?::"
            r"(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?)(?![\w:])"
        ),
        "[REDACTED-IPV6]",
    ),
    (
        "ipv4_address",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
        "[REDACTED-IPV4]",
    ),
    (
        "serial_number",
        # Axis serial numbers are 12 hexadecimal digits; require a digit and a letter so that
        # plain numbers are not flagged.
        re.compile(r"\b(?=[0-9A-F]*[0-9])(?=[0-9A-F]*[A-F])[0-9A-F]{12}\b"),
        "[REDACTED-SERIAL]",
    ),
)
KINDS = tuple(name for name, _, _ in PATTERNS)


def scan(text: str, protect: Collection[str] = ()) -> Counter[str]:
    """Number of matches of each kind in ``text``. ``protect`` lists exact strings (for example
    the firmware version) that look like an address but are not one."""
    found: Counter[str] = Counter()
    remaining = text
    for name, pattern, _replacement in PATTERNS:
        for match in pattern.finditer(remaining):
            if match.group(0) not in protect:
                found[name] += 1
        # Blank out matches so a later pattern does not count the same text again.
        remaining = pattern.sub(
            lambda m: m.group(0) if m.group(0) in protect else " " * len(m.group(0)), remaining
        )
    return found


def redact(text: str, protect: Collection[str] = ()) -> tuple[str, Counter[str]]:
    """Return ``text`` with matches replaced by placeholders, and the counts by kind."""
    counts: Counter[str] = Counter()
    for name, pattern, replacement in PATTERNS:

        def substitute(match: re.Match[str], _name: str = name, _rep: str = replacement) -> str:
            if match.group(0) in protect:
                return match.group(0)
            counts[_name] += 1
            return match.expand(_rep)

        text = pattern.sub(substitute, text)
    return text, counts
