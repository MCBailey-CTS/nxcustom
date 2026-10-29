"""
Runs Assembly Export Design Data's detail updates and exports several at a time (2026-10-23).

Detail updates (design_exports.update_part: display the detail, set the export layers, unblank, update the drafting
views, save) go to headless NX workers (export_worker.py under run_journal.exe; they share the user's license
checkout). NX only reads or sets layers on the DISPLAYED part, so one session can update one detail at a time;
each worker displays its own. A worker gets one "detail" job per part: it opens the part, updates and saves it,
then runs that part's PDF / DWG exports while the part is open and current. The workers connect back over a local
socket with a random password and are fed by a background thread that only does socket I/O.

STEP jobs do not need NX at all: they are split into translator runs (step214ug.exe with a .def listing up to
MaxPartsPerRun parts, design_exports.write_step_batch_def), up to `translators` of them at once, started straight
from this session as plain processes. A part's STEP waits until its detail update has been saved. A run's ~5-6 s
start-up is most of a small part's export time, so one run of several parts costs little more than one part.

    pool = ExportPool()
    pool.start()                          # start early: a worker needs ~15-20 s to come up
    ... strip set-up, save ...
    failures = pool.run(jobs, updates)    # blocks until every update and export has run
    pool.close()

This session only takes detail / PDF / DWG jobs itself when there are no workers (TSG_EXPORT_WORKERS=0), or when
none connected within WorkerGrace seconds, or every worker has died - then it works through what is left exactly
as the one-at-a-time RTO did. After a run with workers, this session's copies of the updated details are older
than the files on disk; it does not save them again (nothing here modifies them).

TSG_EXPORT_TRANSLATORS / TSG_EXPORT_WORKERS override the defaults.
"""

from __future__ import annotations

import math
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from multiprocessing.connection import Connection, Listener, wait
from typing import IO, Any, Deque, Dict, List, Optional, Tuple, cast

import tsg_nx as nx
from design_exports import Job, run_detail, run_job, step_translator, write_step_batch_def

_here = os.path.dirname(os.path.abspath(__file__))

# Headless NX workers for the detail updates and PDF / DWG exports (0 = this session does them, one at a time).
DefaultWorkers = 3
# STEP translator runs at once (this PC has 4 cores), and the most parts one run gets: a run reports nothing until
# it ends, and a long PROCESS_PART_LIST line is not something to test the translator's limits with.
DefaultTranslators = 4
MaxPartsPerRun = 10
# While detail updates are still releasing STEPs, a free translator starts on as few as this many rather than
# waiting for a full run - waiting left translators idle through the updates and piled the STEPs up at the end
# (006073: ~6 min of STEPs after the last update).
MinPartsPerRun = 3
# How long this session waits for a first worker before it starts on the detail jobs itself.
WorkerGrace = 90.0

_RunJournalFallback = "C:\\Program Files\\Siemens\\NX2306.6001\\NXBIN\\run_journal.exe"
_CreateNoWindow = 0x08000000


def _setting(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except ValueError:
        return default


def default_workers() -> int:
    return _setting("TSG_EXPORT_WORKERS", DefaultWorkers, 0)


def default_translators() -> int:
    return _setting("TSG_EXPORT_TRANSLATORS", DefaultTranslators, 0)


def _run_journal() -> str:
    base = os.environ.get("UGII_BASE_DIR", "")
    candidate = os.path.join(base, "NXBIN", "run_journal.exe") if base else ""
    return candidate if candidate and os.path.isfile(candidate) else _RunJournalFallback


def _step_key(job: Job) -> str:
    """Jobs that can share a translator run: one settings file and one part folder (FILE_FILTER)."""
    return "{}|{}".format(job["settings"].lower(), os.path.dirname(job["part"]).lower())


class _StepRun(object):
    """One step214ug.exe run over several STEP jobs that share a settings file and a part folder."""

    def __init__(self, jobs: List[Job], number: int) -> None:
        self.jobs = jobs
        self.number = number
        self.folder = tempfile.mkdtemp(prefix="tsg-step-")
        self.log = os.path.join(self.folder, "step214ug.log")
        self.process: Optional[subprocess.Popen] = None
        self.started = 0.0

    def start(self) -> None:
        def_path = os.path.join(self.folder, "step214ug.def")
        write_step_batch_def(self.jobs[0]["settings"], [j["part"] for j in self.jobs],
                             [j["output"] for j in self.jobs], self.log, def_path)
        self.started = time.monotonic()
        # Started in its own folder: NX reads load_options.def from the current folder, and NX's (NXstartup) has
        # LoadWAVEParents ALL, which the .def's "Overwrite load_options.def values" does not cover - a 0.6 MB
        # 006073 detail took 66 s instead of 5.5 s, loading every WAVE parent and the layouts. Components still
        # load as saved (UGI_LOAD_OPTION in the .def); the output is the same.
        self.process = subprocess.Popen([step_translator(), "d=" + def_path], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, creationflags=_CreateNoWindow, cwd=self.folder)

    def finished(self) -> bool:
        return self.process is not None and self.process.poll() is not None

    def results(self) -> List[Tuple[Job, Optional[str]]]:
        """Each job with None, or why it failed. Keeps the run's log folder when anything failed."""
        code = self.process.returncode if self.process is not None else None
        results: List[Tuple[Job, Optional[str]]] = []
        for job in self.jobs:
            output = job["output"]
            if os.path.isfile(output) and os.path.getsize(output) > 0:
                results.append((job, None))
            else:
                results.append((job, "no file was written (step214ug exit code {}; log {})".format(code, self.log)))
            # _stp's clean-up of the translator's per-part log.
            log = output.replace(".stp", ".log")
            if os.path.isfile(log):
                try:
                    os.remove(log)
                except OSError:
                    pass
        if all(error is None for _job, error in results):
            shutil.rmtree(self.folder, ignore_errors=True)
        return results

    def kill(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()


class ExportPool(object):

    def __init__(self, workers: Optional[int] = None, translators: Optional[int] = None) -> None:
        self.workers = default_workers() if workers is None else workers
        # 0 translators: no batched step214ug runs - STEP jobs go through NX's StepCreator, one at a time, in the
        # workers (or this session) like the PDFs.
        self.translators = default_translators() if translators is None else max(0, translators)
        self._listener: Optional[Listener] = None
        self._processes: List[subprocess.Popen] = []
        self._logs: List[IO[str]] = []
        self._lock = threading.Lock()
        self._arrived: List[Connection] = []
        self._connections: List[Connection] = []
        self._names: Dict[Connection, str] = {}
        self._step_runs: List[_StepRun] = []
        self._started = time.monotonic()

    def __enter__(self) -> "ExportPool":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ----- workers -----

    def start(self) -> None:
        self._started = time.monotonic()
        if self.workers <= 0:
            return
        key = os.urandom(16)
        self._listener = Listener(("127.0.0.1", 0), authkey=key)
        host, port = cast(Tuple[str, int], self._listener.address)
        script = os.path.join(_here, "export_worker.py")
        run_journal = _run_journal()

        for i in range(self.workers):
            log_path = os.path.join(tempfile.gettempdir(), "tsg-export-worker-{}.log".format(i + 1))
            log = open(log_path, "w", encoding="utf-8")
            self._logs.append(log)
            self._processes.append(subprocess.Popen(
                [run_journal, script, "-args", host, str(port), key.hex()],
                stdout=log, stderr=subprocess.STDOUT, creationflags=_CreateNoWindow))
        nx.syslog("ExportPool: started {} worker(s) with {}, listening on {}:{}".format(
            self.workers, run_journal, host, port))

        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        listener = self._listener
        assert listener is not None
        while True:
            try:
                conn = listener.accept()
                _hello, pid = conn.recv()
            except Exception:
                if self._listener is None:
                    return      # closed
                continue        # a worker that failed the handshake
            with self._lock:
                self._names[conn] = "worker {}".format(pid)
                self._arrived.append(conn)

    def _take_arrivals(self) -> List[Connection]:
        """Connections that arrived since the last call (thread-safe; makes no NX calls)."""
        with self._lock:
            arrived, self._arrived = self._arrived, []
            self._connections.extend(arrived)
        return arrived

    def _workers_available(self) -> bool:
        """Whether a worker is connected, or may still connect - else this session does the NX jobs itself."""
        if self.workers <= 0:
            return False
        with self._lock:
            if self._connections or self._arrived:
                return True
        if all(p.poll() is not None for p in self._processes):
            return False
        return time.monotonic() - self._started < WorkerGrace

    # ----- run -----

    def run(self, jobs: List[Job], updates: Optional[List[Dict[str, Any]]] = None) -> List[Tuple[Job, str]]:
        """
        Runs the detail updates and every export job; returns the (job, error) pairs that failed - an update that
        failed is listed as a job with kind "detail". updates are {"part": full path, "casting": bool}; a part's
        PDF / DWG jobs run inside its detail job and its STEP jobs wait until that job has saved it. Prints a line
        per finished job.
        """
        updates = updates or []
        update_keys = {u["part"].lower() for u in updates}
        results: "queue.Queue[Tuple[str, Any, Any, Any, str]]" = queue.Queue()
        stop = threading.Event()
        failures: List[Tuple[Job, str]] = []
        total = len(jobs)
        done = 0
        updates_total = len(updates)
        updates_done = 0
        counts: Dict[str, int] = {}
        started = time.monotonic()

        def count(who: str) -> None:
            group = "translators" if who.startswith("translator") else \
                "workers" if who.startswith("worker") else who
            counts[group] = counts.get(group, 0) + 1

        def export_done(job: Job, error: Optional[str], elapsed: float, who: str) -> None:
            nonlocal done
            done += 1
            count(who)
            nx.prompt("Exports: {} of {} done; detail updates: {} of {}".format(done, total, updates_done,
                                                                               updates_total))
            if error is None:
                nx.print_("{} {} of {} ({}, {:.1f}s) -> {}".format(job["label"], done, total, who, elapsed,
                                                                   job["output"]))
            else:
                failures.append((job, error))
                nx.print_("{} FAILED ({}): {}\n{}".format(job["label"], who, job["output"], error))

        # ----- sort the jobs -----
        exports_by_part: Dict[str, List[Job]] = {}
        standalone: List[Job] = []
        step_ready: List[Job] = []
        step_blocked: Dict[str, List[Job]] = {}
        step_total = 0

        for job in jobs:
            key = job["part"].lower()
            if job["kind"] == "stp" and self.translators > 0:
                # A missing part or an existing output fails now, as _stp raised for them.
                if not os.path.isfile(job["part"]):
                    export_done(job, "Could not find file location \"{}\".".format(job["part"]), 0.0, "translator")
                elif os.path.isfile(job["output"]):
                    export_done(job, "STP \"{}\" already exists.".format(job["output"]), 0.0, "translator")
                elif key in update_keys:
                    step_blocked.setdefault(key, []).append(job)
                    step_total += 1
                else:
                    step_ready.append(job)
                    step_total += 1
            elif key in update_keys:
                exports_by_part.setdefault(key, []).append(job)
            else:
                standalone.append(job)

        def size(path: str) -> int:
            try:
                return os.path.getsize(path)
            except OSError:
                return 0

        # Biggest details first: the slow ones (40 s against a few) do not end up last on one worker, and their
        # STEPs - also the slow ones - reach the translators early.
        pending: Deque[Job] = deque()
        for i, update in enumerate(sorted(updates, key=lambda u: -size(u["part"]))):
            pending.append({"id": "u{}".format(i + 1), "kind": "detail", "part": update["part"],
                            "casting": bool(update.get("casting")), "label": "Update",
                            "output": update["part"], "exports": exports_by_part.get(update["part"].lower(), [])})
        pending.extend(standalone)

        def detail_done(job: Job, payload: Dict[str, Any], elapsed: float, who: str) -> None:
            nonlocal updates_done
            updates_done += 1
            count(who)
            leaf = os.path.splitext(os.path.basename(job["part"]))[0]
            for message in payload.get("messages", []):
                nx.print_(message)
            if payload.get("error") is None:
                nx.print_("Updated {} of {}: {} ({}, {:.1f}s)".format(updates_done, updates_total, leaf, who, elapsed))
            else:
                failures.append((job, payload["error"]))
                nx.print_("Update FAILED ({}): {}\n{}".format(who, leaf, payload["error"]))
            for export in job.get("exports", []):
                error = payload.get("exports", {}).get(export["id"], "not run: the worker did not report it")
                export_done(export, error, elapsed, who)
            # Its STEPs can run now that the part is saved (or its update has failed, as the serial RTO also
            # exported what it had).
            step_ready.extend(step_blocked.pop(job["part"].lower(), []))

        def finished(kind: str, job: Any, payload: Any, elapsed: Any, who: str) -> None:
            if kind == "connected":
                nx.syslog("ExportPool: {} connected".format(who))
            elif kind == "lost":
                nx.print_("{} stopped; {} goes back on the list.".format(who, job["part"]))
            elif job["kind"] == "detail":
                detail_done(job, payload, elapsed, who)
            else:
                export_done(job, payload, elapsed, who)

        # ----- STEP translator runs -----
        per_run = max(1, min(MaxPartsPerRun, int(math.ceil(step_total / float(self.translators))))) \
            if step_total and self.translators > 0 else 1
        active = self._step_runs
        run_number = 0

        def poll_step_runs() -> None:
            nonlocal run_number
            for step_run in [r for r in active if r.finished()]:
                active.remove(step_run)
                elapsed = time.monotonic() - step_run.started
                who = "translator run {}, {} part(s)".format(step_run.number, len(step_run.jobs))
                for job, error in step_run.results():
                    export_done(job, error, elapsed, who)

            while step_ready and len(active) < self.translators:
                groups: Dict[str, List[Job]] = {}
                for job in step_ready:
                    groups.setdefault(_step_key(job), []).append(job)
                group = max(groups.values(), key=len)
                if step_blocked:
                    # Updates are still releasing STEPs: start on a few rather than leave this translator idle.
                    if len(group) < min(per_run, MinPartsPerRun) and active:
                        break
                    take = group[:per_run]
                else:
                    # All released: spread what is left over the free translators, so they finish together.
                    free = self.translators - len(active)
                    take = group[:max(1, min(per_run, int(math.ceil(len(step_ready) / float(free)))))]
                for job in take:
                    step_ready.remove(job)
                run_number += 1
                step_run = _StepRun(take, run_number)
                try:
                    step_run.start()
                    active.append(step_run)
                except Exception as ex:
                    for job in take:
                        export_done(job, "{}: {}".format(type(ex).__name__, ex), 0.0, "translator")

        # ----- workers -----
        def take_job() -> Optional[Job]:
            with self._lock:
                return pending.popleft() if pending else None

        def feed_workers() -> None:
            idle: List[Connection] = []
            busy: Dict[Connection, Job] = {}
            while not stop.is_set():
                for conn in self._take_arrivals():
                    results.put(("connected", None, None, None, self._names.get(conn, "worker")))
                    idle.append(conn)

                while idle:
                    job = take_job()
                    if job is None:
                        break
                    conn = idle.pop()
                    try:
                        conn.send(job)
                        busy[conn] = job
                    except (EOFError, OSError):
                        with self._lock:
                            pending.appendleft(job)
                        self._drop(conn)

                if not busy:
                    stop.wait(0.2)
                    continue

                for ready in wait(list(busy), timeout=0.2):
                    conn = cast(Connection, ready)
                    job = busy.pop(conn)
                    who = self._names.get(conn, "worker")
                    try:
                        _job_id, payload, elapsed = conn.recv()
                    except (EOFError, OSError):
                        with self._lock:
                            pending.appendleft(job)
                        self._drop(conn)
                        results.put(("lost", job, None, None, who))
                        continue
                    results.put(("done", job, payload, elapsed, who))
                    idle.append(conn)

        feeder = threading.Thread(target=feed_workers, daemon=True)
        if self._listener is not None:
            feeder.start()
        try:
            while done < total or updates_done < updates_total:
                poll_step_runs()
                while True:
                    try:
                        finished(*results.get_nowait())
                    except queue.Empty:
                        break
                if done >= total and updates_done >= updates_total:
                    break

                local_job = None if self._workers_available() else take_job()
                if local_job is not None:
                    job_started = time.monotonic()
                    if local_job["kind"] == "detail":
                        nx.prompt("Updating {} ({} of {} done)".format(local_job["part"], updates_done,
                                                                      updates_total))
                        detail_done(local_job, run_detail(local_job, worker=False), time.monotonic() - job_started,
                                    "this session")
                    else:
                        export_done(local_job, run_job(local_job, worker=False), time.monotonic() - job_started,
                                    "this session")
                else:
                    try:
                        finished(*results.get(timeout=0.2))
                    except queue.Empty:
                        pass
        finally:
            for step_run in active:
                step_run.kill()
            del active[:]
            stop.set()
            if feeder.is_alive():
                feeder.join(5)

        summary = ", ".join("{} {}".format(who, n) for who, n in sorted(counts.items()))
        line = "{} detail update(s) and {} export(s) in {:.1f}s ({}); {} failed.".format(
            updates_total, total, time.monotonic() - started, summary or "none", len(failures))
        nx.print_(line)
        nx.syslog("ExportPool: " + line)
        return failures

    # ----- shutdown -----

    def _drop(self, conn: Connection) -> None:
        with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)
        try:
            conn.close()
        except OSError:
            pass

    def close(self) -> None:
        for step_run in self._step_runs:
            step_run.kill()
        self._step_runs = []
        self._take_arrivals()
        with self._lock:
            connections = list(self._connections)
        for conn in connections:
            try:
                conn.send(None)
            except (EOFError, OSError):
                pass
            self._drop(conn)

        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()

        deadline = time.monotonic() + 15
        for process in self._processes:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
        self._processes = []

        for log in self._logs:
            log.close()
        self._logs = []
