"""Argument parser and host-local CLI handlers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from axis_memlab import __version__
from axis_memlab.config import load_config
from axis_memlab.errors import ConfigError

_PLANNED = {
    "discover": "0001",
    "collect": "0001",
    "annotate": "0001",
    "snapshot": "0001",
    "import": "0001",
    "analyze": "0002",
    "compare": "0002",
    "symbolize": "0004",
    "report": "0002",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the command tree without performing I/O."""
    parser = argparse.ArgumentParser(prog="axis-memlab", description="AXIS memory lab host CLI")
    parser.add_argument("--version", action="version", version=f"axis-memory-lab {__version__}")
    commands = parser.add_subparsers(dest="command")
    config_parser = commands.add_parser("config", help="validate a local TOML profile")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    check = config_commands.add_parser("check", help="validate configuration safety and fields")
    check.add_argument("--file", required=True, type=Path, help="TOML configuration path")
    for name, milestone in _PLANNED.items():
        planned = commands.add_parser(name, help=f"planned for milestone {milestone}")
        planned.description = (
            f"Planned for milestone {milestone}; no device operation is implemented."
        )
        planned.set_defaults(planned_milestone=milestone)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one CLI command and return its documented exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "config" and args.config_command == "check":
        try:
            load_config(args.file)
        except ConfigError as exc:
            print(f"axis-memlab: {exc}", file=sys.stderr)
            return 2
        except OSError:
            print(f"axis-memlab: cannot read configuration file: {args.file}", file=sys.stderr)
            return 4
        print(f"axis-memlab: configuration is valid: {args.file}")
        return 0
    if args.command in _PLANNED:
        print(
            f"axis-memlab: '{args.command}' is planned for milestone "
            f"{args.planned_milestone}; no {args.command} was performed",
            file=sys.stderr,
        )
        return 3
    parser.print_help()
    return 0
