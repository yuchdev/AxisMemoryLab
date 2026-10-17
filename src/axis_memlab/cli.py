"""Argument parser and host-local CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axis_memlab import __version__
from axis_memlab.analysis.compare import compare_runs
from axis_memlab.analysis.engine import analyze_run, build_report
from axis_memlab.analysis.load import load_run
from axis_memlab.analysis.settings import AnalysisSettings
from axis_memlab.cli_device import DEVICE_COMMANDS, add_device_commands, run_device_command
from axis_memlab.cli_symbolize import add_symbolize_command, run_symbolize
from axis_memlab.config import load_config
from axis_memlab.errors import ConfigError, RunDataError
from axis_memlab.reporting import load_report
from axis_memlab.reporting.csv import render_csv
from axis_memlab.reporting.html import render_html
from axis_memlab.reporting.markdown import render_markdown

_PLANNED: dict[str, str] = {}


def build_parser() -> argparse.ArgumentParser:
    """Build the command tree without performing I/O."""
    parser = argparse.ArgumentParser(prog="axis-memlab", description="AXIS memory lab host CLI")
    parser.add_argument("--version", action="version", version=f"axis-memory-lab {__version__}")
    commands = parser.add_subparsers(dest="command")
    config_parser = commands.add_parser("config", help="validate a local TOML profile")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    check = config_commands.add_parser("check", help="validate configuration safety and fields")
    check.add_argument("--file", required=True, type=Path, help="TOML configuration path")
    analyze = commands.add_parser("analyze", help="trend analysis of a local run archive")
    analyze.add_argument("--run", required=True, type=Path, help="run directory")
    analyze.add_argument("--config", required=True, type=Path, help="TOML profile")
    analyze.add_argument(
        "--correlate",
        action="append",
        default=[],
        metavar="A:B",
        help="correlate interval changes of two metrics (repeatable)",
    )
    analyze.add_argument("--out", type=Path, help="write report JSON here (must not exist)")
    compare = commands.add_parser("compare", help="compare post-warm-up growth of two runs")
    compare.add_argument("--baseline", required=True, type=Path)
    compare.add_argument("--candidate", required=True, type=Path)
    compare.add_argument("--config", required=True, type=Path)
    compare.add_argument("--phase", help="only compare segments of this phase")
    compare.add_argument("--out", type=Path, help="write report JSON here (must not exist)")
    report = commands.add_parser("report", help="render a report JSON as Markdown, HTML or CSV")
    report.add_argument("--input", required=True, type=Path, help="report JSON from analyze")
    report.add_argument("--format", required=True, choices=("markdown", "html", "csv"))
    report.add_argument("--out", type=Path, help="write here (must not exist) instead of stdout")
    add_device_commands(commands)
    add_symbolize_command(commands)
    for name, milestone in _PLANNED.items():
        planned = commands.add_parser(name, help=f"planned for milestone {milestone}")
        planned.description = (
            f"Planned for milestone {milestone}; no device operation is implemented."
        )
        planned.set_defaults(planned_milestone=milestone)
    return parser


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    with out.open("x", encoding="utf-8") as stream:  # never overwrite existing evidence
        stream.write(text)


def _settings(path: Path) -> AnalysisSettings:
    return AnalysisSettings.from_config(load_config(path))


def _parse_pairs(values: list[str]) -> tuple[tuple[str, str], ...]:
    pairs = []
    for value in values:
        left, sep, right = value.partition(":")
        if not sep or not left or not right:
            raise ConfigError(f"--correlate expects METRIC_A:METRIC_B, got {value!r}")
        pairs.append((left, right))
    return tuple(pairs)


def _run_analysis_command(args: argparse.Namespace) -> str:
    now = datetime.now(UTC)
    if args.command == "report":
        loaded = load_report(args.input)
        renderers = {"markdown": render_markdown, "html": render_html, "csv": render_csv}
        return renderers[args.format](loaded)
    settings = _settings(args.config)
    if args.command == "analyze":
        pairs = _parse_pairs(args.correlate)
        run = load_run(args.run)
        findings, limitations = analyze_run(run, settings, pairs)
        doc: dict[str, Any] = build_report([run], findings, limitations, now)
    elif args.command == "compare":
        baseline, candidate = load_run(args.baseline), load_run(args.candidate)
        findings, limitations = compare_runs(baseline, candidate, settings, args.phase)
        doc = build_report([baseline, candidate], findings, limitations, now)
    else:
        raise AssertionError(args.command)
    return json.dumps(doc, indent=2, sort_keys=True, allow_nan=False) + "\n"


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
    if args.command == "symbolize":
        return run_symbolize(args)
    if args.command in DEVICE_COMMANDS:
        return run_device_command(args)
    if args.command in ("analyze", "compare", "report"):
        try:
            text = _run_analysis_command(args)
            _emit(text, args.out)
        except ConfigError as exc:
            print(f"axis-memlab: {exc}", file=sys.stderr)
            return 2
        except (RunDataError, OSError) as exc:
            print(f"axis-memlab: {exc}", file=sys.stderr)
            return 4
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
