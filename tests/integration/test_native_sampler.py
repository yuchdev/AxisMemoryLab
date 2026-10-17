"""End to end: C++ sampler + operator new hook -> alloc-samples-v1 -> host estimates (-> symbols).

Builds COUNTERS + SAMPLER with CMake. Skipped when CMake or a C++ toolchain is missing. Name
resolution needs an ELF binary, so that part runs on Linux only; elsewhere the test checks that
unresolved frames are reported honestly instead of being guessed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from axis_memlab.cli import main
from axis_memlab.symbolization.stackmap import load_samples

pytestmark = pytest.mark.native

ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("cmake") is None:
        pytest.skip("cmake is not installed")
    build = tmp_path_factory.mktemp("native-sampler")
    configure = _run(
        ["cmake", "-S", str(ROOT), "-B", str(build)]
        + ["-DAXMEM_COUNTERS=ON", "-DAXMEM_SAMPLER=ON", "-DCMAKE_BUILD_TYPE=Release"]
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
            "axis_memlab_sampler_demo",
        ]
    )
    assert built.returncode == 0, built.stdout + built.stderr
    found = [
        p
        for p in build.rglob("axis_memlab_sampler_demo*")
        if p.is_file() and p.suffix in ("", ".exe")
    ]
    assert found, "demo binary not found"
    return found[0]


@pytest.fixture(scope="module")
def run_output(demo: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("sampler-out") / "allocs.jsonl"
    result = _run([str(demo), str(out), "4096", "12345"])
    assert result.returncode == 0, result.stderr
    return out, json.loads(result.stdout)


def test_every_line_conforms_to_the_schema(run_output: tuple[Path, dict[str, Any]]) -> None:
    path, truth = run_output
    schema = json.loads((ROOT / "schemas/alloc-samples-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    kinds = set()
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        record = json.loads(line)
        errors = list(validator.iter_errors(record))
        assert not errors, f"line {number} ({record.get('type')}): {errors[0].message}"
        kinds.add(record["type"])
    assert {"header", "alloc", "free", "summary"} <= kinds
    assert truth["dropped_ring_full"] == 0 and truth["dropped_table_full"] == 0


def test_estimates_match_the_known_allocations(run_output: tuple[Path, dict[str, Any]]) -> None:
    path, truth = run_output
    session = load_samples(path).sessions[0]
    assert session.summary_final and session.summary is not None
    assert session.summary["dropped_ring_full"] == 0 and session.summary["dropped_free_events"] == 0

    def estimate(size: int, kind: str, *, live: bool) -> float:
        return sum(
            a.weight_count * a.size
            for a in session.allocs
            if a.size == size and a.kind == kind and (not live or a.id not in session.freed)
        )

    leak_live = estimate(1024, "new[]", live=True)
    assert leak_live == pytest.approx(truth["leak_live_bytes"], rel=0.15)
    # The transient site allocated twice as much as the leak holds, but holds nothing.
    assert estimate(4096, "new[]", live=True) == 0
    assert estimate(4096, "new[]", live=False) == pytest.approx(
        truth["transient_cumulative_bytes"], rel=0.12
    )
    array_live = estimate(truth["array_block_bytes"], "new[]", live=True)
    assert array_live == pytest.approx(
        truth["array_live_count"] * truth["array_block_bytes"], rel=0.4
    )
    # Cumulative estimate versus the exact counter kept by the sampler.
    total = sum(a.weight_count * a.size for a in session.allocs)
    assert total == pytest.approx(session.summary["alloc_request_bytes"], rel=0.10)


def test_stacks_and_module_map_are_consistent(run_output: tuple[Path, dict[str, Any]]) -> None:
    path, _ = run_output
    session = load_samples(path).sessions[0]
    header = session.header
    assert header["pointer_bits"] == (64 if sys.maxsize > 2**32 else 32)
    assert header["unwinder"] in {"frame_pointer", "capture_stack_back_trace", "caller_only"}
    assert any(m.build_id for m in session.all_modules())
    deep = 0
    for sample in session.allocs:
        assert sample.stack, "every sample has a stack on supported targets"
        for pc in sample.stack:
            assert session.locate(pc) is not None, f"pc 0x{pc:x} is outside every loaded module"
        deep += len(sample.stack) >= 2
    assert deep > len(session.allocs) * 0.9


def test_symbolize_reports_unresolved_frames_honestly(
    run_output: tuple[Path, dict[str, Any]], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path, _ = run_output
    empty = tmp_path / "no-symbols"
    empty.mkdir()
    assert (
        main(["symbolize", "--samples", str(path), "--symbols", str(empty), "--tool", "builtin"])
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    summary = next(f for f in report["findings"] if f["type"] == "allocation_summary")
    assert summary["unresolved_frames"] > 0
    assert summary["calibration"]["ratio"] == pytest.approx(1.0, rel=0.10)
    sites = [f for f in report["findings"] if f["type"] == "allocation_site"]
    assert sites[0]["estimated_live_bytes"] > sites[-1]["estimated_live_bytes"]
    assert all(f["function"] is None for s in sites for f in s["frames"])  # nothing invented


@pytest.mark.skipif(
    sys.platform != "linux", reason="symbol resolution of the demo needs an ELF binary"
)
def test_sites_resolve_to_the_demo_functions(
    demo: Path, run_output: tuple[Path, dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    path, _ = run_output
    args = ["symbolize", "--samples", str(path), "--symbols", str(demo.parent), "--tool", "builtin"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    sites = [f for f in report["findings"] if f["type"] == "allocation_site"]
    top_names = {s["frames"][0]["function"] for s in sites if s["frames"]}
    assert {
        "axmem_demo_leak_site",
        "axmem_demo_transient_site",
        "axmem_demo_array_site",
    } <= top_names
    live = {s["frames"][0]["function"]: s for s in sites if s["frames"]}
    assert sites[0]["frames"][0]["function"] == "axmem_demo_leak_site"  # ranked by live bytes
    assert live["axmem_demo_transient_site"]["estimated_live_bytes"] == 0
    assert live["axmem_demo_transient_site"]["estimated_cumulative_bytes"] > 0
    assert sites[0]["frames"][0]["status"] == "resolved"
