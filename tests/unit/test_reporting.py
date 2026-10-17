"""CLI analysis commands and report renderers, offline on synthetic runs."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from synthetic_traces import linear, write_run

from axis_memlab.cli import main

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/default.toml"
PSS = "process.pss_bytes"


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return write_run(
        tmp_path / "run",
        {PSS: linear(1e6, 500), "app.queue.depth_bytes": linear(0, 300)},
        events=[(0.0, {"event": "phase_start", "phase": "=cmd|'<script>'!A1"})],
    )


def _analyze(run_dir: Path, out: Path) -> dict[str, object]:
    assert main(["analyze", "--run", str(run_dir), "--config", str(CONFIG), "--out", str(out)]) == 0
    loaded: dict[str, object] = json.loads(out.read_text())
    return loaded


def test_analyze_writes_report_and_refuses_to_overwrite(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report.json"
    doc = _analyze(run_dir, out)
    assert doc["schema_version"] == 1
    args = ["analyze", "--run", str(run_dir), "--config", str(CONFIG), "--out", str(out)]
    assert main(args) == 4  # evidence is never overwritten
    assert "exists" in capsys.readouterr().err.lower()


def test_analyze_stdout_is_json(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", "--run", str(run_dir), "--config", str(CONFIG)]) == 0
    assert json.loads(capsys.readouterr().out)["run_references"]


def test_exit_codes_for_bad_inputs(
    run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["analyze", "--run", str(tmp_path / "missing"), "--config", str(CONFIG)]) == 4
    assert main(["analyze", "--run", str(run_dir), "--config", str(tmp_path / "no.toml")]) == 4
    bad = tmp_path / "bad.toml"
    bad.write_text("[collection]\n")
    assert main(["analyze", "--run", str(run_dir), "--config", str(bad)]) == 2
    assert (
        main(["analyze", "--run", str(run_dir), "--config", str(CONFIG), "--correlate", "x"]) == 2
    )
    junk = tmp_path / "junk.json"
    junk.write_text("[]")
    assert main(["report", "--input", str(junk), "--format", "markdown"]) == 4
    assert "Traceback" not in capsys.readouterr().err


def test_compare_command(run_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    other = write_run(
        tmp_path / "other",
        {PSS: linear(1e6, 0, noise=1)},
        run_id="00000000-0000-4000-8000-0000000000bb",
    )
    argv = [
        "compare",
        "--baseline",
        str(other),
        "--candidate",
        str(run_dir),
        "--config",
        str(CONFIG),
    ]
    assert main(argv) == 0
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["run_references"]) == 2
    assert any(f["type"] == "comparison" and f["status"] == "compared" for f in doc["findings"])


def test_markdown_html_csv_renderers(run_dir: Path, tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    _analyze(run_dir, report)
    outputs = {}
    for fmt in ("markdown", "html", "csv"):
        out = tmp_path / f"report.{fmt}"
        assert main(["report", "--input", str(report), "--format", fmt, "--out", str(out)]) == 0
        outputs[fmt] = out.read_text()

    markdown = outputs["markdown"]
    assert "## Limitations" in markdown and "## Trends" in markdown
    assert "does not establish a cause" in markdown
    assert "not_evaluated" in markdown

    page = outputs["html"]
    assert "<script" not in page and "&lt;script&gt;" in page
    assert "default-src 'none'" in page

    rows = list(csv.DictReader(io.StringIO(outputs["csv"])))
    assert rows and {"value_unit", "slope_unit", "slope_per_hour"} <= set(rows[0])
    pss = next(r for r in rows if r["metric"] == PSS and r["window"] == "post_warmup")
    assert pss["value_unit"] == "bytes" and pss["slope_unit"] == "bytes per hour"
    assert all(not r["phase"].startswith("=") for r in rows)  # formula injection neutralised
    assert rows[0]["phase"].startswith("'=")


def test_no_command_is_left_as_a_placeholder() -> None:
    from axis_memlab.cli import _PLANNED, build_parser

    assert _PLANNED == {}  # every command now does what it says; M0005 may add planned ones
    help_text = build_parser().format_help()
    assert "symbolize" in help_text and "discover" in help_text
