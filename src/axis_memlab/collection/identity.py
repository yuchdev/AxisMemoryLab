"""Pseudonymous device identity and run ids.

The run archive must not contain anything that identifies a customer or a unit. Only a label
chosen by the operator is accepted, and text that looks like an address or a serial number is
refused rather than stored.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from axis_memlab.errors import CollectionError

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_MAC = re.compile(r"^(?:[0-9A-Fa-f]{2}[-.]){5}[0-9A-Fa-f]{2}$")
_HEX12 = re.compile(r"^[0-9A-Fa-f]{12}$")  # Axis serial numbers are 12 hex digits


def validate_device_id(label: str) -> str:
    """Return ``label`` if it is an acceptable pseudonym, else raise ``CollectionError``."""
    if not _SAFE.match(label):
        raise CollectionError("device id must be 1-64 characters of [A-Za-z0-9._-]")
    if _IPV4.match(label) or _MAC.match(label) or _HEX12.match(label):
        raise CollectionError("device id looks like an address or serial number; use a pseudonym")
    return label


def pseudonym(raw: str, salt: str) -> str:
    """Stable pseudonym for ``raw`` under a secret ``salt`` the operator keeps outside the repo."""
    if not salt:
        raise CollectionError("a non-empty salt is required")
    digest = hashlib.sha256(f"{salt}\0{raw}".encode()).hexdigest()
    return f"dev-{digest[:12]}"


def new_run_id() -> str:
    return str(uuid.uuid4())
