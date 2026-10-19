"""Durable job queue operations on SQLite (ADR-009).

Design decisions:
- The queue lives in the `jobs` table, not in memory: killing the
  backend mid-run loses nothing. Restart resumes queued work.
- Claims are atomic: BEGIN IMMEDIATE serializes writers (busy_timeout
  covers contention), so two claims can never hand out the same job.
- GPU jobs are serialized (GPU concurrency = 1, ADR-003): a gpu job is
  only claimable when no other gpu job is running. Non-gpu jobs are
  never blocked by gpu jobs.
- Retries use exponential backoff via run_after; attempts counts
  executions. A job exhausts max_attempts -> status 'failed'.
- Crash recovery: running jobs whose heartbeat went stale are requeued
  (or failed if attempts are exhausted) by reclaim_stale().
- Idempotency: enqueue with the same idempotency_key returns the
  existing job instead of creating a duplicate (client retries, UI
  double-clicks).

All timestamps are ISO-8601 UTC strings in the same format the SQL
defaults produce, so lexicographic comparison is correct.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

# Backoff for automatic retries: attempts=1 -> ~2 s, 2 -> ~8 s, 3 -> ~32 s.
_BACKOFF_BASE_S = 2.0


def iso_utc(offset_s: float = 0.0) -> str:
    """ISO-8601 UTC timestamp with millisecond precision (+ optional offset)."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_s)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a jobs row to a dict, decoding the JSON columns."""

    def _load(field: str) -> Any:
        raw = row[field]
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw  # never lie: surface malformed JSON as-is

    job = dict(row)
    job["payload"] = _load("payload")
    job["result"] = _load("result")
    job["gpu"] = bool(job["gpu"])
    return job


def row_to_episode(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


# ---------------------------------------------------------------------------
# Jobs: enqueue / claim / complete / fail / cancel / reclaim
# ---------------------------------------------------------------------------


def enqueue(
    conn: sqlite3.Connection,
    job_type: str,
    *,
    payload: dict[str, Any] | None = None,
    episode_id: int | None = None,
    priority: int = 100,
    gpu: bool = False,
    max_attempts: int = 3,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert a queued job. Returns (job, created).

    With an idempotency_key that already exists, the existing job is
    returned unchanged and created=False - no duplicate is inserted.
    """
    try:
        cur = conn.execute(
            """
            INSERT INTO jobs (type, payload, episode_id, priority, gpu,
                              max_attempts, idempotency_key, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')
            """,
            (
                job_type,
                json.dumps(payload or {}, ensure_ascii=False),
                episode_id,
                int(priority),
                1 if gpu else 0,
                int(max_attempts),
                idempotency_key,
            ),
        )
    except sqlite3.IntegrityError:
        if not idempotency_key:
            raise
        row = conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise
        return row_to_job(row), False
    return get_job(conn, int(cur.lastrowid)), True


def claim_next(
    conn: sqlite3.Connection,
    *,
    worker_id: str,
    kinds: set[str] | None = None,
) -> dict[str, Any] | None:
    """Atomically claim the highest-priority eligible queued job.

    Eligibility: status='queued', run_after due, type in kinds (when
    given), and - for gpu jobs - no other gpu job currently running.
    Returns the freshly claimed job (status='running') or None.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'queued' AND (run_after IS NULL OR run_after <= ?)
            ORDER BY priority ASC, id ASC
            """,
            (iso_utc(),),
        ).fetchall()
        chosen: sqlite3.Row | None = None
        for row in rows:
            if kinds is not None and row["type"] not in kinds:
                continue
            if row["gpu"]:
                busy = conn.execute(
                    "SELECT 1 FROM jobs WHERE status = 'running' AND gpu = 1 LIMIT 1"
                ).fetchone()
                if busy:
                    continue  # GPU concurrency = 1: skip, try a cpu job
            chosen = row
            break
        if chosen is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            """
            UPDATE jobs
            SET status = 'running', worker_id = ?, heartbeat_at = ?,
                started_at = COALESCE(started_at, ?), attempts = attempts + 1
            WHERE id = ?
            """,
            (worker_id, iso_utc(), iso_utc(), chosen["id"]),
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.rollback()
        raise
    return get_job(conn, int(chosen["id"]))


def heartbeat(conn: sqlite3.Connection, job_id: int) -> None:
    """Refresh the liveness marker of a running job."""
    conn.execute(
        "UPDATE jobs SET heartbeat_at = ? WHERE id = ? AND status = 'running'",
        (iso_utc(), int(job_id)),
    )


def complete(
    conn: sqlite3.Connection, job_id: int, result: dict[str, Any] | None
) -> dict[str, Any]:
    """Mark a job succeeded with its result payload."""
    conn.execute(
        """
        UPDATE jobs SET status = 'succeeded', result = ?, error = NULL,
                        finished_at = ?, heartbeat_at = NULL
        WHERE id = ?
        """,
        (json.dumps(result or {}, ensure_ascii=False), iso_utc(), int(job_id)),
    )
    return get_job(conn, int(job_id))  # type: ignore[arg-type]


def fail(
    conn: sqlite3.Connection,
    job_id: int,
    error: str,
    *,
    retry: bool = True,
) -> dict[str, Any]:
    """Record a failure; requeue with backoff while attempts remain.

    retry=False (e.g. missing prerequisite) marks the job failed
    immediately - retrying cannot fix an absent Ollama/Piper install.
    """
    row = conn.execute(
        "SELECT attempts, max_attempts FROM jobs WHERE id = ?", (int(job_id),)
    ).fetchone()
    will_retry = (
        bool(retry)
        and row is not None
        and int(row["attempts"]) < int(row["max_attempts"])
    )
    if will_retry:
        delay = _BACKOFF_BASE_S ** (int(row["attempts"]) + 1)
        conn.execute(
            """
            UPDATE jobs SET status = 'queued', error = ?, run_after = ?,
                            finished_at = NULL, heartbeat_at = NULL
            WHERE id = ?
            """,
            (error, iso_utc(delay), int(job_id)),
        )
    else:
        conn.execute(
            """
            UPDATE jobs SET status = 'failed', error = ?, finished_at = ?,
                            heartbeat_at = NULL
            WHERE id = ?
            """,
            (error, iso_utc(), int(job_id)),
        )
    return get_job(conn, int(job_id))  # type: ignore[arg-type]


def cancel(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    """Cancel a queued job. Running jobs are deliberately not touched
    (Phase 3 has no cooperative cancellation inside handlers; Phase 8
    adds it). Returns the updated job, or None if it cannot cancel."""
    row = get_job(conn, int(job_id))
    if row is None or row["status"] != "queued":
        return None
    conn.execute(
        """
        UPDATE jobs SET status = 'cancelled', finished_at = ?
        WHERE id = ? AND status = 'queued'
        """,
        (iso_utc(), int(job_id)),
    )
    return get_job(conn, int(job_id))


def reclaim_stale(
    conn: sqlite3.Connection, *, stale_after_s: float = 120.0
) -> list[dict[str, Any]]:
    """Requeue (or fail) running jobs whose heartbeat went stale.

    This is the crash-recovery path: a backend killed mid-job leaves
    rows in 'running'; on the next boot the worker reclaims them. Jobs
    whose attempts are exhausted are marked failed with an honest
    error instead of being retried forever.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_s)
    rows = conn.execute("SELECT * FROM jobs WHERE status = 'running'").fetchall()
    reclaimed: list[dict[str, Any]] = []
    for row in rows:
        marker = _parse_iso(row["heartbeat_at"]) or _parse_iso(row["started_at"])
        if marker is not None and marker > cutoff:
            continue  # heartbeat fresh - its worker is alive
        job = fail(
            conn, int(row["id"]), "worker lost heartbeat; job reclaimed", retry=True
        )
        reclaimed.append(job)
    return reclaimed


# ---------------------------------------------------------------------------
# Jobs: reads
# ---------------------------------------------------------------------------


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    return row_to_job(row) if row else None


def list_jobs(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    episode_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM jobs"
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        if status not in JOB_STATUSES:
            raise ValueError(f"invalid status filter: {status}")
        clauses.append("status = ?")
        params.append(status)
    if episode_id is not None:
        clauses.append("episode_id = ?")
        params.append(int(episode_id))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return [row_to_job(row) for row in conn.execute(sql, params).fetchall()]


def job_stats(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {status: 0 for status in JOB_STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
        counts[str(row[0])] = int(row[1])
    return counts
