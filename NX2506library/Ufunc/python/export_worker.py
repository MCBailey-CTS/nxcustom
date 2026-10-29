"""
A headless export worker (2026-10-23): export_pool.ExportPool starts this with
    run_journal.exe export_worker.py -args <host> <port> <authkey hex>
It connects back to the pool's listener in the interactive NX session, then runs the export jobs it is sent
(design_exports.run_job, worker=True: parts are opened from disk and closed again, nothing is saved) until it is
sent None or the connection drops. A run_journal session shares the user's NX license checkout, so a worker costs
no extra seat. Everything it prints goes to the log file the pool opened for it (%TEMP%\\tsg-export-worker-N.log).
"""

from __future__ import annotations

import os
import sys
import time
from multiprocessing.connection import Client

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import NXOpen  # noqa: E402

import design_exports  # noqa: E402


def _log(message: str) -> None:
    print("{} {}".format(time.strftime("%H:%M:%S"), message), flush=True)


def main() -> None:
    host, port, key = sys.argv[1], int(sys.argv[2]), bytes.fromhex(sys.argv[3])

    # No interpart data: a worker started from NX starts in NX's folder (NXstartup), whose load_options.def has
    # LoadWAVEParents ALL (it also gives the as-saved component loading the exports need, so the worker keeps the
    # folder and turns interpart data off here). With the parents, a 0.6 MB 006073 detail
    # then pulled in 44 job parts and the 13 layouts (512 MB) - 54 s to open, 69% of the workers' time, then
    # closed and loaded again for the next detail. Without it the same open is 1-2 s (just its fasteners). The
    # linked bodies keep the geometry they were saved with, which is current: the main session has the parents
    # loaded and saves every modified detail before handing it out.
    design_exports.nx.session_.Parts.LoadOptions.SetInterpartData(False, NXOpen.LoadOptions.Parent.Immediate)
    _log("worker {} connecting to {}:{}".format(os.getpid(), host, port))
    conn = Client((host, port), authkey=key)
    conn.send(("hello", os.getpid()))

    while True:
        try:
            job = conn.recv()
        except (EOFError, OSError):
            _log("the pool went away")
            break
        if job is None:
            _log("told to quit")
            break

        started = time.monotonic()
        payload: object
        if job["kind"] == "detail":
            # Update and save the detail, then its PDF / DWG exports: design_exports.run_detail's dict.
            _log("job {} detail {} ({} export(s))".format(job["id"], job["part"], len(job.get("exports", []))))
            detail = design_exports.run_detail(job, worker=True)
            payload = detail
            error = detail["error"]
            # One TIMINGS line per detail (seconds per step, plus sizes and counts) for summing across the logs.
            _log("TIMINGS {} {}".format(os.path.basename(job["part"]), " ".join(
                "{}={:.2f}".format(k, v) for k, v in sorted(detail.get("timings", {}).items()))))
            for export_id, export_error in detail["exports"].items():
                if export_error is not None:
                    _log("  export {} FAILED\n{}".format(export_id, export_error))
        else:
            _log("job {} {} {} -> {}".format(job["id"], job["kind"], job["part"], job["output"]))
            error = design_exports.run_job(job, worker=True)
            payload = error
        elapsed = time.monotonic() - started
        _log("job {} {} in {:.1f}s{}".format(job["id"], "ok" if error is None else "FAILED", elapsed,
                                             "" if error is None else "\n" + error))
        try:
            conn.send((job["id"], payload, elapsed))
        except (EOFError, OSError):
            break

    conn.close()


if __name__ == "__main__":
    main()
