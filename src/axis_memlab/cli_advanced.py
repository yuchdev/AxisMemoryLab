"""``advanced`` (diagnostic gate, evidence, DDH import) and ``bundle`` commands.

Exit codes follow ``cli.py``: 0 ok, 2 invalid request or a refusal that protects data (for
example identifying text left in a bundle), 3 not permitted (``advanced check`` found a blocked
diagnostic), 4 unreadable or invalid input.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axis_memlab.advanced.catalog import CATALOG, IDS
from axis_memlab.advanced.evidence import (
    ACCOUNT_TYPES,
    capabilities_from_records,
    check,
    load_evidence,
    skeleton,
)
from axis_memlab.bundle.build import build_bundle, verify_bundle
from axis_memlab.collection.run_store import RunStore
from axis_memlab.config import load_config
from axis_memlab.errors import CollectionError, ConfigError, RunDataError
from axis_memlab.sources.ddh import convert, load_mapping

ADVANCED_COMMANDS = ("advanced", "bundle")
EXIT_BLOCKED = 3


def add_advanced_commands(commands: Any) -> None:
    adv = commands.add_parser(
        "advanced", help="gate and helpers for Level 3-4 diagnostics (nothing is run on a device)"
    )
    sub = adv.add_subparsers(dest="advanced_command", required=True)

    lst = sub.add_parser("list", help="the diagnostics catalog and what each one cannot show")
    lst.add_argument("--json", action="store_true")

    ev = sub.add_parser("evidence", help="start a compatibility-evidence record from a run")
    ev.add_argument("--run", required=True, type=Path)
    ev.add_argument("--authorized-by-reference", required=True, help="approved incident/consent id")
    ev.add_argument("--lab-unit", action="store_true", help="the device is a declared lab unit")
    ev.add_argument("--developer-mode", action="store_true")
    ev.add_argument("--account-type", choices=ACCOUNT_TYPES, default="restricted_non_root")
    ev.add_argument("--out", required=True, type=Path, help="new file; never overwritten")

    chk = sub.add_parser("check", help="may these diagnostics be used on this firmware?")
    chk.add_argument("--evidence", required=True, type=Path)
    chk.add_argument("--diagnostic", action="append", choices=IDS, help="repeatable; default all")
    chk.add_argument("--for-firmware", help="firmware you intend to use; must equal the evidence")
    chk.add_argument("--json", action="store_true")

    ddh = sub.add_parser("import-ddh", help="import captured DDH messages through a mapping file")
    ddh.add_argument("--input", required=True, type=Path, help="JSON Lines of captured messages")
    ddh.add_argument("--mapping", required=True, type=Path)
    ddh.add_argument("--run", required=True, type=Path, help="existing run to append to")

    b = commands.add_parser("bundle", help="build or verify a redacted evidence bundle")
    b.add_argument("--verify", type=Path, metavar="DIR", help="verify an existing bundle")
    b.add_argument("--run", type=Path)
    b.add_argument("--config", type=Path, help="TOML profile (used if no --report is given)")
    b.add_argument("--out", type=Path, help="new directory; never overwritten")
    b.add_argument("--report", type=Path, help="existing analysis report JSON")
    b.add_argument("--alloc-report", type=Path, help="report from 'symbolize'")
    b.add_argument("--evidence", type=Path, help="compatibility evidence JSON")
    b.add_argument("--plan", type=Path, help="test plan (text)")
    b.add_argument("--reproducer", type=Path, help="reproduction steps (text)")
    b.add_argument("--server-report", type=Path, help="Axis server report (a text file)")
    b.add_argument("--redact-server-report", action="store_true")
    b.add_argument("--redact-context", action="store_true", help="also redact plan and reproducer")
    b.add_argument("--include-records", action="store_true", help="include records.jsonl")
    b.add_argument("--reviewed", action="store_true", help="a person has reviewed the contents")


def _read_records(run_dir: Path) -> list[dict[str, Any]]:
    plain, packed = run_dir / "records.jsonl", run_dir / "records.jsonl.gz"
    if plain.exists():
        text = plain.read_text(encoding="utf-8", errors="replace")
    elif packed.exists():
        text = gzip.decompress(packed.read_bytes()).decode("utf-8", errors="replace")
    else:
        raise RunDataError(f"{run_dir}: no records file")
    out = []
    for line in text.splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def _cmd_list(args: argparse.Namespace) -> int:
    if args.json:
        payload = [
            {
                "id": d.id,
                "title": d.title,
                "level": d.level,
                "intrusive": d.intrusive,
                "lab_unit_required": d.lab_unit_required,
                "developer_mode_required": d.developer_mode_required,
                "tool_support": d.tool_support,
                "provides": d.provides,
                "cannot_show": d.cannot_show,
                "risks": d.risks,
                "guide_section": d.guide_section,
            }
            for d in CATALOG
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for d in CATALOG:
        flags = [
            "intrusive" if d.intrusive else "read-mostly",
            "lab unit" if d.lab_unit_required else "any approved unit",
        ]
        if d.developer_mode_required:
            flags.append("Developer Mode")
        print(f"{d.id:<16} L{d.level}  {d.title}")
        print(f"{'':<20}{', '.join(flags)}; tool support: {d.tool_support}")
        print(f"{'':<20}cannot show: {d.cannot_show}")
    print("\nEvery diagnostic is blocked until verified for the firmware: 'advanced check'.")
    return 0


def _cmd_evidence(args: argparse.Namespace) -> int:
    run_dir: Path = args.run
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunDataError(f"{run_dir}: cannot read manifest.json: {exc}") from None
    missing = [k for k in ("camera_model", "soc", "firmware_version") if not manifest.get(k)]
    if missing:
        raise CollectionError(
            "the run's manifest lacks " + ", ".join(missing) + ". Evidence needs exact device "
            "facts: collect again with --camera-model, --soc and --firmware-version"
        )
    data = skeleton(
        manifest=manifest,
        capabilities=capabilities_from_records(_read_records(run_dir)),
        authorized_by_reference=args.authorized_by_reference,
        lab_unit=args.lab_unit,
        developer_mode=args.developer_mode,
        account_type=args.account_type,
    )
    with args.out.open("x", encoding="utf-8") as stream:  # never overwrite evidence
        stream.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(
        f"axis-memlab: wrote {args.out}. Every diagnostic is 'not_tested'. After testing one by "
        "hand (docs/13-advanced-diagnostics.md), edit its status and say how you tested it."
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    evidence = load_evidence(args.evidence)
    results = check(evidence, args.diagnostic, for_firmware=args.for_firmware)
    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2, sort_keys=True))
    else:
        for r in results:
            print(f"{'ALLOWED' if r.allowed else 'BLOCKED':<8} {r.diagnostic}")
            for reason in r.reasons:
                print(f"           - {reason}")
            for note in r.notes:
                print(f"           note: {note}")
    return 0 if all(r.allowed for r in results) else EXIT_BLOCKED


def _cmd_import_ddh(args: argparse.Namespace) -> int:
    mapping = load_mapping(args.mapping)
    accepted = 0
    rejected: list[tuple[int, str]] = []
    with RunStore.open_existing(args.run) as store:
        device_id = str(store.manifest["device_identity"])
        with args.input.open("rb") as stream:
            for number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    rejected.append((number, "invalid JSON"))
                    continue
                result = convert(message, mapping, run_id=store.run_id, device_id=device_id)
                if isinstance(result, str):
                    rejected.append((number, result))
                else:
                    store.append(result)
                    accepted += 1
    print(
        json.dumps(
            {
                "accepted": accepted,
                "rejected": [{"line": n, "reason": r} for n, r in rejected],
                "note": "DDH topics are alpha maturity and device-wide; not per-process",
            },
            indent=2,
        )
    )
    if rejected:
        print(f"axis-memlab: {len(rejected)} message(s) were rejected", file=sys.stderr)
    return 4 if rejected and accepted == 0 else 0


def _cmd_bundle(args: argparse.Namespace) -> int:
    if args.verify is not None:
        problems = verify_bundle(args.verify)
        for problem in problems:
            print(f"axis-memlab: {problem}", file=sys.stderr)
        if not problems:
            print(f"axis-memlab: bundle intact: {args.verify}")
        return 4 if problems else 0
    if args.run is None or args.out is None:
        raise CollectionError("bundle needs --run and --out (or --verify DIR)")
    if args.report is None and args.config is None:
        raise CollectionError("give --config (to analyse the run) or --report (an existing one)")
    config = load_config(args.config) if args.config else None
    result = build_bundle(
        run_dir=args.run,
        config=config or {},
        out=args.out,
        report_path=args.report,
        alloc_report_path=args.alloc_report,
        evidence_path=args.evidence,
        plan_path=args.plan,
        reproducer_path=args.reproducer,
        server_report_path=args.server_report,
        redact_server_report=args.redact_server_report,
        redact_context=args.redact_context,
        include_records=args.include_records,
        reviewed=args.reviewed,
        now=datetime.now(UTC),
    )
    print(
        json.dumps(
            {
                "bundle": str(result.directory),
                "files": result.files,
                "redactions": result.redactions,
            },
            indent=2,
        )
    )
    print(
        "axis-memlab: review every file before sharing; redaction is best-effort. No transfer "
        "procedure is defined by this tool.",
        file=sys.stderr,
    )
    return 0


_HANDLERS = {
    "list": _cmd_list,
    "evidence": _cmd_evidence,
    "check": _cmd_check,
    "import-ddh": _cmd_import_ddh,
}


def run_advanced_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "bundle":
            return _cmd_bundle(args)
        return _HANDLERS[args.advanced_command](args)
    except (CollectionError, ConfigError) as exc:
        print(f"axis-memlab: {exc}", file=sys.stderr)
        return 2
    except (RunDataError, OSError) as exc:
        print(f"axis-memlab: {exc}", file=sys.stderr)
        return 4
