"""Append-only local run archive.

Layout: ``<root>/<run_id>/manifest.json`` and ``records.jsonl`` (optionally ``records.jsonl.gz``
after :func:`compress_run`). Records are only ever appended, each as one ``write`` of one line;
history is never rewritten. The manifest is replaced atomically and only its ``status`` changes
after creation. A process killed mid-write can leave one partial last line; the next writer
starts on a fresh line and readers report the damaged line instead of hiding it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from axis_memlab import __version__
from axis_memlab.errors import CollectionError, RunDataError
from axis_memlab.records import Record

MANIFEST = "manifest.json"
RECORDS = "records.jsonl"
STATUSES = ("started", "complete", "incomplete", "failed")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    *,
    run_id: str,
    device_id: str,
    scenario: str,
    privacy_classification: str = "redacted",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": now_iso(),
        "device_identity": device_id,
        "scenario": scenario,
        "privacy_classification": privacy_classification,
        "status": "started",
        "collector_version": __version__,
    }
    manifest.update({k: v for k, v in (extra or {}).items() if v is not None})
    return manifest


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def encode_line(record: Record | dict[str, Any]) -> bytes:
    payload = record.as_dict() if isinstance(record, Record) else record
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8") + b"\n"


class RunStore:
    def __init__(self, directory: Path, manifest: dict[str, Any], *, fsync: bool = True) -> None:
        self.directory = directory
        self.manifest = manifest
        self._fsync = fsync
        self._fd: int | None = None

    # ---- lifecycle -----------------------------------------------------------------------
    @classmethod
    def create(cls, root: Path, manifest: dict[str, Any], *, fsync: bool = True) -> RunStore:
        """Create ``<root>/<run_id>``. Refuses to touch an existing run."""
        run_id = str(UUID(manifest["run_id"]))
        directory = root / run_id
        root.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            raise CollectionError(f"run directory already exists: {directory}") from None
        store = cls(directory, manifest, fsync=fsync)
        _write_atomic(directory / MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        store._open()
        return store

    @classmethod
    def open_existing(cls, directory: Path, *, fsync: bool = True) -> RunStore:
        try:
            manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
            UUID(str(manifest["run_id"]))
        except FileNotFoundError:
            raise RunDataError(f"{directory}: not a run directory (no {MANIFEST})") from None
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise RunDataError(f"{directory}: invalid {MANIFEST}: {exc}") from None
        if (directory / (RECORDS + ".gz")).exists():
            raise CollectionError("run is compressed; it is read-only")
        store = cls(directory, manifest, fsync=fsync)
        store._open()
        return store

    @property
    def run_id(self) -> str:
        return str(self.manifest["run_id"])

    def _open(self) -> None:
        path = self.directory / RECORDS
        # A prior crash may have left a partial last line; never glue a new record onto it.
        needs_newline = False
        if path.exists() and path.stat().st_size > 0:
            with path.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                needs_newline = stream.read(1) != b"\n"
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        self._fd = os.open(path, flags, 0o600)
        if needs_newline:
            os.write(self._fd, b"\n")

    def append(self, record: Record | dict[str, Any]) -> None:
        if self._fd is None:
            raise CollectionError("run store is closed")
        line = encode_line(record)
        written = os.write(self._fd, line)  # one line per write; O_APPEND positions it
        if written != len(line):
            raise OSError("short write to run archive")
        if self._fsync:
            os.fsync(self._fd)

    def finalize(self, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        self.manifest = {**self.manifest, "status": status}
        _write_atomic(
            self.directory / MANIFEST, json.dumps(self.manifest, indent=2, sort_keys=True) + "\n"
        )

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> RunStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def compress_run(directory: Path) -> Path:
    """Replace ``records.jsonl`` with ``records.jsonl.gz`` after verifying the copy."""
    source = directory / RECORDS
    target = directory / (RECORDS + ".gz")
    if target.exists():
        raise CollectionError("run is already compressed")
    data = source.read_bytes()
    with gzip.open(target, "wb") as stream:
        stream.write(data)
    with gzip.open(target, "rb") as stream:
        if stream.read() != data:
            target.unlink()
            raise CollectionError("compressed copy did not verify; original kept")
    source.unlink()
    return target


def find_old_runs(root: Path, older_than_days: int, *, now: datetime | None = None) -> list[Path]:
    """Direct child run directories whose manifest ``created_at`` is older than the cutoff."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=older_than_days)
    found: list[Path] = []
    if not root.is_dir():
        return found
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir() or not (entry / MANIFEST).is_file():
            continue
        try:
            manifest = json.loads((entry / MANIFEST).read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue  # unreadable manifests are never deleted automatically
        if created.tzinfo is not None and created < cutoff:
            found.append(entry)
    return found


def purge_runs(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        if path.is_symlink() or not (path / MANIFEST).is_file():
            continue
        shutil.rmtree(path)
        removed += 1
    return removed
