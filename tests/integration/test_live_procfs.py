"""The host collector against a real Linux /proc (the test process itself).

Everything else in the suite reads synthetic procfs text. This is the one test that sees the
kernel's actual formats, so it runs only on Linux. It asserts what must hold on any modern kernel
and tolerates what legitimately varies (PSI, cgroup layout, restricted containers).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from axis_memlab.cli import main

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="needs a real Linux /proc"
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/default.toml"


def _collect(tmp_path: Path) -> list[dict[str, Any]]:
    code = main(
        [
            "collect",
            "--procfs-root",
            "/",
            "--pid",
            str(os.getpid()),
            "--config",
            str(CONFIG),
            "--out",
            str(tmp_path / "runs"),
            "--device-id",
            "ci-runner-1",
            "--scenario",
            "live-proc",
            "--privacy-classification",
            "synthetic",
            "--max-samples",
            "2",
            "--no-wait",
        ]  # fmt: skip
    )
    assert code == 0
    run = next(p for p in (tmp_path / "runs").iterdir() if p.is_dir())
    return [json.loads(x) for x in (run / "records.jsonl").read_text().splitlines()]


def test_live_samples_parse_and_validate(tmp_path: Path) -> None:
    records = _collect(tmp_path)
    schema = json.loads((ROOT / "schemas/record-v1.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for record in records:
        assert not list(validator.iter_errors(record)), record["record_type"]

    samples = [r for r in records if r["record_type"] == "sample"]
    assert len(samples) == 2
    metrics = samples[0]["metrics"]

    # Real kernel text must parse: a parse_error here means a format this repository misreads.
    bad = {
        n: m
        for s in samples
        for n, m in s["metrics"].items()
        if m.get("reason_code") == "parse_error"
    }
    assert not bad, f"unparseable on this kernel: {sorted(bad)}"

    assert metrics["system.mem.total_bytes"]["value"] > 16 * 1024 * 1024
    assert metrics["system.mem.free_bytes"]["value"] >= 0
    assert metrics["process.rss_bytes"]["value"] > 1024 * 1024  # a Python interpreter
    assert metrics["process.threads_count"]["value"] >= 1
    assert metrics["process.cpu_user_ticks"]["unit"] == "ticks"
    assert samples[0]["identity"]["pid"] == os.getpid()
    assert samples[0]["identity"]["process_start_ticks"] > 0

    # The first sample takes the sparse reads: descriptors of this process are real.
    assert metrics["process.fd_count"]["value"] >= 3
    assert (
        metrics["process.fd_file_count"]["value"] + metrics["process.fd_other_count"]["value"] >= 1
    )
    assert sum(metrics[f"process.fd_{c}_count"]["value"] for c in
               ("socket", "pipe", "dmabuf", "anon_inode_other", "file", "other")) == metrics["process.fd_count"]["value"]  # fmt: skip

    states = {r["annotations"]["capability"]: r["annotations"]["state"] for r in records
              if r["record_type"] == "capability"}  # fmt: skip
    assert states["meminfo"] == "available" and states["process_status"] == "available"
    assert states["process_stat"] == "available"


def test_resident_memory_tracks_a_real_allocation(tmp_path: Path) -> None:
    ballast = bytearray(40 * 1024 * 1024)  # touched pages: resident and anonymous
    for i in range(0, len(ballast), 4096):
        ballast[i] = 1
    records = _collect(tmp_path)
    sample = next(r for r in records if r["record_type"] == "sample")
    anon = sample["metrics"]["process.rss_anon_bytes"]
    if anon.get("available") is False:
        pytest.skip(f"RssAnon unavailable on this kernel: {anon['reason']}")
    assert anon["value"] >= 35 * 1024 * 1024
    del ballast
