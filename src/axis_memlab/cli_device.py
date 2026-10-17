"""Command handlers for discovery, collection, annotation, snapshot, import, and purge.

Exit codes (in addition to those in ``cli.py``): 5 = the transport failed (device unreachable,
host key rejected, repeated connection failures), 6 = a run ended early but safely (operator
interrupt or memory pressure below the abort threshold).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from axis_memlab.collection.annotate import annotate
from axis_memlab.collection.discovery import discover
from axis_memlab.collection.identity import new_run_id, validate_device_id
from axis_memlab.collection.importer import import_records, peek_run_id
from axis_memlab.collection.run_store import (
    RunStore,
    build_manifest,
    compress_run,
    config_digest,
    find_old_runs,
    purge_runs,
)
from axis_memlab.collection.scheduler import Clock, Collector, SystemClock
from axis_memlab.config import load_config
from axis_memlab.errors import CollectionError, ConfigError, RunDataError, TransportError
from axis_memlab.transport import Reader
from axis_memlab.transport.offline import LocalProcfsReader
from axis_memlab.transport.ssh import SshReader, SshSettings

DEVICE_COMMANDS = ("discover", "collect", "annotate", "snapshot", "import", "purge")
EXIT_TRANSPORT = 5
EXIT_INCOMPLETE = 6

_DEFAULT_CONNECT, _DEFAULT_COMMAND, _DEFAULT_BYTES = 5, 10, 1024 * 1024


class _NoWaitClock(SystemClock):
    """Offline demos only: do not sleep between cycles."""

    def sleep(self, seconds: float) -> None:
        return None


def _target_args(parser: argparse.ArgumentParser) -> None:
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument(
        "--ssh", metavar="[USER@]HOST", help="read over SSH (host key must be known)"
    )
    where.add_argument(
        "--procfs-root",
        type=Path,
        metavar="DIR",
        help="read a saved tree laid out like / (proc/, sys/); use / on a live local Linux host",
    )
    parser.add_argument("--ssh-port", type=int)
    parser.add_argument("--ssh-identity", type=Path, help="private key file (never stored)")
    parser.add_argument("--ssh-known-hosts", type=Path)
    who = parser.add_mutually_exclusive_group()
    who.add_argument("--pid", type=int, help="process id to monitor")
    who.add_argument("--app", help="kernel command name (comm) of the process to monitor")


def _manifest_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device-id", required=True, help="pseudonym; never a serial or address")
    parser.add_argument("--scenario", required=True)
    parser.add_argument(
        "--privacy-classification",
        choices=("synthetic", "redacted", "sensitive"),
        default="sensitive",
    )
    for name in (
        "camera-model",
        "soc",
        "firmware-version",
        "sdk-generation",
        "libc",
        "build-id",
        "software-version",
        "test-case-id",
        "consent-reference",
    ):
        parser.add_argument(f"--{name}")
    parser.add_argument("--redaction-status", choices=("not_applicable", "none", "redacted"))
    parser.add_argument("--workload-resolution")
    parser.add_argument("--workload-fps", type=float)
    parser.add_argument("--workload-codec")


def add_device_commands(commands: Any) -> None:
    d = commands.add_parser("discover", help="list which read-only sources the target exposes")
    _target_args(d)
    d.add_argument("--config", type=Path, help="TOML profile (timeouts and byte caps)")
    d.add_argument("--json", action="store_true", help="print machine-readable JSON")

    c = commands.add_parser("collect", help="bounded read-only collection into a new run")
    _target_args(c)
    _manifest_args(c)
    c.add_argument("--config", required=True, type=Path)
    c.add_argument("--out", required=True, type=Path, help="directory that will hold the run")
    c.add_argument("--duration-seconds", type=float)
    c.add_argument("--max-samples", type=int)
    c.add_argument(
        "--run-id",
        help="UUID for the run, so records from the application can be imported into it",
    )
    c.add_argument("--compress", action="store_true", help="gzip records.jsonl when finished")
    c.add_argument(
        "--no-wait", action="store_true", help="offline demos only: do not sleep between cycles"
    )

    a = commands.add_parser("annotate", help="append a phase or segment-boundary event to a run")
    a.add_argument("--run", required=True, type=Path)
    a.add_argument("--phase")
    a.add_argument("--segment-boundary", metavar="REASON")
    a.add_argument("--note")

    s = commands.add_parser("snapshot", help="one sparse capture appended to an existing run")
    _target_args(s)
    s.add_argument("--run", required=True, type=Path)
    s.add_argument("--config", required=True, type=Path)
    s.add_argument("--level", choices=("sparse", "deep"), default="sparse")

    i = commands.add_parser("import", help="import probe/device JSON Lines into a run")
    i.add_argument("--input", required=True, type=Path)
    i.add_argument("--run", required=True, type=Path, help="existing run to append to, or new")
    i.add_argument("--out", type=Path, help="parent directory when creating a new run")
    _manifest_args_optional(i)

    p = commands.add_parser("purge", help="delete old runs (dry run unless --confirm)")
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--older-than-days", required=True, type=int)
    p.add_argument("--confirm", action="store_true")


def _manifest_args_optional(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device-id")
    parser.add_argument("--scenario")
    parser.add_argument(
        "--privacy-classification",
        choices=("synthetic", "redacted", "sensitive"),
        default="sensitive",
    )


def _collection_limits(config: dict[str, Any] | None) -> tuple[int, int, int]:
    if config is None:
        return _DEFAULT_CONNECT, _DEFAULT_COMMAND, _DEFAULT_BYTES
    c = config["collection"]
    return (
        c["ssh_connect_timeout_seconds"],
        c["ssh_command_timeout_seconds"],
        c["max_snapshot_bytes"],
    )


def _reader(args: argparse.Namespace, config: dict[str, Any] | None) -> Reader:
    connect, command, max_bytes = _collection_limits(config)
    if args.ssh:
        return SshReader(
            SshSettings(
                target=args.ssh,
                port=args.ssh_port,
                identity_file=args.ssh_identity,
                known_hosts_file=args.ssh_known_hosts,
                connect_timeout_seconds=connect,
                command_timeout_seconds=command,
                max_bytes=max_bytes,
            )
        )
    return LocalProcfsReader(args.procfs_root, max_bytes=max_bytes)


def _require_host_ssh(config: dict[str, Any]) -> None:
    if config["collection"]["source"] != "host_ssh":
        raise CollectionError(
            "this profile selects in-app collection; use 'axis-memlab import' for probe output"
        )


def _manifest_extra(args: argparse.Namespace, config_path: Path | None) -> dict[str, Any]:
    workload: dict[str, Any] = {}
    if args.workload_resolution:
        workload["resolution"] = args.workload_resolution
    if args.workload_fps is not None:
        workload["fps"] = args.workload_fps
    if args.workload_codec:
        workload["codec"] = args.workload_codec
    extra: dict[str, Any] = {
        "camera_model": args.camera_model,
        "soc": args.soc,
        "firmware_version": args.firmware_version,
        "sdk_generation": args.sdk_generation,
        "libc": args.libc,
        "build_id": args.build_id,
        "software_version": args.software_version,
        "test_case_id": args.test_case_id,
        "consent_reference": args.consent_reference,
        "redaction_status": args.redaction_status,
        "workload": workload or None,
        "config_sha256": config_digest(config_path) if config_path else None,
    }
    return extra


def _print_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _cmd_discover(args: argparse.Namespace) -> int:
    config = load_config(args.config) if args.config else None
    found = discover(_reader(args, config), pid=args.pid, app=args.app)
    if args.json:
        _print_json(found.as_dict())
        return 0
    for cap in found.capabilities:
        reason = f"  ({cap.reason})" if cap.reason else ""
        print(f"{cap.state:<12} {cap.name}{reason}")
    for key, val in sorted(found.facts.items()):
        print(f"fact         {key} = {val}")
    print(f"note         {found.as_dict()['not_probed']}")
    return 0


def _cmd_collect(args: argparse.Namespace, clock: Clock | None = None) -> int:
    config = load_config(args.config)
    _require_host_ssh(config)
    if args.duration_seconds is None and args.max_samples is None:
        raise CollectionError("give --duration-seconds or --max-samples: runs must be bounded")
    if args.max_samples is not None and args.max_samples < 1:
        raise CollectionError("--max-samples must be positive")
    if args.no_wait and not args.procfs_root:
        raise CollectionError("--no-wait is only for offline --procfs-root demos")
    device_id = validate_device_id(args.device_id)
    reader = _reader(args, config)
    try:
        run_id = str(UUID(args.run_id)) if args.run_id else new_run_id()
    except ValueError:
        raise CollectionError("--run-id must be a UUID") from None
    manifest = build_manifest(
        run_id=run_id,
        device_id=device_id,
        scenario=args.scenario,
        privacy_classification=args.privacy_classification,
        extra=_manifest_extra(args, args.config),
    )
    store = RunStore.create(args.out, manifest)
    run_clock = clock or (_NoWaitClock() if args.no_wait else SystemClock())
    try:
        with store:
            result = Collector(
                reader,
                store,
                config,
                device_id=device_id,
                clock=run_clock,
                pid=args.pid,
                app=args.app,
                max_samples=args.max_samples,
                duration_seconds=args.duration_seconds,
            ).run()
            store.finalize(result.status)
    except TransportError:
        store.finalize("failed")
        raise
    if args.compress:
        compress_run(store.directory)
    _print_json(
        {
            "run_dir": str(store.directory),
            "run_id": store.run_id,
            "status": result.status,
            "samples": result.samples,
            "reason": result.reason,
        }
    )
    return {"complete": 0, "incomplete": EXIT_INCOMPLETE}.get(result.status, EXIT_TRANSPORT)


def _cmd_annotate(args: argparse.Namespace) -> int:
    with RunStore.open_existing(args.run) as store:
        annotate(
            store,
            phase=args.phase,
            boundary_reason=args.segment_boundary,
            note=args.note,
        )
    print(f"axis-memlab: annotation appended to {args.run}")
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    if args.level == "deep":
        print(
            "axis-memlab: 'deep' snapshots (full smaps, allocator reports) are not available: "
            "the safety model forbids them (allow_deep_snapshot must stay false) until a "
            "separate review enables them. No snapshot was taken.",
            file=sys.stderr,
        )
        return 3
    config = load_config(args.config)
    _require_host_ssh(config)
    with RunStore.open_existing(args.run) as store:
        device_id = str(store.manifest["device_identity"])
        result = Collector(
            _reader(args, config),
            store,
            config,
            device_id=device_id,
            pid=args.pid,
            app=args.app,
        ).snapshot()
    _print_json({"status": result.status, "samples": result.samples, "reason": result.reason})
    return 0 if result.status == "complete" else EXIT_TRANSPORT


def _cmd_import(args: argparse.Namespace) -> int:
    if (args.run / "manifest.json").exists():
        store = RunStore.open_existing(args.run)
    else:
        if not args.device_id or not args.scenario:
            raise CollectionError("a new run needs --device-id and --scenario")
        run_id = peek_run_id(args.input)
        manifest = build_manifest(
            run_id=run_id,
            device_id=validate_device_id(args.device_id),
            scenario=args.scenario,
            privacy_classification=args.privacy_classification,
        )
        parent = args.out or args.run.parent
        store = RunStore.create(parent, manifest)
    with store:
        summary = import_records(args.input, store)
        store.finalize("complete" if not summary.rejected else "incomplete")
    _print_json({"run_dir": str(store.directory), **summary.as_dict()})
    if summary.rejected:
        print(
            f"axis-memlab: {len(summary.rejected)} line(s) were rejected and not imported",
            file=sys.stderr,
        )
    return 4 if summary.rejected and summary.accepted == 0 else 0


def _cmd_purge(args: argparse.Namespace) -> int:
    if args.older_than_days < 1:
        raise CollectionError("--older-than-days must be at least 1")
    old = find_old_runs(args.root, args.older_than_days)
    for path in old:
        print(("delete " if args.confirm else "would delete ") + str(path))
    if args.confirm:
        print(f"axis-memlab: removed {purge_runs(old)} run(s)")
    else:
        print(f"axis-memlab: {len(old)} run(s) match; re-run with --confirm to delete")
    return 0


_HANDLERS = {
    "discover": _cmd_discover,
    "collect": _cmd_collect,
    "annotate": _cmd_annotate,
    "snapshot": _cmd_snapshot,
    "import": _cmd_import,
    "purge": _cmd_purge,
}


def run_device_command(args: argparse.Namespace) -> int:
    try:
        return _HANDLERS[args.command](args)
    except (CollectionError, ConfigError) as exc:
        print(f"axis-memlab: {exc}", file=sys.stderr)
        return 2
    except TransportError as exc:
        print(f"axis-memlab: transport failure: {exc}", file=sys.stderr)
        return EXIT_TRANSPORT
    except (RunDataError, OSError) as exc:
        print(f"axis-memlab: {exc}", file=sys.stderr)
        return 4
