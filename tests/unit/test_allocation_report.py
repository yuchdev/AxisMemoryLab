"""Site aggregation, estimator semantics, honesty of the report, and the symbolize command."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from elf_builder import build_elf
from jsonschema import Draft202012Validator, FormatChecker
from sample_files import RUN_ID, alloc, free, header, module, summary, write_samples

from axis_memlab.cli import main
from axis_memlab.reporting.markdown import render_markdown
from axis_memlab.symbolization.report import aggregate, build_report, confidence, relative_error
from axis_memlab.symbolization.resolve import Resolver, SymbolIndex
from axis_memlab.symbolization.stackmap import load_samples

ROOT = Path(__file__).resolve().parents[2]
BUILD = "aabbccddeeff00112233445566778899aabbccdd"
SYMBOLS = [
    ("_start", 0x1000, 0x40),
    ("leaky_function", 0x1100, 0x80),
    ("_ZN3foo3barEv", 0x1200, 0x40),
]
BASE = 0x400000
LEAK_STACK = [BASE + 0x1105, BASE + 0x1005]  # leaky_function <- _start
CHURN_STACK = [BASE + 0x1205, BASE + 0x1005]  # foo::bar <- _start
NOW = datetime(2026, 1, 2, tzinfo=UTC)


@pytest.fixture
def symbols(tmp_path: Path) -> Path:
    directory = tmp_path / "symbols"
    directory.mkdir()
    build_elf(directory / "app.debug", build_id=bytes.fromhex(BUILD), symbols=SYMBOLS)
    return directory


def _lines(extra_summary: dict[str, Any] | None = None, **header_over: Any) -> list[Any]:
    """200 samples at a leaking site (never freed), 300 at a churning site (all freed)."""
    lines: list[Any] = [header([module("app", BUILD, BASE)], **header_over)]
    for i in range(1, 201):
        lines.append(alloc(i, 1024, LEAK_STACK))
    for i in range(201, 501):
        lines.append(alloc(i, 4096, CHURN_STACK))
        lines.append(free(i))
    # By construction the exact requested volume equals what the weighted samples stand for.
    w_leak = 1 / -math.expm1(-1024 / 4096)
    w_churn = 1 / -math.expm1(-4096 / 4096)
    exact = round(200 * w_leak * 1024 + 300 * w_churn * 4096)
    lines.append(
        summary(**{"alloc_request_bytes": exact, "samples_taken": 500, **(extra_summary or {})})
    )
    return lines


def _report(tmp_path: Path, symbols: Path, lines: list[Any], **kw: Any) -> dict[str, Any]:
    path = write_samples(tmp_path / "s.jsonl", lines)
    session = load_samples(path).sessions[-1]
    resolver = Resolver(SymbolIndex.build(symbols), tool="builtin", demangle=False)
    sites = aggregate(
        session, resolver, skip_top=kw.pop("skip_top", 0), max_depth=kw.pop("max_depth", None)
    )
    return build_report(
        session,
        sites,
        resolver,
        top=kw.pop("top", 20),
        sort=kw.pop("sort", "live"),
        generated_at=NOW,
    )


def _sites(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in report["findings"] if f["type"] == "allocation_site"]


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return next(f for f in report["findings"] if f["type"] == "allocation_summary")


def test_live_and_cumulative_are_kept_apart(tmp_path: Path, symbols: Path) -> None:
    report = _report(tmp_path, symbols, _lines())
    by_name = {s["frames"][0]["label"]: s for s in _sites(report)}
    leak, churn = by_name["leaky_function"], by_name["_ZN3foo3barEv"]
    w_leak = 1 / -math.expm1(-1024 / 4096)
    w_churn = 1 / -math.expm1(-4096 / 4096)
    assert leak["estimated_live_bytes"] == pytest.approx(200 * w_leak * 1024)
    assert leak["estimated_cumulative_bytes"] == pytest.approx(leak["estimated_live_bytes"])
    # The churning site allocated a lot and holds nothing: cumulative must never leak into live.
    assert churn["estimated_live_bytes"] == 0 and churn["sampled_live"] == 0
    assert churn["estimated_cumulative_bytes"] == pytest.approx(300 * w_churn * 4096)
    assert churn["estimated_cumulative_bytes"] > leak["estimated_cumulative_bytes"]
    total = _summary(report)
    assert total["estimated_live_bytes"] == pytest.approx(leak["estimated_live_bytes"])
    assert total["estimated_cumulative_bytes"] == pytest.approx(
        leak["estimated_cumulative_bytes"] + churn["estimated_cumulative_bytes"]
    )


def test_ranking_follows_the_requested_measure(tmp_path: Path, symbols: Path) -> None:
    live = _sites(_report(tmp_path, symbols, _lines(), sort="live"))
    cumulative = _sites(_report(tmp_path, symbols, _lines(), sort="cumulative"))
    assert live[0]["frames"][0]["label"] == "leaky_function" and live[0]["ranked_by"] == "live"
    assert cumulative[0]["frames"][0]["label"] == "_ZN3foo3barEv"
    assert [s["rank"] for s in live] == [1, 2]


def test_site_identity_is_the_symbolized_stack(tmp_path: Path, symbols: Path) -> None:
    lines = _lines()
    lines.insert(1, alloc(900, 1024, [BASE + 0x1110, BASE + 0x1005]))  # same function, other pc
    report = _report(tmp_path, symbols, lines)
    leak = next(s for s in _sites(report) if s["frames"][0]["label"] == "leaky_function")
    assert leak["sampled_allocs"] == 201  # merged by function, not by raw address
    assert [f["label"] for f in leak["frames"]] == ["leaky_function", "_start"]
    assert leak["frames"][0]["status"] == "resolved"


def test_skip_top_and_max_depth_regroup_sites(tmp_path: Path, symbols: Path) -> None:
    report = _report(tmp_path, symbols, _lines(), skip_top=1)
    sites = _sites(report)
    assert len(sites) == 1 and sites[0]["frames"][0]["label"] == "_start"  # both sites merge
    assert sites[0]["sampled_allocs"] == 500
    depth_one = _sites(_report(tmp_path, symbols, _lines(), max_depth=1))
    assert all(len(s["frames"]) == 1 for s in depth_one)


def test_confidence_tiers_and_error_bars() -> None:
    assert [confidence(n) for n in (0, 1, 4, 5, 29, 30, 1000)] == [
        "low", "low", "low", "medium", "medium", "high", "high",
    ]  # fmt: skip
    assert relative_error(0) is None
    assert relative_error(100) == pytest.approx(0.1)


def test_calibration_compares_the_estimate_with_the_exact_total(
    tmp_path: Path, symbols: Path
) -> None:
    good = _summary(_report(tmp_path, symbols, _lines()))
    assert good["calibration"]["ratio"] == pytest.approx(1.0, rel=0.01)
    assert good["closing_summary_present"] is True
    bad = _report(tmp_path, symbols, _lines({"alloc_request_bytes": 10_000_000_000}))
    assert _summary(bad)["calibration"]["ratio"] < 0.01
    assert any("exact requested volume" in x for x in bad["limitations"])


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"dropped_free_events": 3}, "overstate"),
        ({"dropped_ring_full": 4}, "not recorded"),
        ({"dropped_table_full": 4}, "not recorded"),
        ({"dropped_output_cap": 2}, "size cap"),
        ({"stack_failures": 5}, "no stack"),
    ],
)
def test_drops_are_never_silent(
    tmp_path: Path, symbols: Path, overrides: dict[str, int], fragment: str
) -> None:
    report = _report(tmp_path, symbols, _lines(overrides))
    assert any(fragment in x for x in report["limitations"])


def test_missing_and_partial_summaries_are_called_out(tmp_path: Path, symbols: Path) -> None:
    no_summary = _lines()[:-1]
    report = _report(tmp_path, symbols, no_summary)
    assert any("No summary record" in x for x in report["limitations"])
    assert _summary(report)["calibration"]["ratio"] is None
    periodic = _lines()
    periodic[-1]["final"] = False
    report = _report(tmp_path, symbols, periodic)
    assert any("no closing summary" in x for x in report["limitations"])


def test_other_honesty_notes(tmp_path: Path, symbols: Path) -> None:
    lines = _lines(unwinder="caller_only")
    lines.append(free(9999))  # refers to a sample that is not in the file
    lines.append("{broken")
    report = _report(tmp_path, symbols, lines)
    text = " ".join(report["limitations"])
    assert (
        "only the call site" in text and "unknown samples" in text and "skipped as invalid" in text
    )
    assert "operator new" in text and "not live" in text.lower()  # the standing coverage notes
    assert "malloc" in text


def test_unresolved_frames_are_counted_and_never_guessed(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    report = _report(tmp_path, empty, _lines())
    assert _summary(report)["unresolved_frames"] > 0
    assert _summary(report)["frame_status_counts"]["no_symbols"] > 0
    assert all(f["function"] is None for s in _sites(report) for f in s["frames"])
    assert _sites(report)[0]["frames"][0]["label"].startswith("app+0x")
    assert any("could not be resolved" in x for x in report["limitations"])


def test_top_limits_the_listing_and_says_so(tmp_path: Path, symbols: Path) -> None:
    report = _report(tmp_path, symbols, _lines(), top=1)
    assert len(_sites(report)) == 1
    assert any("Only the top 1 of 2" in x for x in report["limitations"])


def test_report_conforms_to_the_report_schema_and_is_json_safe(
    tmp_path: Path, symbols: Path
) -> None:
    report = _report(tmp_path, symbols, _lines())
    schema = json.loads((ROOT / "schemas/report-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
    json.dumps(report, allow_nan=False)
    assert report["run_references"] == [RUN_ID]
    session = load_samples(write_samples(tmp_path / "t.jsonl", _lines())).sessions[0]
    resolver = Resolver(SymbolIndex(), tool="builtin")
    with pytest.raises(ValueError, match="timezone"):
        build_report(session, [], resolver, top=1, sort="live", generated_at=datetime(2026, 1, 1))


def test_markdown_labels_cumulative_as_not_live(tmp_path: Path, symbols: Path) -> None:
    text = render_markdown(_report(tmp_path, symbols, _lines()))
    assert "## Allocation summary" in text and "## Allocation sites (ranked by live)" in text
    assert "NOT live" in text and "cumulative est. bytes (not live)" in text
    assert "leaky_function <- _start" in text


def test_schema_accepts_what_the_loader_accepts(tmp_path: Path) -> None:
    schema = json.loads((ROOT / "schemas/alloc-samples-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for line in _lines():
        assert not list(validator.iter_errors(line)), line["type"]
    bad = alloc(1, 10, [0x1000])
    bad["weight_count"] = 0.5
    assert list(validator.iter_errors(bad))


# ---- the command -----------------------------------------------------------------------------------------
def _cli(tmp_path: Path, symbols: Path, *extra: str) -> list[str]:
    samples = write_samples(tmp_path / "cli.jsonl", _lines())
    return [
        "symbolize",
        "--samples",
        str(samples),
        "--symbols",
        str(symbols),
        "--tool",
        "builtin",
        *extra,
    ]


def test_symbolize_json_markdown_and_no_overwrite(
    tmp_path: Path, symbols: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_cli(tmp_path, symbols)) == 0
    report = json.loads(capsys.readouterr().out)
    assert _sites(report)[0]["frames"][0]["function"] == "leaky_function"
    out = tmp_path / "out.md"
    assert main([*_cli(tmp_path, symbols), "--format", "markdown", "--out", str(out)]) == 0
    assert "leaky_function" in out.read_text()
    assert main([*_cli(tmp_path, symbols), "--out", str(out)]) == 4  # evidence is never overwritten
    assert "exists" in capsys.readouterr().err.lower()


def test_symbolize_without_symbols_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    samples = write_samples(tmp_path / "n.jsonl", _lines())
    assert main(["symbolize", "--samples", str(samples), "--tool", "builtin"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert any("No symbol directory" in x for x in report["limitations"])


def test_symbolize_error_exit_codes(
    tmp_path: Path, symbols: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["symbolize", "--samples", str(tmp_path / "missing.jsonl")]) == 4
    junk = tmp_path / "junk.jsonl"
    junk.write_text("not json\n")
    assert main(["symbolize", "--samples", str(junk)]) == 4
    assert main(_cli(tmp_path, symbols, "--session", "5")) == 2
    assert main(_cli(tmp_path, symbols, "--top", "0")) == 2
    assert main(["symbolize", "--samples", str(junk), "--symbols", str(tmp_path / "nope")]) in (
        2,
        4,
    )
    assert "Traceback" not in capsys.readouterr().err


def test_symbolize_picks_the_last_session_by_default(
    tmp_path: Path, symbols: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _lines()
    second = [
        header([module("app", BUILD, BASE)]),
        alloc(1, 64, LEAK_STACK),
        summary(alloc_request_bytes=64),
    ]
    samples = write_samples(tmp_path / "two.jsonl", [*first, *second])
    args = ["symbolize", "--samples", str(samples), "--symbols", str(symbols), "--tool", "builtin"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert _summary(report)["session"] == 2 and any(
        "2 sessions" in x for x in report["limitations"]
    )
    assert main([*args, "--session", "1"]) == 0
    assert _summary(json.loads(capsys.readouterr().out))["session"] == 1
