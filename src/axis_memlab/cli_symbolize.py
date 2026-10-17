"""``axis-memlab symbolize``: resolve allocation samples to call sites, offline.

Runs on the host only. It reads a sample file written by the in-app sampler and a local directory
of unstripped binaries whose build-ids must match the modules in the file; it never contacts a
network service and never executes the binaries. Exit codes follow ``cli.py``: 2 for a bad request
(missing tool or symbols directory), 4 for unreadable or invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from axis_memlab.errors import CollectionError, RunDataError
from axis_memlab.reporting.markdown import render_markdown
from axis_memlab.symbolization.report import aggregate, build_report
from axis_memlab.symbolization.resolve import TOOLS, Resolver, SymbolIndex
from axis_memlab.symbolization.stackmap import load_samples


def add_symbolize_command(commands: Any) -> None:
    p = commands.add_parser(
        "symbolize", help="resolve sampled allocation stacks to call sites (host only)"
    )
    p.add_argument("--samples", required=True, type=Path, help="alloc-samples-v1 JSON Lines file")
    p.add_argument(
        "--symbols",
        type=Path,
        help="directory of unstripped binaries; matched to modules by build-id, never by name",
    )
    p.add_argument("--tool", choices=TOOLS, default="auto", help="symbol backend (default auto)")
    p.add_argument("--session", type=int, help="1-based session in the file (default: the last)")
    p.add_argument("--top", type=int, default=20, help="sites to list (default 20)")
    p.add_argument("--sort", choices=("live", "cumulative"), default="live")
    p.add_argument("--skip-top", type=int, default=0, help="drop this many leading frames")
    p.add_argument("--max-depth", type=int, help="group by at most this many frames")
    p.add_argument("--no-demangle", action="store_true")
    p.add_argument("--format", choices=("json", "markdown"), default="json")
    p.add_argument("--out", type=Path, help="write here (must not exist) instead of stdout")


def run_symbolize(args: argparse.Namespace) -> int:
    try:
        return _run(args)
    except CollectionError as exc:
        print(f"axis-memlab: {exc}", file=sys.stderr)
        return 2
    except (RunDataError, OSError) as exc:
        print(f"axis-memlab: {exc}", file=sys.stderr)
        return 4


def _run(args: argparse.Namespace) -> int:
    if args.top < 1 or args.skip_top < 0 or (args.max_depth is not None and args.max_depth < 1):
        raise CollectionError(
            "--top and --max-depth must be positive; --skip-top cannot be negative"
        )
    samples = load_samples(args.samples)
    if args.session is None:
        session = samples.sessions[-1]
    elif 1 <= args.session <= len(samples.sessions):
        session = samples.sessions[args.session - 1]
    else:
        raise CollectionError(f"--session must be between 1 and {len(samples.sessions)}")
    index = SymbolIndex.build(args.symbols) if args.symbols else SymbolIndex()
    resolver = Resolver(index, tool=args.tool, demangle=not args.no_demangle)
    sites = aggregate(session, resolver, skip_top=args.skip_top, max_depth=args.max_depth)
    report = build_report(
        session, sites, resolver, top=args.top, sort=args.sort, generated_at=datetime.now(UTC)
    )
    if args.symbols is None:
        report["limitations"].append(
            "No symbol directory was given; frames are shown as module+offset."
        )
    if samples.problems:
        report["limitations"].append(
            f"{len(samples.problems)} line(s) outside any session were skipped as invalid."
        )
    if len(samples.sessions) > 1 and args.session is None:
        report["limitations"].append(
            f"The file holds {len(samples.sessions)} sessions; session {session.index} (the last) "
            "was analysed."
        )
    text = (
        render_markdown(report)
        if args.format == "markdown"
        else json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    if args.out is None:
        sys.stdout.write(text)
    else:
        with args.out.open("x", encoding="utf-8") as stream:  # never overwrite evidence
            stream.write(text)
    return 0
