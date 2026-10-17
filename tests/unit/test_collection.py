"""Collector, run store, discovery, triggers, annotations, import: all offline."""

from __future__ import annotations

import copy
import gzip
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from axis_memlab.analysis.load import load_run
from axis_memlab.analysis.phase import segment_run
from axis_memlab.collection.annotate import annotate
from axis_memlab.collection.discovery import discover, select_process
from axis_memlab.collection.identity import new_run_id, pseudonym, validate_device_id
from axis_memlab.collection.importer import import_records, peek_run_id, validate_record
from axis_memlab.collection.run_store import (
    RunStore,
    build_manifest,
    compress_run,
    find_old_runs,
    purge_runs,
)
from axis_memlab.collection.scheduler import Collector
from axis_memlab.collection.triggers import TriggerEvaluator
from axis_memlab.config import load_config
from axis_memlab.errors import CollectionError, RunDataError, TransportError
from axis_memlab.transport import ReadError
from axis_memlab.transport.offline import LocalProcfsReader

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/procfs/basic"
MIB = 1024 * 1024


# ---- test doubles ----------------------------------------------------------------------------
class FakeClock:
    def __init__(self) -> None:
        self.mono = 5_000_000_000
        self.utc = 1_767_225_600_000_000_000
        self.sleeps: list[float] = []

    def utc_ns(self) -> int:
        return self.utc

    def mono_ns(self) -> int:
        return self.mono

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.mono += int(seconds * 1e9)
        self.utc += int(seconds * 1e9)


def _num(fn: Callable[[int], int] | int) -> Callable[[int], int]:
    return fn if callable(fn) else (lambda _t: fn)


class Scripted:
    """A reader whose values are functions of the cycle number; counts what was requested."""

    def __init__(
        self,
        *,
        avail_kb: Callable[[int], int] | int = 100_000,
        pss_kb: Callable[[int], int] | int = 6_000,
        start_ticks: Callable[[int], int] | int = 111,
        status_missing: Callable[[int], bool] = lambda _t: False,
        down: Callable[[int], bool] = lambda _t: False,
        psi: bool = True,
        smaps_denied: bool = False,
        comm: dict[int, str] | None = None,
    ) -> None:
        self.avail_kb, self.pss_kb, self.start_ticks = (
            _num(avail_kb),
            _num(pss_kb),
            _num(start_ticks),
        )
        self.status_missing, self.down = status_missing, down
        self.psi, self.smaps_denied = psi, smaps_denied
        self.comm = comm if comm is not None else {4242: "app"}
        self.tick = -1
        self.requested: list[str] = []
        self.fd_calls = 0

    def describe(self) -> str:
        return "scripted"

    def _one(self, path: str) -> str | ReadError:
        t = self.tick
        self.requested.append(path)
        if path == "/proc/meminfo":
            return f"MemTotal: 262144 kB\nMemFree: 1000 kB\nMemAvailable: {self.avail_kb(t)} kB\n"
        if path == "/proc/vmstat":
            return "pgfault 100\npgmajfault 1\n"
        if path == "/proc/pressure/memory":
            if not self.psi:
                return ReadError("missing", "/proc/pressure/memory does not exist")
            return "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        if path == "/proc/sys/kernel/osrelease":
            return "5.15.0\n"
        if path == "/proc/sys/kernel/random/boot_id":
            return "11111111-2222-4333-8444-555555555555\n"
        if path.endswith("/status"):
            if self.status_missing(t):
                return ReadError("missing", "process vanished")
            return "VmRSS:\t 1000 kB\nRssAnon:\t 800 kB\nThreads:\t4\n"
        if path.endswith("/stat"):
            return f"4242 (app) S 1 4242 4242 0 -1 0 1 0 2 0 3 4 0 0 20 0 4 0 {self.start_ticks(t)} 1 2\n"
        if path.endswith("/smaps_rollup"):
            if self.smaps_denied:
                return ReadError("permission_denied", "smaps_rollup is not readable")
            return f"Rss: 9000 kB\nPss: {self.pss_kb(t)} kB\nPrivate_Clean: 1 kB\nPrivate_Dirty: 2 kB\n"
        if path.endswith("/cgroup"):
            return "0::/svc\n"
        if path.endswith("memory.current"):
            return "1000\n"
        if path.endswith("memory.max"):
            return "max\n"
        if path.endswith("memory.events"):
            return "oom_kill 0\n"
        return ReadError("unsupported", f"unexpected path {path}")

    def read_many(self, paths: Iterable[str]) -> dict[str, str | ReadError]:
        wanted = list(paths)
        if "/proc/meminfo" in wanted:
            self.tick += 1
        if self.down(self.tick):
            raise TransportError("connection refused")
        return {p: self._one(p) for p in wanted}

    def read_text(self, path: str) -> str:
        got = self._one(path)
        if isinstance(got, ReadError):
            raise got
        return got

    def read_fd_targets(self, pid: int) -> dict[str, str]:
        self.fd_calls += 1
        return {"3": "socket:[1]", "4": "anon_inode:dmabuf"}

    def scan_comm(self) -> dict[int, str]:
        return self.comm


def _config(**collection: Any) -> dict[str, Any]:
    config = copy.deepcopy(load_config(ROOT / "configs/default.toml"))
    config["collection"].update(collection)
    return config


def _run(
    tmp_path: Path,
    reader: Any,
    *,
    config: dict[str, Any] | None = None,
    clock: FakeClock | None = None,
    **kwargs: Any,
) -> tuple[Any, RunStore, FakeClock, list[dict[str, Any]]]:
    clk = clock or FakeClock()
    manifest = build_manifest(
        run_id=new_run_id(), device_id="synthetic-dev-1", scenario="unit", extra=None
    )
    store = RunStore.create(tmp_path, manifest, fsync=False)
    kwargs.setdefault("pid", 4242)
    with store:
        result = Collector(
            reader, store, config or _config(), device_id="synthetic-dev-1", clock=clk, **kwargs
        ).run()
        store.finalize(result.status)
    lines = (store.directory / "records.jsonl").read_text().splitlines()
    return result, store, clk, [json.loads(line) for line in lines]


def _samples(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["record_type"] == "sample"]


def _events(records: list[dict[str, Any]], name: str | None = None) -> list[dict[str, Any]]:
    out = [r for r in records if r["record_type"] == "event"]
    return [r for r in out if name is None or r["annotations"]["event"] == name]


# ---- identity --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label", ["10.0.0.7", "ACCC8E123456", "aa-bb-cc-dd-ee-ff", "a b", "", "x" * 65]
)
def test_identifying_device_ids_are_refused(label: str) -> None:
    with pytest.raises(CollectionError):
        validate_device_id(label)


def test_pseudonyms_are_stable_salted_and_not_reversible_by_inspection() -> None:
    first = pseudonym("serial-123", "salt-a")
    assert first == pseudonym("serial-123", "salt-a")
    assert first != pseudonym("serial-123", "salt-b")
    assert "serial" not in first and validate_device_id(first) == first
    with pytest.raises(CollectionError):
        pseudonym("x", "")


# ---- collector -------------------------------------------------------------------------------
def test_basic_run_writes_bounded_well_formed_records(tmp_path: Path) -> None:
    result, store, clock, records = _run(tmp_path, Scripted(), max_samples=5)
    assert (result.status, result.samples) == ("complete", 5)
    kinds = [r["record_type"] for r in records]
    assert kinds.count("sample") == 5 and kinds[-1] == "run_stop" and "run_start" in kinds
    assert kinds.count("capability") >= 8
    assert json.loads((store.directory / "manifest.json").read_text())["status"] == "complete"
    samples = _samples(records)
    stamps = [s["ts_mono_ns"] for s in samples]
    assert [b - a for a, b in zip(stamps, stamps[1:], strict=False)] == [15_000_000_000] * 4
    assert clock.sleeps == [15.0] * 4  # no sleep after the final sample
    assert all(s["identity"]["pid"] == 4242 for s in samples)
    assert samples[0]["identity"]["process_start_ticks"] == 111
    assert samples[0]["identity"]["boot_id"].startswith("11111111")


def test_sparse_reads_happen_at_their_own_cadence_only(tmp_path: Path) -> None:
    reader = Scripted()
    _, _, _, records = _run(tmp_path, reader, max_samples=10)  # 0..135 s, sparse every 120 s
    with_pss = [i for i, s in enumerate(_samples(records)) if "process.pss_bytes" in s["metrics"]]
    assert with_pss == [0, 8]
    assert reader.fd_calls == 3  # one during discovery plus the two sparse cycles
    sample = _samples(records)[0]["metrics"]
    assert sample["process.fd_dmabuf_count"]["value"] == 1
    assert sample["process.cgroup_memory_current_bytes"]["value"] == 1000
    assert sample["process.uss_approx_bytes"]["value"] == 3 * 1024


def test_unreadable_sources_become_unavailable_with_codes_and_one_error_record(
    tmp_path: Path,
) -> None:
    reader = Scripted(psi=False, smaps_denied=True)
    _, _, _, records = _run(tmp_path, reader, max_samples=6)
    for sample in _samples(records):
        psi_metric = sample["metrics"]["system.psi.memory_some_avg10_percent"]
        assert psi_metric["available"] is False and psi_metric["reason_code"] == "missing"
    first = _samples(records)[0]["metrics"]["process.pss_bytes"]
    assert first["available"] is False and first["reason_code"] == "permission_denied"
    errors = [r for r in records if r["record_type"] == "error"]
    sources = sorted(e["annotations"]["source"] for e in errors)
    assert sources == ["psi", "smaps_rollup"]  # once each, not once per cycle
    assert all("0" != str(m.get("value")) for m in first.values() if isinstance(m, dict))
    assert not any(p.endswith("/smaps") for p in reader.requested)  # never falls back to smaps


def test_collector_reports_its_own_cost_and_errors(tmp_path: Path) -> None:
    _, _, _, records = _run(tmp_path, Scripted(psi=False), max_samples=4)
    reads = [s["metrics"]["collector.reads_total_count"]["value"] for s in _samples(records)]
    errors = [s["metrics"]["collector.read_errors_count"]["value"] for s in _samples(records)]
    assert reads == sorted(reads) and reads[-1] > reads[0]
    assert errors[-1] >= 4  # one failed psi read per cycle
    last = _samples(records)[-1]["metrics"]
    assert last["collector.bytes_read_bytes"]["unit"] == "bytes"
    assert last["collector.cycle_duration_ns"]["unit"] == "nanoseconds"


def test_recovery_is_recorded_once(tmp_path: Path) -> None:
    class Flaky(Scripted):
        def _one(self, path: str) -> str | ReadError:
            if path == "/proc/vmstat" and 2 <= self.tick <= 3:
                return ReadError("timeout", "slow")
            return super()._one(path)

    _, _, _, records = _run(tmp_path, Flaky(), max_samples=7)
    assert len([r for r in records if r["record_type"] == "error"]) == 1
    assert len(_events(records, "source_recovered")) == 1


def test_process_restart_is_an_event_and_splits_analysis_segments(tmp_path: Path) -> None:
    reader = Scripted(start_ticks=lambda t: 111 if t < 4 else 222)
    _, store, _, records = _run(tmp_path, reader, max_samples=8)
    assert len(_events(records, "process_restart")) == 1
    run = load_run(store.directory)
    assert [s.start_reason for s in segment_run(run)] == ["run_start", "process_restart"]


def test_missing_process_is_explicit_and_found_again_by_name(tmp_path: Path) -> None:
    reader = Scripted(status_missing=lambda t: 3 <= t <= 4)
    _, _, _, records = _run(tmp_path, reader, max_samples=8, pid=None, app="app")
    assert len(_events(records, "process_missing")) == 1
    gone = [
        s for s in _samples(records) if s["metrics"]["process.rss_bytes"].get("available") is False
    ]
    assert gone and all(s["metrics"]["process.rss_bytes"]["reason_code"] == "missing" for s in gone)
    assert _samples(records)[-1]["metrics"]["process.rss_bytes"]["value"] == 1000 * 1024


def test_memory_pressure_aborts_before_heavier_reads(tmp_path: Path) -> None:
    reader = Scripted(avail_kb=lambda t: 100_000 if t < 3 else 10_000)  # < 16 MiB abort threshold
    result, store, _, records = _run(tmp_path, reader, max_samples=50)
    assert result.status == "incomplete"
    assert "abort threshold" in result.reason
    assert len(_events(records, "abort_memory_pressure")) == 1
    assert json.loads((store.directory / "manifest.json").read_text())["status"] == "incomplete"
    assert len(_samples(records)) < 50
    assert "process.pss_bytes" not in _samples(records)[-1]["metrics"]  # no page-table walk


def test_low_but_not_critical_memory_skips_sparse_reads_and_says_so(tmp_path: Path) -> None:
    reader = Scripted(
        avail_kb=30 * 1024
    )  # 30 MiB: below the 32 MiB trigger, above the 16 MiB abort
    result, _, _, records = _run(tmp_path, reader, max_samples=4)
    assert result.status == "complete"
    assert all("process.pss_bytes" not in s["metrics"] for s in _samples(records))
    assert len(_events(records, "sparse_skipped")) == 1
    trigger = _events(records, "trigger_fired")[0]["annotations"]
    assert (
        trigger["trigger"] == "mem_available_low"
        and trigger["snapshot"] == "skipped_memory_pressure"
    )


def test_pss_growth_trigger_takes_a_sparse_snapshot_with_cooldown(tmp_path: Path) -> None:
    config = _config(smaps_rollup_interval_seconds=15, deep_snapshot_cooldown_seconds=30)
    reader = Scripted(pss_kb=lambda t: 6_000 + 3_000 * t)  # +3 MB per cycle vs 10 MiB threshold
    _, _, _, records = _run(tmp_path, reader, config=config, max_samples=12)
    fired = _events(records, "trigger_fired")
    assert fired and all(e["annotations"]["trigger"] == "pss_growth" for e in fired)
    assert all(e["annotations"]["snapshot"] == "sparse" for e in fired)
    assert len(fired) < 12  # the cooldown limits how often it can fire


def test_transport_failures_back_off_then_recover(tmp_path: Path) -> None:
    reader = Scripted(down=lambda t: 1 <= t <= 3)
    result, _, clock, records = _run(tmp_path, reader, max_samples=3)
    assert result.status == "complete"
    assert clock.sleeps[:3] == [2.0, 4.0, 8.0]  # exponential, not a retry storm
    transport = [r for r in records if r["record_type"] == "error"]
    assert len(transport) == 3 and all(e["annotations"]["source"] == "transport" for e in transport)


def test_permanent_transport_failure_ends_the_run_as_failed(tmp_path: Path) -> None:
    reader = Scripted(down=lambda t: t >= 1)
    result, _, clock, records = _run(tmp_path, reader, max_samples=100)
    assert result.status == "failed" and "transport" in result.reason
    assert clock.sleeps == [2.0, 4.0, 8.0, 16.0]
    assert records[-1]["record_type"] == "run_stop"


def test_unreachable_at_start_fails_without_samples(tmp_path: Path) -> None:
    result, _, _, records = _run(tmp_path, Scripted(down=lambda t: True), max_samples=3)
    assert result.status == "failed" and result.samples == 0
    assert [r["record_type"] for r in records] == ["run_stop"]


def test_duration_bound(tmp_path: Path) -> None:
    result, _, _, records = _run(tmp_path, Scripted(), duration_seconds=60)
    assert result.samples == 5 and len(_samples(records)) == 5  # t = 0, 15, 30, 45, 60


def test_snapshot_forces_the_sparse_reads(tmp_path: Path) -> None:
    clock = FakeClock()
    manifest = build_manifest(run_id=new_run_id(), device_id="d1", scenario="s")
    with RunStore.create(tmp_path, manifest, fsync=False) as store:
        reader = Scripted()
        result = Collector(
            reader, store, _config(), device_id="d1", clock=clock, pid=4242
        ).snapshot()
        directory = store.directory
    assert result.status == "complete"
    lines = [json.loads(x) for x in (directory / "records.jsonl").read_text().splitlines()]
    assert _events(lines, "snapshot")[0]["annotations"]["level"] == "sparse"
    assert "process.pss_bytes" in _samples(lines)[0]["metrics"]


def test_run_output_is_analysable(tmp_path: Path) -> None:
    from axis_memlab.analysis.engine import analyze_run
    from axis_memlab.analysis.settings import AnalysisSettings

    reader = Scripted(avail_kb=lambda t: 100_000 - 400 * t)
    _, store, _, _ = _run(
        tmp_path, reader, config=_config(smaps_rollup_interval_seconds=15), max_samples=30
    )
    settings = AnalysisSettings(60, 10, ("system.mem.available_bytes",), ("elapsed_seconds",))
    findings, limitations = analyze_run(load_run(store.directory), settings)
    trend = next(
        f for f in findings if f["type"] == "trend" and f["metric"] == "system.mem.available_bytes"
    )
    assert trend["post_warmup"]["direction"] == "falling"


# ---- discovery -------------------------------------------------------------------------------
def test_discovery_states_and_facts_on_fixture() -> None:
    found = discover(LocalProcfsReader(FIXTURE), app="synthetic_app")
    states = {c.name: c.state for c in found.capabilities}
    assert set(states.values()) == {"available"}
    assert found.pid == 4242 and found.facts["mem_total_bytes"] == 262144 * 1024
    assert found.facts["cgroup_version"] == 2


def test_discovery_reports_missing_and_denied_instead_of_failing(tmp_path: Path) -> None:
    class Denied(LocalProcfsReader):
        def read_many(self, paths: Iterable[str]) -> dict[str, str | ReadError]:
            got = super().read_many(paths)
            for path in got:
                if path.endswith("smaps_rollup"):
                    got[path] = ReadError("permission_denied", "no")
                if path.endswith("pressure/memory"):
                    got[path] = ReadError("missing", "no")
            return got

    states = {c.name: c.state for c in discover(Denied(FIXTURE), pid=4242).capabilities}
    assert states["process_smaps_rollup"] == "denied" and states["pressure_memory"] == "missing"
    assert states["meminfo"] == "available"


def test_process_selection_rules() -> None:
    reader = LocalProcfsReader(FIXTURE)
    assert select_process(reader, None, "synthetic_app")[0] == 4242
    with pytest.raises(CollectionError, match="no visible process"):
        select_process(reader, None, "nothing")
    with pytest.raises(CollectionError, match="positive"):
        select_process(reader, 0, None)

    class Two(LocalProcfsReader):
        def scan_comm(self) -> dict[int, str]:
            return {1: "same", 2: "same"}

    with pytest.raises(CollectionError, match="--pid"):
        select_process(Two(FIXTURE), None, "same")


# ---- triggers --------------------------------------------------------------------------------
def _trig(**kw: Any) -> TriggerEvaluator:
    base = {
        "pss_growth_bytes": 10 * MIB,
        "mem_available_below_bytes": 32 * MIB,
        "abort_mem_available_below_bytes": 16 * MIB,
        "cooldown_seconds": 100,
    }
    return TriggerEvaluator(**{**base, **kw})


def test_trigger_growth_baseline_and_restart_reset() -> None:
    t = _trig()
    assert not t.evaluate(0, 50 * MIB, 200 * MIB).triggers
    assert not t.evaluate(10, 55 * MIB, 200 * MIB).triggers
    fired = t.evaluate(20, 61 * MIB, 200 * MIB).triggers
    assert [x.name for x in fired] == ["pss_growth"] and fired[0].snapshot_allowed
    assert not t.evaluate(30, 90 * MIB, 200 * MIB).triggers  # cooling down
    assert t.evaluate(150, 90 * MIB, 200 * MIB).triggers  # growth is measured from the last fire
    t.reset_process()
    assert not t.evaluate(400, 5 * MIB, 200 * MIB).triggers  # new process, new baseline


def test_trigger_low_memory_and_abort_precedence() -> None:
    t = _trig()
    low = t.evaluate(0, None, 20 * MIB)
    assert [x.name for x in low.triggers] == ["mem_available_low"] and not low.abort
    assert not low.triggers[0].snapshot_allowed
    dead = t.evaluate(1000, None, 10 * MIB)
    assert dead.abort and not dead.triggers
    assert not _trig().evaluate(0, None, None).abort  # unknown memory never aborts


def test_growth_during_memory_pressure_does_not_allow_a_snapshot() -> None:
    t = _trig()
    t.evaluate(0, 10 * MIB, 200 * MIB)  # baseline taken while memory is healthy
    decision = t.evaluate(1, 40 * MIB, 20 * MIB)  # growth now happens under pressure
    growth = next(x for x in decision.triggers if x.name == "pss_growth")
    assert not growth.snapshot_allowed


# ---- run store -------------------------------------------------------------------------------
def _store(tmp_path: Path, **kw: Any) -> RunStore:
    return RunStore.create(
        tmp_path,
        build_manifest(run_id=new_run_id(), device_id="d1", scenario="s"),
        fsync=False,
        **kw,
    )


def test_store_is_append_only_and_refuses_to_reuse_a_run(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append({"a": 1})
    store.append({"b": 2})
    store.close()
    with pytest.raises(CollectionError, match="already exists"):
        RunStore.create(tmp_path, store.manifest)
    again = RunStore.open_existing(store.directory, fsync=False)
    again.append({"c": 3})
    again.close()
    lines = (store.directory / "records.jsonl").read_text().splitlines()
    assert [json.loads(x) for x in lines] == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_store_never_glues_onto_a_partial_last_line(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.close()
    path = store.directory / "records.jsonl"
    path.write_bytes(b'{"ok":1}\n{"torn":')  # a crash mid-write
    again = RunStore.open_existing(store.directory, fsync=False)
    again.append({"after": 1})
    again.close()
    lines = path.read_text().splitlines()
    assert lines == ['{"ok":1}', '{"torn":', '{"after":1}']


def test_store_rejects_bad_runs(tmp_path: Path) -> None:
    with pytest.raises(RunDataError):
        RunStore.open_existing(tmp_path)
    (tmp_path / "manifest.json").write_text("{not json")
    with pytest.raises(RunDataError):
        RunStore.open_existing(tmp_path)
    store = _store(tmp_path / "ok")
    with pytest.raises(ValueError):
        store.finalize("done")
    store.close()
    with pytest.raises(CollectionError, match="closed"):
        store.append({"x": 1})


def test_manifest_updates_only_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = dict(store.manifest)
    store.finalize("incomplete")
    after = json.loads((store.directory / "manifest.json").read_text())
    assert {k: v for k, v in after.items() if k != "status"} == {
        k: v for k, v in before.items() if k != "status"
    }
    assert after["status"] == "incomplete"
    store.close()


def test_compressed_runs_are_still_readable_by_analysis(tmp_path: Path) -> None:
    _, store, _, _ = _run(tmp_path, Scripted(), max_samples=3)
    plain = len(load_run(store.directory).samples)
    target = compress_run(store.directory)
    assert target.suffix == ".gz" and not (store.directory / "records.jsonl").exists()
    assert len(gzip.decompress(target.read_bytes()).splitlines()) > 3
    assert len(load_run(store.directory).samples) == plain
    with pytest.raises(CollectionError):
        RunStore.open_existing(store.directory)  # compressed runs are read-only


def test_retention_finds_only_old_runs_and_deletes_only_on_request(tmp_path: Path) -> None:
    old = _store(tmp_path)
    old.manifest["created_at"] = "2020-01-01T00:00:00Z"
    (old.directory / "manifest.json").write_text(json.dumps(old.manifest))
    old.close()
    fresh = _store(tmp_path)
    fresh.close()
    (tmp_path / "unrelated").mkdir()
    (tmp_path / "unrelated" / "keep.txt").write_text("x")
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{")
    found = find_old_runs(tmp_path, 30, now=datetime.now(UTC))
    assert found == [old.directory]
    assert old.directory.exists()  # finding is not deleting
    assert purge_runs(found) == 1
    assert not old.directory.exists() and fresh.directory.exists()
    assert (tmp_path / "unrelated" / "keep.txt").exists() and broken.exists()
    assert find_old_runs(tmp_path, 30, now=datetime.now(UTC) + timedelta(days=60)) == [
        fresh.directory,
        # broken manifests are never selected
    ]


# ---- annotations -----------------------------------------------------------------------------
def test_annotations_append_events_and_never_rewrite(tmp_path: Path) -> None:
    clock = FakeClock()
    _, store, _, before = _run(tmp_path, Scripted(), max_samples=3)
    original = (store.directory / "records.jsonl").read_bytes()
    with RunStore.open_existing(store.directory, fsync=False) as reopened:
        annotate(reopened, phase="T2", note="constant fps", clock=clock)
        annotate(reopened, boundary_reason="config change", clock=clock)
    after = (store.directory / "records.jsonl").read_bytes()
    assert after.startswith(original)  # history untouched
    added = [json.loads(x) for x in after[len(original) :].splitlines()]
    assert [a["annotations"]["event"] for a in added] == ["phase_start", "segment_boundary"]
    assert added[0]["annotations"]["phase"] == "T2" and added[0]["identity"] == {
        "device_id": "synthetic-dev-1"
    }
    assert len(before) < len(before) + 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"phase": "a", "boundary_reason": "b"},
        {"phase": "bad phase"},
        {"phase": "x" * 49},
        {"phase": "ok", "note": "tab\there"},
        {"boundary_reason": "n" * 201},
    ],
)
def test_annotation_validation(tmp_path: Path, kwargs: dict[str, str]) -> None:
    store = _store(tmp_path)
    with pytest.raises(CollectionError):
        annotate(store, **kwargs)
    store.close()
    assert (store.directory / "records.jsonl").read_text() == ""


def test_phase_annotation_drives_segments(tmp_path: Path) -> None:
    _, store, clock, _ = _run(tmp_path, Scripted(), max_samples=6)
    # An annotation with a timestamp in the middle of the run splits it.
    mid = load_run(store.directory).samples[3].ts_utc_ns
    with RunStore.open_existing(store.directory, fsync=False) as reopened:
        clock.utc = mid - 1
        annotate(reopened, phase="T3", clock=clock)
    segments = segment_run(load_run(store.directory))
    assert [s.phase for s in segments] == [None, "T3"]


# ---- import ----------------------------------------------------------------------------------
def _probe_line(run_id: str, **over: Any) -> dict[str, Any]:
    line = {
        "schema_version": 1,
        "record_type": "sample",
        "run_id": run_id,
        "producer": "axmem-probe",
        "ts_utc_ns": 1,
        "ts_mono_ns": 2,
        "identity": {"device_id": "d1", "pid": 5},
        "metrics": {
            "app.queue_depth_count": {"value": 0, "unit": "count", "source": "axmem_gauge"},
            "process.rss_bytes": {"available": False, "reason": "no procfs"},
        },
    }
    line.update(over)
    return line


def test_import_accepts_valid_lines_and_reports_each_rejection(tmp_path: Path) -> None:
    store = _store(tmp_path / "runs")
    rid = store.run_id
    bad_unit = _probe_line(rid)
    bad_unit["metrics"] = {"app.x_bytes": {"value": 1, "unit": "KiB", "source": "s"}}
    nan_line = json.dumps(_probe_line(rid)).replace('"value": 0', '"value": NaN')
    lines = [
        json.dumps(_probe_line(rid)),
        json.dumps(
            _probe_line(
                rid, record_type="event", annotations={"event": "phase_start", "phase": "T2"}
            )
        ),
        "{broken",
        json.dumps(_probe_line("00000000-0000-4000-8000-0000000000ff")),
        json.dumps(bad_unit),
        json.dumps(_probe_line(rid, identity={"device_id": "other-device"})),
        json.dumps(_probe_line(rid, extra_field=1)),
        json.dumps(_probe_line(rid, record_type="event")),
        nan_line,
        "",
        json.dumps(_probe_line(rid, ts_utc_ns=True)),
    ]
    source = tmp_path / "in.jsonl"
    source.write_text("\n".join(lines) + "\n")
    summary = import_records(source, store)
    store.close()
    assert summary.accepted == 2
    reasons = {n: why for n, why in summary.rejected}
    assert set(reasons) == {3, 4, 5, 6, 7, 8, 9, 11}
    assert "run_id" in reasons[4] and "KiB" not in reasons[5] and "bytes" in reasons[5]
    assert (
        "device" in reasons[6]
        and "unknown fields" in reasons[7]
        and "annotations.event" in reasons[8]
    )
    kept = (store.directory / "records.jsonl").read_text().splitlines()
    assert len(kept) == 2  # nothing rejected was written


def test_import_preserves_values_exactly(tmp_path: Path) -> None:
    store = _store(tmp_path / "runs")
    line = _probe_line(store.run_id)
    line["metrics"]["app.big_count"] = {
        "value": 18446744073709551615,
        "unit": "count",
        "source": "s",
    }
    source = tmp_path / "in.jsonl"
    source.write_text(json.dumps(line) + "\n")
    import_records(source, store)
    store.close()
    stored = json.loads((store.directory / "records.jsonl").read_text())
    assert stored["metrics"]["app.big_count"]["value"] == 18446744073709551615
    assert stored["metrics"]["process.rss_bytes"] == {"available": False, "reason": "no procfs"}


def test_peek_run_id_and_validate_record(tmp_path: Path) -> None:
    rid = new_run_id()
    path = tmp_path / "x.jsonl"
    path.write_text("junk\n" + json.dumps(_probe_line(rid)) + "\n")
    assert peek_run_id(path) == rid
    empty = tmp_path / "e.jsonl"
    empty.write_text("nothing\n")
    with pytest.raises(RunDataError):
        peek_run_id(empty)
    assert validate_record(_probe_line(rid), rid, "d1") is None
    assert validate_record([], rid, "d1") == "not a JSON object"
    assert "namespaced" in (validate_record(_probe_line(rid, metrics={"bad": 1}), rid, "d1") or "")
