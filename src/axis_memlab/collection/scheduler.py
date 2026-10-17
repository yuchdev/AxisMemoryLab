"""Bounded, read-only collection loop.

Per cycle it makes one batched read for the regular sources (``meminfo``, ``vmstat``, PSI,
process ``status``/``stat``) and, at the sparse interval or on a trigger, ``smaps_rollup``, the
fd inventory and the cgroup charge. It never restarts the application, never falls back to full
``smaps``, and never starts an intrusive capture. Time is injected so tests do not sleep.

Failure policy: a source that cannot be read becomes explicit unavailable metrics plus one
``error`` record when it first fails (not once per cycle); a transport failure backs off
exponentially and ends the run as ``failed`` after repeated failures; memory pressure below the
abort threshold ends the run as ``incomplete`` before any heavier read is attempted.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from axis_memlab.capability import capability_record
from axis_memlab.collection.discovery import Discovery, discover, select_process
from axis_memlab.collection.run_store import RunStore
from axis_memlab.collection.triggers import TriggerEvaluator
from axis_memlab.errors import CollectionError, TransportError
from axis_memlab.records import Metric, Record
from axis_memlab.sources import cgroup as cgroup_source
from axis_memlab.sources import fd as fd_source
from axis_memlab.sources import meminfo, proc_status, psi, smaps, vmstat
from axis_memlab.sources.common import unavailable, value
from axis_memlab.transport import Reader, ReadError

PRODUCER = "axis-memlab-collector"
MAX_CONSECUTIVE_TRANSPORT_FAILURES = 5
MAX_BACKOFF_SECONDS = 60.0

AVAILABLE = "system.mem.available_bytes"
PSS = "process.pss_bytes"


class Clock(Protocol):
    def utc_ns(self) -> int: ...
    def mono_ns(self) -> int: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def utc_ns(self) -> int:
        return time.time_ns()

    def mono_ns(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class CollectResult:
    status: str  # complete | incomplete | failed
    samples: int
    reason: str


def _parse_start(text: str) -> int | None:
    return proc_status.parse_start_ticks(text)


class Collector:
    def __init__(
        self,
        reader: Reader,
        store: RunStore,
        config: dict[str, Any],
        *,
        device_id: str,
        clock: Clock | None = None,
        pid: int | None = None,
        app: str | None = None,
        max_samples: int | None = None,
        duration_seconds: float | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        c = config["collection"]
        self._reader = reader
        self._store = store
        self._device_id = device_id
        self._clock = clock or SystemClock()
        self._pid_arg, self._app = pid, app
        self._interval = float(c["sample_interval_seconds"])
        self._sparse_interval = float(c["smaps_rollup_interval_seconds"])
        self._budget_s = float(c["max_snapshot_seconds"])
        self._mem_low = int(c["trigger_mem_available_below_bytes"])
        self._sparse_skipped = False
        self._missing_reported = False
        self._max_samples = max_samples
        self._duration = duration_seconds
        self._on_progress = on_progress
        self._triggers = TriggerEvaluator(
            pss_growth_bytes=c["trigger_pss_growth_bytes"],
            mem_available_below_bytes=c["trigger_mem_available_below_bytes"],
            abort_mem_available_below_bytes=c["abort_mem_available_below_bytes"],
            cooldown_seconds=c["deep_snapshot_cooldown_seconds"],
        )
        self.pid: int | None = None
        self._boot_id: str | None = None
        self._start_ticks: int | None = None
        self._cgroup: tuple[int, str] | None = None
        self._source_ok: dict[str, bool] = {}
        self._reads = 0
        self._read_errors = 0
        self._bytes = 0
        self._samples = 0
        self._next_sparse_s = 0.0
        self._origin_ns = 0

    # ---- record helpers -----------------------------------------------------------------
    def _identity(self) -> dict[str, Any]:
        identity: dict[str, Any] = {"device_id": self._device_id}
        if self._boot_id:
            identity["boot_id"] = self._boot_id
        if self.pid is not None:
            identity["pid"] = self.pid
        if self._start_ticks is not None:
            identity["process_start_ticks"] = self._start_ticks
        return identity

    def _emit(
        self,
        record_type: str,
        metrics: dict[str, Metric] | None = None,
        annotations: dict[str, Any] | None = None,
    ) -> None:
        self._store.append(
            Record(
                record_type=record_type,
                run_id=self._store.run_id,
                producer=PRODUCER,
                ts_utc_ns=self._clock.utc_ns(),
                ts_mono_ns=self._clock.mono_ns(),
                identity=self._identity(),
                metrics=metrics or {},
                annotations=annotations,
            )
        )

    def _event(self, name: str, **fields: Any) -> None:
        self._emit("event", annotations={"event": name, **fields})

    def _transition(self, key: str, ok: bool, code: str = "", detail: str = "") -> None:
        previous = self._source_ok.get(key)
        self._source_ok[key] = ok
        if not ok and previous is not False:
            self._emit(
                "error", annotations={"source": key, "reason_code": code, "detail": detail[:200]}
            )
        elif ok and previous is False:
            self._event("source_recovered", source=key)

    # ---- ingestion ----------------------------------------------------------------------
    def _ingest(
        self,
        metrics: dict[str, Metric],
        key: str,
        result: str | ReadError,
        parser: Callable[[str], dict[str, Metric]],
        names: list[str],
    ) -> dict[str, Metric] | None:
        self._reads += 1
        if isinstance(result, ReadError):
            self._read_errors += 1
            for name in names:
                metrics[name] = unavailable(result.code, result.detail)
            self._transition(key, False, result.code, result.detail)
            return None
        self._bytes += len(result.encode("utf-8", errors="replace"))
        parsed = parser(result)
        metrics.update(parsed)
        if any(m.available for m in parsed.values()):
            self._transition(key, True)
        else:
            self._read_errors += 1
            self._transition(key, False, "parse_error", "no usable fields in output")
        return parsed

    def _resolve_process(self) -> None:
        if self._pid_arg is not None:
            self.pid = self._pid_arg
        elif self._app is not None and self.pid is None:
            try:
                self.pid, _ = select_process(self._reader, None, self._app)
            except CollectionError:
                self.pid = None  # not running (yet): process metrics stay unavailable

    def _resolve_cgroup(self) -> None:
        self._cgroup = None
        if self.pid is None:
            return
        try:
            text = self._reader.read_text(f"/proc/{self.pid}/cgroup")
        except ReadError:
            return
        self._cgroup = cgroup_source.parse_proc_cgroup(text)

    def _sparse(self, metrics: dict[str, Metric]) -> None:
        """smaps_rollup, fd inventory, cgroup charge: the heavier reads, at the sparse cadence."""
        if self.pid is None:
            return
        paths = [f"/proc/{self.pid}/smaps_rollup"]
        files: dict[str, str] = {}
        if self._cgroup is not None:
            files = cgroup_source.files_for(*self._cgroup)
            paths += list(files.values())
        results = self._reader.read_many(paths)
        self._ingest(metrics, "smaps_rollup", results[paths[0]], smaps.parse, smaps.metric_names())
        try:
            targets = self._reader.read_fd_targets(self.pid)
        except ReadError as exc:
            self._reads += 1
            self._read_errors += 1
            for name in fd_source.metric_names():
                metrics[name] = unavailable(exc.code, exc.detail)
            self._transition("fd", False, exc.code, exc.detail)
        else:
            self._reads += 1
            metrics.update(fd_source.metrics(targets))
            self._transition("fd", True)
        if self._cgroup is not None:
            texts: dict[str, str] = {}
            failure: ReadError | None = None
            for leaf, path in files.items():
                got = results[path]
                if isinstance(got, ReadError):
                    if leaf == "current":
                        failure = got
                else:
                    texts[leaf] = got
            self._reads += 1
            if failure is not None:
                self._read_errors += 1
                for name in cgroup_source.metric_names():
                    metrics[name] = unavailable(failure.code, failure.detail)
                self._transition("cgroup", False, failure.code, failure.detail)
            else:
                metrics.update(cgroup_source.parse(self._cgroup[0], texts))
                self._transition("cgroup", True)

    # ---- one cycle ----------------------------------------------------------------------
    def _cycle(self, force_sparse: bool = False) -> bool:
        """Read, write one sample, evaluate triggers. Returns False when the run must stop."""
        started = self._clock.mono_ns()
        now_s = (started - self._origin_ns) / 1e9
        self._resolve_process()
        metrics: dict[str, Metric] = {}
        paths = ["/proc/meminfo", "/proc/vmstat", "/proc/pressure/memory"]
        if self.pid is not None:
            paths += [f"/proc/{self.pid}/status", f"/proc/{self.pid}/stat"]
        results = self._reader.read_many(paths)
        self._ingest(metrics, "meminfo", results[paths[0]], meminfo.parse, meminfo.metric_names())
        self._ingest(metrics, "vmstat", results[paths[1]], vmstat.parse, vmstat.metric_names())
        self._ingest(metrics, "psi", results[paths[2]], psi.parse, psi.metric_names())

        if self.pid is not None:
            status = self._ingest(
                metrics,
                "process_status",
                results[paths[3]],
                proc_status.parse_status,
                proc_status.status_metric_names(),
            )
            stat_result = results[paths[4]]
            self._ingest(
                metrics,
                "process_stat",
                stat_result,
                proc_status.parse_stat,
                proc_status.stat_metric_names(),
            )
            if isinstance(stat_result, str):
                ticks = _parse_start(stat_result)
                if ticks is not None and self._start_ticks not in (None, ticks):
                    self._event("process_restart", previous_start_ticks=self._start_ticks)
                    self._triggers.reset_process()
                    self._cgroup = None
                    self._next_sparse_s = now_s
                if ticks is not None:
                    self._start_ticks = ticks
            status_result = results[paths[3]]
            if status is not None:
                self._missing_reported = False
            if (
                status is None
                and isinstance(status_result, ReadError)
                and status_result.code == "missing"
            ):
                if not self._missing_reported:
                    self._event("process_missing")
                self._missing_reported = True
                if self._app is not None:
                    self.pid, self._start_ticks, self._cgroup = None, None, None

        elif self._pid_arg is not None or self._app is not None:
            for name in (*proc_status.status_metric_names(), *proc_status.stat_metric_names()):
                metrics[name] = unavailable("missing", "no matching process is visible")

        avail_metric = metrics.get(AVAILABLE)
        available_bytes = (
            int(avail_metric.value)
            if avail_metric and avail_metric.available and isinstance(avail_metric.value, int)
            else None
        )
        # Heavier reads (page-table walks, fd listing) are not made while memory is already low.
        under_pressure = available_bytes is not None and available_bytes < self._mem_low
        sparse_due = force_sparse or now_s >= self._next_sparse_s
        sparse_done = False
        if sparse_due and self.pid is not None:
            if under_pressure:
                if not self._sparse_skipped:
                    self._event("sparse_skipped", reason="memory_pressure")
                self._sparse_skipped = True
            else:
                self._sparse_skipped = False
                if self._cgroup is None:
                    self._resolve_cgroup()
                self._sparse(metrics)
                self._next_sparse_s = now_s + self._sparse_interval
                sparse_done = True

        pss = metrics.get(PSS)
        decision = self._triggers.evaluate(
            now_s,
            int(pss.value) if pss and pss.available and isinstance(pss.value, int) else None,
            available_bytes,
        )
        for trigger in decision.triggers:
            self._event(
                "trigger_fired",
                trigger=trigger.name,
                detail=trigger.detail,
                snapshot="skipped_memory_pressure" if not trigger.snapshot_allowed else "sparse",
            )
            if trigger.snapshot_allowed and not sparse_done and self.pid is not None:
                self._sparse(metrics)
                sparse_done = True

        elapsed_ns = self._clock.mono_ns() - started
        metrics["collector.cycle_duration_ns"] = value(elapsed_ns, "nanoseconds", "axis-memlab")
        metrics["collector.reads_total_count"] = value(self._reads, "count", "axis-memlab")
        metrics["collector.read_errors_count"] = value(self._read_errors, "count", "axis-memlab")
        metrics["collector.bytes_read_bytes"] = value(self._bytes, "bytes", "axis-memlab")
        self._emit("sample", metrics)
        self._samples += 1
        if self._on_progress:
            self._on_progress(self._samples)
        if elapsed_ns / 1e9 > self._budget_s:
            self._transition(
                "cycle_budget", False, "timeout", f"cycle took {elapsed_ns / 1e9:.1f} s"
            )
        else:
            self._transition("cycle_budget", True)

        if decision.abort:
            self._event("abort_memory_pressure")
            return False
        return True

    # ---- public --------------------------------------------------------------------------
    def _setup(self) -> Discovery:
        found = discover(self._reader, pid=self._pid_arg, app=self._app)
        self.pid = found.pid
        self._boot_id = found.facts.get("boot_id")
        self._cgroup = found.cgroup
        for capability in found.capabilities:
            self._store.append(
                capability_record(
                    capability,
                    run_id=self._store.run_id,
                    device_id=self._device_id,
                    producer=PRODUCER,
                    ts_utc_ns=self._clock.utc_ns(),
                    ts_mono_ns=self._clock.mono_ns(),
                    pid=found.pid,
                )
            )
        return found

    def snapshot(self) -> CollectResult:
        """One sample with the sparse reads forced; ``deep`` captures do not exist."""
        self._origin_ns = self._clock.mono_ns()
        try:
            self._setup()
            self._event("snapshot", level="sparse")
            self._cycle(force_sparse=True)
        except TransportError as exc:
            self._emit(
                "error",
                annotations={
                    "source": "transport",
                    "reason_code": "timeout",
                    "detail": str(exc)[:200],
                },
            )
            return CollectResult("failed", self._samples, str(exc))
        return CollectResult("complete", self._samples, "snapshot taken")

    def run(self) -> CollectResult:
        self._origin_ns = self._clock.mono_ns()
        status, reason = "complete", "finished"
        try:
            self._setup()
            self._emit("run_start", annotations={"interval_seconds": self._interval})
            failures = 0
            while True:
                tick_started = self._clock.mono_ns()
                try:
                    keep_going = self._cycle()
                    failures = 0
                except TransportError as exc:
                    failures += 1
                    self._emit(
                        "error",
                        annotations={
                            "source": "transport",
                            "reason_code": "timeout",
                            "detail": str(exc)[:200],
                        },
                    )
                    if failures >= MAX_CONSECUTIVE_TRANSPORT_FAILURES:
                        status, reason = "failed", "repeated transport failures"
                        break
                    self._clock.sleep(min(2.0**failures, MAX_BACKOFF_SECONDS))
                    continue
                if not keep_going:
                    status, reason = "incomplete", "memory available fell below the abort threshold"
                    break
                if self._max_samples is not None and self._samples >= self._max_samples:
                    break
                elapsed_total = (self._clock.mono_ns() - self._origin_ns) / 1e9
                if self._duration is not None and elapsed_total >= self._duration:
                    break
                spent = (self._clock.mono_ns() - tick_started) / 1e9
                self._clock.sleep(max(0.0, self._interval - spent))
        except KeyboardInterrupt:
            status, reason = "incomplete", "interrupted by operator"
        except TransportError as exc:
            status, reason = "failed", f"could not start: {exc}"
        self._emit("run_stop", annotations={"status": status, "reason": reason})
        return CollectResult(status, self._samples, reason)
