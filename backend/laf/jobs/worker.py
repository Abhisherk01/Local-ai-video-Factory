"""Background job worker (ADR-009).

One daemon thread with its OWN SQLite connection (the Phase 2 shared
connection stays with the API handlers; per-thread connections are the
Phase 3 concurrency rule from laf.db.connection). The loop:

  1. reclaim_stale()  - crash recovery for rows orphaned by a kill
  2. claim_next()     - atomic claim, GPU jobs serialized (concurrency 1)
  3. dispatch         - handler(payload, job, ctx); exception -> fail()
  4. heartbeat loop   - a helper thread refreshes heartbeat_at while a
                        job runs, so reclaim_stale never double-runs a
                        live job

Lifecycle: start() spawns the thread; stop() flips the event and joins.
The FastAPI lifespan owns both, so tests and `python -m laf.server`
get identical behavior. `create_app(worker_enabled=False)` runs the
API without a worker (used by tests and debugging).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from laf.db import connect
from laf.jobs import queue
from laf.jobs.handlers import (
    JOB_HANDLERS,
    Handler,
    HandlerContext,
    NonRetryable,
    PrereqMissing,
)

logger = logging.getLogger("laf.jobs.worker")

_HEARTBEAT_INTERVAL_S = 20.0


class Worker:
    def __init__(
        self,
        db_path: Path,
        *,
        data_dir: Path,
        models_dir: Path,
        poll_interval_s: float = 0.5,
        stale_after_s: float = 120.0,
        handlers: dict[str, Handler] | None = None,
        worker_id: str | None = None,
        kinds: set[str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.models_dir = Path(models_dir)
        self.poll_interval_s = poll_interval_s
        self.stale_after_s = stale_after_s
        self.handlers = handlers if handlers is not None else dict(JOB_HANDLERS)
        self.worker_id = worker_id or f"worker-{int(time.time())}"
        self.kinds = kinds

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_job_id: int | None = None
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("worker already started")
        self._thread = threading.Thread(
            target=self._run, name="laf-worker", daemon=True
        )
        self._thread.start()
        logger.info("worker started", extra={"worker_id": self.worker_id})

    def stop(self, timeout_s: float = 3.0) -> None:
        self._stop.set()
        self._hb_stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            self._thread = None
        logger.info("worker stopped")

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # loop
    # ------------------------------------------------------------------

    def _run(self) -> None:  # runs in the worker thread
        conn = connect(self.db_path)
        try:
            while not self._stop.is_set():
                try:
                    queue.reclaim_stale(conn, stale_after_s=self.stale_after_s)
                    job = queue.claim_next(
                        conn, worker_id=self.worker_id, kinds=self.kinds
                    )
                except sqlite3.Error as exc:  # pragma: no cover - defensive
                    logger.error("worker db error", extra={"error": str(exc)})
                    job = None
                if job is None:
                    self._stop.wait(self.poll_interval_s)
                    continue
                self._execute(conn, job)
        finally:
            conn.close()

    def _execute(self, conn: sqlite3.Connection, job: dict) -> None:
        handler = self.handlers.get(str(job["type"]))
        if handler is None:
            queue.fail(
                conn, int(job["id"]),
                f"no handler registered for job type '{job['type']}'",
                retry=False,
            )
            return
        ctx = HandlerContext(
            conn=conn, data_dir=self.data_dir, models_dir=self.models_dir
        )
        self._current_job_id = int(job["id"])
        self._hb_stop.clear()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, args=(conn,), name="laf-worker-hb",
            daemon=True,
        )
        self._hb_thread.start()
        logger.info(
            "job started",
            extra={"job_id": job["id"], "type": job["type"], "attempt": job["attempts"]},
        )
        try:
            result = handler(dict(job["payload"]), job, ctx)
            queue.complete(conn, int(job["id"]), result)
            logger.info("job succeeded", extra={"job_id": job["id"], "type": job["type"]})
        except PrereqMissing as exc:
            queue.fail(conn, int(job["id"]), f"prereq_missing: {exc}", retry=False)
            logger.warning("job prereq missing", extra={"job_id": job["id"], "error": str(exc)})
        except NonRetryable as exc:
            queue.fail(
                conn, int(job["id"]), f"non_retryable: {exc}", retry=False
            )
            logger.warning(
                "job failed (non-retryable)",
                extra={"job_id": job["id"], "error": str(exc)},
            )
        except Exception as exc:  # noqa: BLE001 - handler errors become job failures
            queue.fail(conn, int(job["id"]), str(exc), retry=True)
            logger.warning("job failed", extra={"job_id": job["id"], "error": str(exc)})
        finally:
            self._hb_stop.set()
            if self._hb_thread is not None:
                self._hb_thread.join(timeout=1.0)
                self._hb_thread = None
            self._current_job_id = None

    def _heartbeat_loop(self, conn: sqlite3.Connection) -> None:
        """Refresh heartbeat_at for the current job until it finishes."""
        job_id = self._current_job_id
        if job_id is None:
            return
        while not self._hb_stop.wait(_HEARTBEAT_INTERVAL_S):
            try:
                queue.heartbeat(conn, job_id)
            except sqlite3.Error:  # pragma: no cover - defensive
                return


def wait_for_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    timeout_s: float = 10.0,
    poll_s: float = 0.05,
    is_final: Callable[[str], bool] | None = None,
) -> dict:
    """Test helper: poll a job until it reaches a terminal status."""
    final = is_final or (lambda s: s in ("succeeded", "failed", "cancelled"))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = queue.get_job(conn, job_id)
        if job and final(str(job["status"])):
            return job
        time.sleep(poll_s)
    job = queue.get_job(conn, job_id)
    raise TimeoutError(
        f"job {job_id} did not finish within {timeout_s}s "
        f"(status={job['status'] if job else 'missing'})"
    )
