"""The virtual camera pipeline with injected defects, seen through the probe, the ledger, the
sampler, and the host analysis. Builds LEDGER + SAMPLER with CMake; skipped without a toolchain."""

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
from axis_memlab.symbolization.stackmap import load_samples

pytestmark = pytest.mark.native

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "00000000-0000-4000-8000-0000000000f1"
SETTINGS = AnalysisSettings(0, 10, (), ("elapsed_seconds",))
COMMON = [
    "--seconds",
    "3",
    "--fps",
    "100",
    "--width",
    "320",
    "--height",
    "180",
    "--snapshot-ms",
    "150",
]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def camera(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("virtual-camera")
    configure = _run(
        [
            "cmake",
            "-S",
            str(ROOT),
            "-B",
            str(build),
            "-DAXMEM_LEDGER=ON",
            "-DAXMEM_SAMPLER=ON",
            "-DCMAKE_BUILD_TYPE=Release",
        ]  # fmt: skip
    )
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
            "axis_memlab_virtual_camera",
        ]
    )
    assert built.returncode == 0, built.stdout + built.stderr
    found = [
        p
        for p in build.rglob("axis_memlab_virtual_camera*")
        if p.is_file() and p.suffix in ("", ".exe")
    ]
    assert found, "virtual camera binary not found"
    return found[0]


def _simulate(
    camera: Path, tmp_path: Path, label: str, *extra: str
) -> tuple[Path, Path, dict[str, Any]]:
    run_dir = tmp_path / label
    run_dir.mkdir()
    samples = run_dir / "allocs.jsonl"
    result = _run(
        [
            str(camera),
            "--probe-out",
            str(run_dir / "records.jsonl"),
            "--sampler-out",
            str(samples),
            "--sampler-interval-bytes",
            "32768",
            *COMMON,
            *extra,
        ]  # fmt: skip
    )
    assert result.returncode == 0, result.stderr
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "created_at": "2026-01-01T00:00:00Z",
                "device_identity": "virtual-board-001",
                "scenario": f"virtual-camera-{label}",
                "privacy_classification": "synthetic",
                "status": "complete",
            }
        )  # fmt: skip
    )
    return run_dir, samples, json.loads(result.stdout)


def _direction(findings: list[dict[str, Any]], metric: str) -> str:
    trend = next(f for f in findings if f["type"] == "trend" and f["metric"] == metric)
    return str(trend["post_warmup"]["direction"])


def _analyze(run_dir: Path) -> list[dict[str, Any]]:
    findings, _ = analyze_run(load_run(run_dir), SETTINGS)
    return findings


def test_a_healthy_pipeline_is_flat(camera: Path, tmp_path: Path) -> None:
    run_dir, _, truth = _simulate(camera, tmp_path, "none", "--reconnect-seconds", "0.5")
    findings = _analyze(run_dir)
    assert truth["leaked_frames"] == 0 and truth["frames"] > 200
    assert _direction(findings, "app.resource.frame.in_flight_count") == "flat"
    assert _direction(findings, "app.resource.frame.in_flight_bytes") == "flat"
    assert _direction(findings, "app.queue.results_depth_count") == "flat"
    # Reconnects happen, and each tears the previous session down.
    assert _direction(findings, "app.resource.session.in_flight_count") == "flat"
    assert _direction(findings, "app.frames_total_count") == "rising"
    schema = json.loads((ROOT / "schemas/record-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for line in (run_dir / "records.jsonl").read_text().splitlines():
        assert not list(validator.iter_errors(json.loads(line)))


def test_missed_release_shows_in_the_ledger_and_the_sampler(camera: Path, tmp_path: Path) -> None:
    run_dir, samples, truth = _simulate(
        camera, tmp_path, "leak", "--defect", "release_miss", "--defect-every", "10"
    )
    findings = _analyze(run_dir)
    assert truth["leaked_frames"] >= 20
    assert _direction(findings, "app.resource.frame.in_flight_count") == "rising"
    assert _direction(findings, "app.resource.frame.in_flight_bytes") == "rising"
    assert (
        _direction(findings, "app.queue.results_depth_count") == "flat"
    )  # the cause is not the queue
    # The sampler attributes the retained bytes to the frame allocation size.
    session = load_samples(samples).sessions[0]
    assert session.summary_final and session.summary is not None
    assert session.summary["dropped_ring_full"] == 0
    live = sum(a.weight_count * a.size for a in session.allocs
               if a.size == truth["frame_bytes"] and a.id not in session.freed)  # fmt: skip
    assert live == pytest.approx(truth["leaked_frame_bytes"], rel=0.5)
    cumulative = sum(a.weight_count * a.size for a in session.allocs)
    assert cumulative > 5 * live  # churn dwarfs what is actually retained


def test_an_undrained_queue_is_not_a_frame_leak(camera: Path, tmp_path: Path) -> None:
    run_dir, _, truth = _simulate(
        camera, tmp_path, "queue", "--defect", "queue_growth", "--publisher-hz", "5"
    )
    findings = _analyze(run_dir)
    assert truth["queue_left"] > 30
    assert _direction(findings, "app.queue.results_depth_count") == "rising"
    assert _direction(findings, "app.resource.frame.in_flight_count") == "flat"


def test_a_bounded_queue_sheds_load(camera: Path, tmp_path: Path) -> None:
    run_dir, _, truth = _simulate(
        camera, tmp_path, "bounded", "--publisher-hz", "5", "--queue-max", "8"
    )
    findings = _analyze(run_dir)
    assert truth["queue_left"] <= 8
    assert _direction(findings, "app.queue.results_depth_count") in ("flat", "rising")
    dropped = next(
        f
        for f in findings
        if f["type"] == "trend" and f["metric"] == "app.queue.results_dropped_count"
    )
    assert dropped["post_warmup"]["end"] > 0


def test_a_reconnect_leak_accumulates_sessions(camera: Path, tmp_path: Path) -> None:
    run_dir, _, truth = _simulate(
        camera, tmp_path, "reconnect", "--defect", "reconnect_leak", "--reconnect-seconds", "0.2"
    )
    findings = _analyze(run_dir)
    assert truth["leaked_sessions"] >= 8
    assert _direction(findings, "app.resource.session.in_flight_count") == "rising"
    assert _direction(findings, "app.reconnects_total_count") == "rising"
    assert _direction(findings, "app.resource.frame.in_flight_count") == "flat"


def test_cache_growth_is_visible_as_entries(camera: Path, tmp_path: Path) -> None:
    run_dir, _, truth = _simulate(camera, tmp_path, "cache", "--defect", "cache_growth")
    findings = _analyze(run_dir)
    assert truth["frames"] > 200
    assert _direction(findings, "app.cache.entries_count") == "rising"
    assert _direction(findings, "app.resource.frame.in_flight_count") == "flat"


def test_bad_options_fail_fast(camera: Path) -> None:
    assert _run([str(camera), "--defect", "bogus"]).returncode == 2
    assert _run([str(camera), "--fps", "0"]).returncode == 2
    assert _run([str(camera), "--nonsense", "1"]).returncode == 2
    assert _run([str(camera), "--width"]).returncode == 2
