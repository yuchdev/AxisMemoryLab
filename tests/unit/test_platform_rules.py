"""Platform correlation hypotheses (shared buffers, DMA handles, kernel slab, cgroup charge)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synthetic_traces import linear, write_run

from axis_memlab.analysis.engine import analyze_run
from axis_memlab.analysis.load import load_run
from axis_memlab.analysis.settings import AnalysisSettings

SETTINGS = AnalysisSettings(
    60, 10, ("process.rss_anon_bytes", "process.pss_bytes"), ("elapsed_seconds",)
)
SHMEM, SLAB = "system.mem.shmem_bytes", "system.mem.slab_unreclaim_bytes"
RSS_SHMEM, DMABUF = "process.rss_shmem_bytes", "process.fd_dmabuf_count"
CGROUP, ANON, PSS = (
    "process.cgroup_memory_current_bytes",
    "process.rss_anon_bytes",
    "process.pss_bytes",
)


def _ids(tmp_path: Path, metrics: dict[str, Any]) -> set[str]:
    findings, _ = analyze_run(load_run(write_run(tmp_path / "r", metrics)), SETTINGS)
    return {f["id"] for f in findings if f["type"] == "hypothesis" and f["status"] == "observed"}


def test_shared_buffers_need_system_and_process_evidence(tmp_path: Path) -> None:
    flat = linear(1e6, 0, noise=1)
    assert "H-SHARED-BUFFERS" in _ids(
        tmp_path, {SHMEM: linear(1e6, 3000), RSS_SHMEM: linear(1e5, 600), ANON: flat}
    )
    # System shared memory alone, with nothing process-side, is not enough to say anything.
    assert "H-SHARED-BUFFERS" not in _ids(tmp_path / "b", {SHMEM: linear(1e6, 3000), ANON: flat})


def test_dmabuf_handle_growth_without_anonymous_growth(tmp_path: Path) -> None:
    assert "H-DMABUF-HANDLES" in _ids(
        tmp_path / "a", {DMABUF: linear(2, 0.02), ANON: linear(1e6, 0, noise=1)}
    )
    ids = _ids(tmp_path / "b", {DMABUF: linear(2, 0.02), ANON: linear(1e6, 2000)})
    assert "H-DMABUF-HANDLES" not in ids  # anonymous memory grows too: a different story


def test_kernel_slab_is_reported_only_when_the_process_is_known_flat(tmp_path: Path) -> None:
    flat = {ANON: linear(1e6, 0, noise=1), PSS: linear(1e6, 0, noise=1)}
    assert "H-KERNEL-SLAB" in _ids(tmp_path / "a", {SLAB: linear(2e6, 500), **flat})
    assert "H-KERNEL-SLAB" not in _ids(
        tmp_path / "b", {SLAB: linear(2e6, 500), ANON: linear(1e6, 3000)}
    )
    assert "H-KERNEL-SLAB" not in _ids(tmp_path / "c", {SLAB: linear(2e6, 500)})  # process unknown


def test_cgroup_charge_versus_anonymous_memory(tmp_path: Path) -> None:
    assert "H-CGROUP-CHARGE" in _ids(
        tmp_path / "a", {CGROUP: linear(5e6, 2000), ANON: linear(1e6, 0, noise=1)}
    )
    assert "H-CGROUP-CHARGE" not in _ids(tmp_path / "b", {CGROUP: linear(5e6, 2000)})
    assert "H-CGROUP-CHARGE" not in _ids(
        tmp_path / "c", {CGROUP: linear(5e6, 2000), ANON: linear(1e6, 3000)}
    )


def test_platform_findings_are_hypotheses_not_diagnoses(tmp_path: Path) -> None:
    findings, _ = analyze_run(
        load_run(
            write_run(tmp_path / "r", {SLAB: linear(2e6, 500), ANON: linear(1e6, 0, noise=1)})
        ),
        SETTINGS,
    )
    slab = next(f for f in findings if f.get("id") == "H-KERNEL-SLAB")
    assert "does not establish a cause" in slab["caveat"]
    assert "unconfirmed" in slab["hypothesis"] and slab["alternatives"] and slab["next_comparison"]
    assert "advanced check" in slab["next_comparison"]  # lab-only diagnostics go through the gate
    text = str(slab).lower()
    assert "kernel leak" not in text and "is a leak" not in text
