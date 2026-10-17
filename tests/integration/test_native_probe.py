"""End to end: C++ probe simulator -> record-v1 JSON Lines -> Python trend analysis.

Builds the native library in LEDGER mode with CMake. Skipped when CMake or a C++ toolchain is
missing; fails (not skips) on any other build problem. The simulator is fully synthetic.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from axis_memlab.analysis.engine import analyze_run
from axis_memlab.analysis.load import load_run
from axis_memlab.analysis.settings import AnalysisSettings

pytestmark = pytest.mark.native

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "00000000-0000-4000-8000-0000000000d4"
SETTINGS = AnalysisSettings(
    warmup_seconds=0,
    minimum_samples=10,
    metrics=("process.rss_anon_bytes",),
    normalization=("elapsed_seconds",),
)


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def simulator(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("native-ledger")
    configure = _run(["cmake", "-S", str(ROOT / "native"), "-B", str(build), "-DAXMEM_LEDGER=ON"])
    if configure.returncode != 0:
        if "No CMAKE_CXX_COMPILER" in configure.stderr + configure.stdout:
            pytest.skip("no C++ compiler available")
        pytest.fail(f"cmake configure failed:\n{configure.stdout}\n{configure.stderr}")
    built = _run(
        [
            "cmake",
            "--build",
            str(build),
            "--config",
            "Release",
            "--target",
            "axis_memlab_lifecycle_simulator",
        ]
    )
    assert built.returncode == 0, built.stdout + built.stderr
    found = [
        p
        for p in build.rglob("axis_memlab_lifecycle_simulator*")
        if p.is_file() and p.suffix in ("", ".exe")
    ]
    assert found, "simulator binary not found"
    return found[0]


def _simulate(simulator: Path, tmp_path: Path, mode: str, *extra: str, label: str = "") -> Path:
    run_dir = tmp_path / (label or mode)
    run_dir.mkdir()
    result = _run([str(simulator), str(run_dir / "records.jsonl"), mode, *extra])
    assert result.returncode == 0, result.stderr
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "created_at": "2026-01-01T00:00:00Z",
                "device_identity": "synthetic-device-001",
                "scenario": f"native-simulator-{mode}",
                "privacy_classification": "synthetic",
                "status": "complete",
            }
        )
    )
    return run_dir


def _trend(findings: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    return next(f for f in findings if f["type"] == "trend" and f["metric"] == metric)


def test_probe_output_validates_against_record_schema(simulator: Path, tmp_path: Path) -> None:
    run_dir = _simulate(simulator, tmp_path, "leak")
    schema = json.loads((ROOT / "schemas/record-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    lines = (run_dir / "records.jsonl").read_text().splitlines()
    assert len(lines) == 41  # one phase event + 40 snapshots
    for line in lines:
        errors = list(validator.iter_errors(json.loads(line)))
        assert not errors, errors[0].message
    sample = json.loads(lines[-1])
    assert sample["identity"]["device_id"] == "synthetic-device-001"
    assert sample["annotations"]["ledger"]["oldest_live"][0]["kind"] == "frame"
    # Unreadable process memory is explicit on platforms without procfs, never zero.
    rss = sample["metrics"]["process.rss_anon_bytes"]
    assert "value" in rss or rss["available"] is False


def test_injected_release_defect_is_visible_in_trends(simulator: Path, tmp_path: Path) -> None:
    leak, _ = analyze_run(load_run(_simulate(simulator, tmp_path, "leak")), SETTINGS)
    healthy, _ = analyze_run(load_run(_simulate(simulator, tmp_path, "ok")), SETTINGS)
    live = "app.resource.frame.in_flight_count"
    live_bytes = "app.resource.frame.in_flight_bytes"
    assert _trend(leak, live)["post_warmup"]["direction"] == "rising"
    assert _trend(leak, live_bytes)["post_warmup"]["direction"] == "rising"
    assert _trend(healthy, live)["post_warmup"]["direction"] == "flat"
    # The totals keep moving in both runs; only the difference exposes the defect.
    assert (
        _trend(healthy, "app.resource.frame.acquired_total_count")["post_warmup"]["direction"]
        == "rising"
    )
    segment = next(f for f in leak if f["type"] == "segment")
    assert segment["phase"] == "T2"


def test_undrained_queue_is_distinguished_from_unreleased_frames(
    simulator: Path, tmp_path: Path
) -> None:
    findings, _ = analyze_run(load_run(_simulate(simulator, tmp_path, "queue")), SETTINGS)
    assert _trend(findings, "app.queue.depth_count")["post_warmup"]["direction"] == "rising"
    assert (
        _trend(findings, "app.resource.frame.in_flight_count")["post_warmup"]["direction"] == "flat"
    )


def test_simulator_rejects_unknown_mode(simulator: Path, tmp_path: Path) -> None:
    result = _run([str(simulator), str(tmp_path / "x.jsonl"), "bogus"])
    assert result.returncode == 2
    assert not (tmp_path / "x.jsonl").exists()


def test_one_leaked_frame_in_500_is_found_by_the_ledger_without_smaps(
    simulator: Path, tmp_path: Path
) -> None:
    # Acceptance scenario from the tech notes: a rare release miss shows up as ledger imbalance.
    run_dir = _simulate(simulator, tmp_path, "leak", "40", "200", "5", "500", label="rare")
    findings, _ = analyze_run(load_run(run_dir), SETTINGS)
    live = _trend(findings, "app.resource.frame.in_flight_count")["post_warmup"]
    assert live["direction"] == "rising"
    assert live["end"] == 16  # 8000 frames / 500
    healthy, _ = analyze_run(load_run(_simulate(simulator, tmp_path, "ok")), SETTINGS)
    assert _trend(healthy, "app.resource.frame.in_flight_count")["post_warmup"]["end"] == 0


def test_queue_growth_is_normalized_per_recognition_not_per_frame(
    simulator: Path, tmp_path: Path
) -> None:
    settings = AnalysisSettings(
        warmup_seconds=0,
        minimum_samples=10,
        metrics=(),
        normalization=("elapsed_seconds", "app.recognitions_total_count"),
    )
    findings, _ = analyze_run(load_run(_simulate(simulator, tmp_path, "queue")), settings)
    normalized = _trend(findings, "app.queue.depth_count")["normalized"]
    assert normalized, "expected growth per 1000 recognitions"
    # One queued result per recognition, so ~1000 items per 1000 recognitions.
    assert normalized[0]["value"] == pytest.approx(1000, rel=0.1)
    assert normalized[0]["per"] == "app.recognitions_total_count"
