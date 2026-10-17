"""Trend, phase, hypothesis, comparison, and correlation tests on synthetic traces."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from synthetic_traces import linear, ramp_then_flat, write_run

from axis_memlab.analysis.compare import compare_runs
from axis_memlab.analysis.correlate import spearman
from axis_memlab.analysis.engine import analyze_run, build_report
from axis_memlab.analysis.load import load_run
from axis_memlab.analysis.phase import segment_run
from axis_memlab.analysis.settings import AnalysisSettings
from axis_memlab.analysis.trend import summarize
from axis_memlab.errors import RunDataError

ROOT = Path(__file__).resolve().parents[2]
PSS = "process.pss_bytes"
RSS = "process.rss_anon_bytes"
AVAIL = "system.mem.available_bytes"
SETTINGS = AnalysisSettings(
    warmup_seconds=60,
    minimum_samples=10,
    metrics=(AVAIL, RSS, PSS),
    normalization=("elapsed_seconds",),
)
NOW = datetime(2026, 1, 2, tzinfo=UTC)


def _analyze(
    path: Path, settings: AnalysisSettings = SETTINGS, **kw: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    return analyze_run(load_run(path), settings, **kw)


def _ids(findings: list[dict[str, Any]], status: str = "observed") -> set[str]:
    return {f["id"] for f in findings if f["type"] == "hypothesis" and f["status"] == status}


def _trend(findings: list[dict[str, Any]], metric: str, segment: int = 0) -> dict[str, Any]:
    return next(
        f
        for f in findings
        if f["type"] == "trend" and f["metric"] == metric and f["segment"] == segment
    )


def test_linear_growth_reports_exact_robust_slope(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", {PSS: linear(1_000_000, 100, noise=3)})
    post = _trend(_analyze(run)[0], PSS)["post_warmup"]
    assert post["direction"] == "rising"
    assert post["slope_per_hour"] == pytest.approx(100 * 3600, rel=0.02)
    assert post["n"] > 100 and post["min"] <= post["start"] <= post["max"]


def test_growth_with_queue_growth_is_a_hypothesis_not_a_diagnosis(tmp_path: Path) -> None:
    run = write_run(
        tmp_path / "r",
        {PSS: linear(1e6, 500), "app.queue.depth_bytes": linear(0, 400), AVAIL: linear(9e7, 0)},
    )
    findings, _ = _analyze(run)
    assert "H-RETENTION" in _ids(findings)
    hypothesis = next(f for f in findings if f.get("id") == "H-RETENTION")
    assert "does not establish a cause" in hypothesis["caveat"]
    assert hypothesis["alternatives"] and hypothesis["next_comparison"]


def test_unexplained_growth_is_labelled_unattributed(tmp_path: Path) -> None:
    findings, _ = _analyze(write_run(tmp_path / "r", {PSS: linear(1e6, 500)}))
    assert _ids(findings) == {"H-UNATTRIBUTED"}


def test_plateau_after_warmup_is_not_growth(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", {PSS: ramp_then_flat(1e6, 20_000, 50)}, seconds=900)
    findings, _ = _analyze(run)
    trend = _trend(findings, PSS)
    assert trend["warmup"]["direction"] == "rising"
    assert trend["post_warmup"]["direction"] == "flat"
    assert _ids(findings) == {"H-PLATEAU"}


def test_system_decline_with_flat_process_does_not_claim_kernel_leak(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", {AVAIL: linear(9e7, -20000), PSS: linear(1e6, 0, noise=1)})
    findings, _ = _analyze(run)
    assert _ids(findings) == {"H-NOT-IN-PROCESS"}
    hypothesis = next(f for f in findings if f.get("id") == "H-NOT-IN-PROCESS")
    assert "kernel" not in json.dumps(hypothesis).lower().replace("driver", "")


def test_allocator_hypothesis_needs_flat_tracked_live_bytes(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", {RSS: linear(1e6, 800), "app.live_bytes": linear(5e5, 0)})
    assert "H-ALLOCATOR" in _ids(_analyze(run)[0])


def test_process_restart_starts_a_new_segment_and_is_not_fitted_across(tmp_path: Path) -> None:
    run = write_run(
        tmp_path / "r",
        {PSS: lambda t: 1e6 + 100 * (t if t < 300 else t - 300)},
        pid_at=lambda t: 10 if t < 300 else 11,
    )
    loaded = load_run(run)
    segments = segment_run(loaded)
    assert [s.start_reason for s in segments] == ["run_start", "process_restart"]
    findings, _ = analyze_run(loaded, SETTINGS)
    second = _trend(findings, PSS, segment=1)["post_warmup"]
    assert second["slope_per_hour"] == pytest.approx(360_000, rel=0.02)  # no negative jump


def test_phase_markers_split_and_label_segments(tmp_path: Path) -> None:
    events = [
        (0.0, {"event": "phase_start", "phase": "T1"}),
        (300.0, {"event": "phase_start", "phase": "T2"}),
        (450.0, {"event": "segment_boundary", "reason": "config change"}),
    ]
    run = write_run(tmp_path / "r", {PSS: linear(1e6, 10)}, events=events)
    segments = segment_run(load_run(run))
    assert [(s.phase, s.start_reason) for s in segments] == [
        ("T1", "phase_start:T1"),
        ("T2", "phase_start:T2"),
        ("T2", "config change"),
    ]


def test_too_little_data_gives_no_slope_and_a_limitation(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", {PSS: linear(1e6, 100)}, seconds=120)
    findings, limitations = _analyze(run)
    post = _trend(findings, PSS)["post_warmup"]
    assert post["direction"] == "insufficient_data" or post["n"] >= 10
    short = write_run(tmp_path / "s", {PSS: linear(1e6, 100)}, seconds=40)
    findings, limitations = _analyze(short)
    post = _trend(findings, PSS)["post_warmup"]
    assert post["direction"] == "insufficient_data" and post["slope_per_hour"] is None
    assert any("too little data" in item for item in limitations)
    assert not _ids(findings)


def test_unavailable_is_counted_never_treated_as_zero(tmp_path: Path) -> None:
    run = write_run(tmp_path / "r", {PSS: lambda t: None, AVAIL: linear(9e7, 0)})
    findings, limitations = _analyze(run)
    trend = _trend(findings, PSS)
    assert trend["unavailable_samples"] > 0
    assert trend["post_warmup"]["direction"] == "insufficient_data"
    assert trend["post_warmup"]["start"] is None
    assert RSS in "".join(limitations)  # requested but absent


def test_growth_normalized_per_1000_counter_units(tmp_path: Path) -> None:
    run = write_run(
        tmp_path / "r", {PSS: linear(1e6, 1000), "app.frames_total_count": linear(0, 10)}
    )
    settings = AnalysisSettings(60, 10, (PSS,), ("elapsed_seconds", "app.frames_total_count"))
    normalized = _trend(_analyze(run, settings)[0], PSS)["normalized"]
    assert normalized[0]["value"] == pytest.approx(100_000)
    assert normalized[0]["unit"] == "bytes per 1000 app.frames_total_count"


def test_corrupt_and_foreign_lines_are_reported_not_dropped_silently(tmp_path: Path) -> None:
    bad = ["{not json", json.dumps({"schema_version": 1, "run_id": "other"})]
    run = write_run(tmp_path / "r", {PSS: linear(1e6, 1)}, extra_lines=bad)
    loaded = load_run(run)
    assert len(loaded.problems) == 2
    assert any("invalid JSON" in p for p in loaded.problems)
    _, limitations = analyze_run(loaded, SETTINGS)
    assert any("invalid JSON" in item for item in limitations)


def test_invalid_manifest_raises(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "records.jsonl").write_text("")
    with pytest.raises(RunDataError):
        load_run(tmp_path)


def test_report_matches_schema_and_avoids_overclaiming(tmp_path: Path) -> None:
    run = load_run(
        write_run(tmp_path / "r", {PSS: linear(1e6, 500), "app.queue.depth_bytes": linear(0, 5)})
    )
    findings, limitations = analyze_run(
        run, SETTINGS, (("process.pss_bytes", "app.queue.depth_bytes"),)
    )
    doc = build_report([run], findings, limitations, NOW)
    schema = json.loads((ROOT / "schemas/report-v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(doc)
    json.dumps(doc, allow_nan=False)
    text = json.dumps(doc).lower()
    for phrase in ("confirmed", "is a leak", "definitely", "proves"):
        assert phrase not in text
    assert any(f["status"] == "not_evaluated" for f in doc["findings"] if f["type"] == "hypothesis")
    with pytest.raises(ValueError, match="timezone"):
        build_report([run], findings, limitations, datetime(2026, 1, 2))


def test_comparison_reports_delta_and_uncontrolled_fields(tmp_path: Path) -> None:
    base = load_run(
        write_run(
            tmp_path / "a", {PSS: linear(1e6, 0, noise=1)}, manifest={"firmware_version": "A"}
        )
    )
    cand = load_run(
        write_run(
            tmp_path / "b",
            {PSS: linear(1e6, 200)},
            run_id="00000000-0000-4000-8000-0000000000bb",
            manifest={"firmware_version": "B"},
        )
    )
    findings, limitations = compare_runs(base, cand, SETTINGS)
    pss = next(f for f in findings if f["metric"] == PSS)
    assert pss["status"] == "compared"
    assert pss["slope_delta_per_hour"] == pytest.approx(200 * 3600, rel=0.02)
    absent = next(f for f in findings if f["metric"] == RSS)
    assert absent["status"] == "not_compared" and "absent" in absent["reason"]
    assert any("firmware_version differs" in item for item in limitations)
    assert any("not recorded" in item for item in limitations)
    assert any("two repetitions" in item for item in limitations)


def test_correlation_of_interval_changes(tmp_path: Path) -> None:
    run = write_run(
        tmp_path / "r",
        {
            PSS: lambda t: 1e6 + sum(((i * 7) % 5) * 100 for i in range(int(t) // 5)),
            "app.queue.depth_bytes": lambda t: sum(((i * 7) % 5) * 10 for i in range(int(t) // 5)),
            "app.const_count": lambda t: 4.0,
        },
    )
    findings, _ = _analyze(
        run, correlations=((PSS, "app.queue.depth_bytes"), (PSS, "app.const_count"))
    )
    rho, constant = (f for f in findings if f["type"] == "correlation")
    assert rho["spearman_rho"] == pytest.approx(1.0)
    assert constant["spearman_rho"] is None and constant["reason"]
    assert "does not show cause" in rho["interpretation"]


def test_spearman_handles_ties() -> None:
    assert spearman([1, 2, 2, 3], [1, 2, 2, 3]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_summarize_flat_noise_is_not_rising() -> None:
    points = [(float(i), 1000.0 + ((i * 7) % 5)) for i in range(60)]
    assert summarize(points, 10).direction == "flat"
