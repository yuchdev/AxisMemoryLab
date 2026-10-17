"""Root-cause evidence bundle: a minimal, redacted, verifiable package for escalation.

The bundle contains what lets someone else reproduce and judge a finding (manifest, analysis
report, capability and error records, limitations, optional allocation report, compatibility
evidence, test plan, reproducer, redacted server report) and nothing more. Raw records are
included only on request and with the kernel boot id replaced by a hash. Every text file is
scanned before anything is written; if identifying patterns remain the build is refused and says
which file and which kind, never the matched text. ``BUNDLE.json`` lists every file with its
SHA-256 so ``verify`` can detect changes after the bundle was made.

No contact, transfer, or retention procedure is defined here: those are owner-supplied
(``docs/09-customer-escalation.md``).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axis_memlab import __version__
from axis_memlab.advanced.evidence import load_evidence
from axis_memlab.analysis.engine import analyze_run, build_report
from axis_memlab.analysis.load import load_run
from axis_memlab.analysis.settings import AnalysisSettings
from axis_memlab.bundle.redact import redact, scan
from axis_memlab.errors import CollectionError, RunDataError
from axis_memlab.reporting import load_report
from axis_memlab.reporting.markdown import render_markdown

SCHEMA_VERSION = 1
MAX_CONTEXT_BYTES = 256 * 1024
MAX_SERVER_REPORT_BYTES = 5 * 1024 * 1024
NOT_INCLUDED = (
    "raw records (unless --include-records was given)",
    "images, video, plate text, or any payload",
    "command lines, environment, memory contents, fd targets, or file paths",
    "host names, IP or MAC addresses, serial numbers, credentials (scanned for and refused)",
    "contact details and a transfer procedure (owner-supplied; see docs/09)",
)
README_TEXT = """This is an evidence bundle produced by axis-memlab.

It is meant to let someone reproduce and judge a finding about memory behaviour. It is NOT a
diagnosis and it was NOT reviewed by a person unless BUNDLE.json says `reviewed: true`.

Before sharing:
  1. Read every file. Redaction is a best-effort safety net, not a guarantee.
  2. Confirm the consent or incident reference in manifest.json is the approved one.
  3. Share only through the channel the owner has approved (none is defined by this tool).

`axis-memlab bundle --verify <this directory>` checks the SHA-256 of every file against
BUNDLE.json. See limitations.md for what the data cannot show.
"""


@dataclass
class BundleFile:
    path: str
    kind: str
    data: bytes
    redactions: Counter[str] = field(default_factory=Counter)


@dataclass
class BundleResult:
    directory: Path
    files: int
    redactions: dict[str, int]


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _read_text(path: Path, limit: int, label: str) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RunDataError(f"{label}: cannot read {path}: {exc.strerror}") from None
    if len(data) > limit:
        raise CollectionError(f"{label} is larger than {limit // 1024} KiB")
    if b"\x00" in data:
        raise CollectionError(
            f"{label} looks binary. If it is an archive, extract the text files you intend to "
            "share and pass them one at a time"
        )
    return data.decode("utf-8", errors="replace")


def _records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "records.jsonl"
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
    return out


def _hash_boot_id(record: dict[str, Any]) -> dict[str, Any]:
    identity = record.get("identity")
    if isinstance(identity, dict) and isinstance(identity.get("boot_id"), str):
        digest = hashlib.sha256(identity["boot_id"].encode()).hexdigest()[:16]
        record = {**record, "identity": {**identity, "boot_id": f"hash-{digest}"}}
    return record


def build_bundle(
    *,
    run_dir: Path,
    config: dict[str, Any],
    out: Path,
    report_path: Path | None = None,
    alloc_report_path: Path | None = None,
    evidence_path: Path | None = None,
    plan_path: Path | None = None,
    reproducer_path: Path | None = None,
    server_report_path: Path | None = None,
    redact_server_report: bool = False,
    redact_context: bool = False,
    include_records: bool = False,
    reviewed: bool = False,
    now: datetime | None = None,
) -> BundleResult:
    stamp = now or datetime.now(UTC)
    run = load_run(run_dir)
    manifest = run.manifest
    classification = manifest.get("privacy_classification", "sensitive")
    if classification == "sensitive" and not reviewed:
        raise CollectionError(
            "the run is classified 'sensitive'. Review what it contains, reclassify it as "
            "'redacted' in the manifest if appropriate, or pass --reviewed to confirm that a "
            "person has reviewed the bundle contents"
        )
    protect = {
        str(manifest[k])
        for k in ("firmware_version", "software_version", "sdk_generation", "build_id")
        if isinstance(manifest.get(k), str)
    }

    files: list[BundleFile] = []

    def add(path: str, kind: str, data: bytes, redactions: Counter[str] | None = None) -> None:
        files.append(BundleFile(path, kind, data, redactions or Counter()))

    add("manifest.json", "manifest", _json_bytes(manifest))

    if report_path is not None:
        report = load_report(report_path)
    else:
        settings = AnalysisSettings.from_config(config)
        findings, limitations = analyze_run(run, settings)
        report = build_report([run], findings, limitations, stamp)
    add("analysis/report.json", "analysis_report", _json_bytes(report))
    add("analysis/report.md", "analysis_report", render_markdown(report).encode("utf-8"))

    records = _records(run_dir)
    interesting = [
        r
        for r in records
        if r.get("record_type") in ("capability", "error")
        or (r.get("record_type") == "event" and isinstance(r.get("annotations"), dict))
    ]
    add(
        "context/capabilities-errors-events.json",
        "capabilities",
        _json_bytes([_hash_boot_id(r) for r in interesting]),
    )
    limits = "\n".join(f"- {item}" for item in report["limitations"])
    add(
        "limitations.md",
        "limitations",
        (
            "# Limitations\n\nWhat the data cannot show, in the analysis's own words.\n\n"
            f"{limits}\n"
        ).encode(),
    )

    if alloc_report_path is not None:
        alloc = load_report(alloc_report_path)
        add("allocation/report.json", "allocation_report", _json_bytes(alloc))
        add("allocation/report.md", "allocation_report", render_markdown(alloc).encode("utf-8"))
    if evidence_path is not None:
        evidence = load_evidence(evidence_path)
        add("context/compatibility-evidence.json", "evidence", _json_bytes(evidence.data))
    for label, path, name in (
        ("test plan", plan_path, "context/test-plan.md"),
        ("reproducer", reproducer_path, "context/reproducer.md"),
    ):
        if path is not None:
            text = _read_text(path, MAX_CONTEXT_BYTES, label)
            counts: Counter[str] = Counter()
            if redact_context:
                text, counts = redact(text, protect)
            add(name, "operator_context", text.encode("utf-8"), counts)
    if server_report_path is not None:
        text = _read_text(server_report_path, MAX_SERVER_REPORT_BYTES, "server report")
        counts = Counter()
        if redact_server_report:
            text, counts = redact(text, protect)
        add("context/server-report.txt", "server_report", text.encode("utf-8"), counts)
    if include_records:
        lines = [
            json.dumps(_hash_boot_id(r), sort_keys=True, separators=(",", ":"), allow_nan=False)
            for r in records
        ]
        add("records.jsonl", "records", ("\n".join(lines) + "\n").encode("utf-8"))
    add("README.txt", "readme", README_TEXT.encode("utf-8"))

    # Safety net: nothing identifying may remain in any text file.
    leaks: list[str] = []
    for item in files:
        for kind, count in scan(item.data.decode("utf-8", errors="replace"), protect).items():
            leaks.append(f"{item.path}: {count} x {kind}")
    if leaks:
        raise CollectionError(
            "identifying text remains; nothing was written. "
            + "; ".join(leaks)
            + ". Redact the source (--redact-server-report / --redact-context) or edit it, "
            "and review the result"
        )

    total_redactions: Counter[str] = Counter()
    entries = []
    for item in sorted(files, key=lambda f: f.path):
        total_redactions.update(item.redactions)
        entries.append(
            {
                "path": item.path,
                "kind": item.kind,
                "bytes": len(item.data),
                "sha256": hashlib.sha256(item.data).hexdigest(),
                "redactions": dict(sorted(item.redactions.items())),
            }
        )
    descriptor = {
        "schema_version": SCHEMA_VERSION,
        "created_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool_version": __version__,
        "run_id": manifest["run_id"],
        "privacy_classification": classification,
        "reviewed": reviewed,
        "review_required": True,
        "includes_raw_records": include_records,
        "not_included": list(NOT_INCLUDED),
        "redactions": dict(sorted(total_redactions.items())),
        "files": entries,
    }

    try:
        out.mkdir(parents=True)
    except FileExistsError:
        raise CollectionError(f"output directory already exists: {out}") from None
    for item in files:
        target = out / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.data)
    (out / "BUNDLE.json").write_bytes(_json_bytes(descriptor))
    return BundleResult(out, len(files) + 1, dict(total_redactions))


def verify_bundle(directory: Path) -> list[str]:
    """Problems found when comparing the directory with ``BUNDLE.json`` (empty means intact)."""
    try:
        descriptor = json.loads((directory / "BUNDLE.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["BUNDLE.json is missing or unreadable"]
    problems = []
    expected = {}
    for entry in descriptor.get("files", []):
        expected[entry["path"]] = entry
        path = directory / entry["path"]
        if not path.is_file():
            problems.append(f"missing file: {entry['path']}")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["bytes"]:
            problems.append(f"changed since the bundle was made: {entry['path']}")
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        relative = path.relative_to(directory).as_posix()
        if relative != "BUNDLE.json" and relative not in expected:
            problems.append(f"file not listed in BUNDLE.json: {relative}")
    return problems
