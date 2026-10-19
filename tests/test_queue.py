"""Queue mechanics: atomic claims, GPU serialization, retries, reclaim,
idempotency, cancel. These run against a real migrated SQLite file."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from laf.db import connect, ensure_schema
from laf.jobs import queue


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = connect(tmp_path / "laf.db")
    ensure_schema(c)
    yield c
    c.close()


def test_enqueue_returns_queued_job_with_decoded_payload(conn) -> None:
    job, created = queue.enqueue(conn, "script_gen", payload={"topic": "t"}, gpu=False)
    assert created and job["status"] == "queued" and job["payload"] == {"topic": "t"}
    assert job["attempts"] == 0 and job["gpu"] is False


def test_claim_is_fifo_within_priority_and_marks_running(conn) -> None:
    j_low, _ = queue.enqueue(conn, "script_gen", payload={}, priority=200)
    j_high, _ = queue.enqueue(conn, "script_gen", payload={}, priority=10)
    claimed = queue.claim_next(conn, worker_id="w1")
    assert claimed["id"] == j_high["id"] and claimed["status"] == "running"
    assert claimed["worker_id"] == "w1" and claimed["attempts"] == 1

    second = queue.claim_next(conn, worker_id="w1")
    assert second["id"] == j_low["id"]

    assert queue.claim_next(conn, worker_id="w1") is None


def test_claim_filters_by_kinds(conn) -> None:
    queue.enqueue(conn, "tts_render", payload={})
    claimed = queue.claim_next(conn, worker_id="w", kinds={"script_gen"})
    assert claimed is None
    claimed = queue.claim_next(conn, worker_id="w", kinds={"tts_render"})
    assert claimed is not None and claimed["type"] == "tts_render"


def test_gpu_jobs_never_run_concurrently_but_cpu_jobs_do(conn) -> None:
    gpu1, _ = queue.enqueue(conn, "tts_render", payload={}, gpu=True)
    running = queue.claim_next(conn, worker_id="w")
    assert running["id"] == gpu1["id"]

    gpu2, _ = queue.enqueue(conn, "tts_render", payload={}, gpu=True)
    cpu, _ = queue.enqueue(conn, "script_fallback", payload={}, gpu=False)
    # gpu2 must be skipped while gpu1 is running; cpu is claimable.
    next_job = queue.claim_next(conn, worker_id="w")
    assert next_job["id"] == cpu["id"]
    assert queue.claim_next(conn, worker_id="w") is None  # gpu2 blocked

    queue.complete(conn, int(gpu1["id"]), {"ok": True})
    freed = queue.claim_next(conn, worker_id="w")
    assert freed["id"] == gpu2["id"]


def test_complete_stores_result_and_finishes(conn) -> None:
    job, _ = queue.enqueue(conn, "script_fallback", payload={})
    claimed = queue.claim_next(conn, worker_id="w")
    done = queue.complete(conn, int(job["id"]), {"chars": 42})
    assert done["status"] == "succeeded" and done["result"] == {"chars": 42}
    assert done["finished_at"] and done["id"] == claimed["id"]


def test_fail_requeues_with_backoff_until_attempts_exhausted(conn) -> None:
    job, _ = queue.enqueue(conn, "script_gen", payload={}, max_attempts=2)

    first = queue.claim_next(conn, worker_id="w")  # attempts=1
    failed = queue.fail(conn, int(job["id"]), "boom")
    assert failed["status"] == "queued" and failed["error"] == "boom"
    assert failed["run_after"] is not None  # backoff gate set

    # Backoff in the future: not claimable yet.
    assert queue.claim_next(conn, worker_id="w") is None

    # Force due, second attempt exhausts max_attempts -> failed.
    conn.execute("UPDATE jobs SET run_after = NULL WHERE id = ?", (job["id"],))
    queue.claim_next(conn, worker_id="w")  # attempts=2
    final = queue.fail(conn, int(job["id"]), "boom again")
    assert final["status"] == "failed" and final["finished_at"]


def test_fail_without_retry_marks_failed_immediately(conn) -> None:
    job, _ = queue.enqueue(conn, "script_gen", payload={}, max_attempts=3)
    queue.claim_next(conn, worker_id="w")
    failed = queue.fail(conn, int(job["id"]), "prereq", retry=False)
    assert failed["status"] == "failed" and failed["attempts"] == 1


def test_reclaim_stale_requeues_lost_jobs_and_respects_fresh_heartbeats(conn) -> None:
    fresh, _ = queue.enqueue(conn, "script_gen", payload={})
    lost, _ = queue.enqueue(conn, "script_gen", payload={})
    queue.claim_next(conn, worker_id="w")  # claims `fresh` (lower id first)
    queue.claim_next(conn, worker_id="w")  # claims `lost`

    # fresh keeps a current heartbeat; lost gets a stale one.
    queue.heartbeat(conn, int(fresh["id"]))
    conn.execute(
        "UPDATE jobs SET heartbeat_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
        (lost["id"],),
    )

    reclaimed = queue.reclaim_stale(conn, stale_after_s=120.0)
    assert [j["id"] for j in reclaimed] == [lost["id"]]
    assert reclaimed[0]["status"] == "queued"
    assert queue.get_job(conn, int(fresh["id"]))["status"] == "running"


def test_reclaim_stale_fails_exhausted_jobs(conn) -> None:
    job, _ = queue.enqueue(conn, "script_gen", payload={}, max_attempts=1)
    queue.claim_next(conn, worker_id="w")
    conn.execute(
        "UPDATE jobs SET heartbeat_at = '2020-01-01T00:00:00.000Z' WHERE id = ?",
        (job["id"],),
    )
    reclaimed = queue.reclaim_stale(conn)
    assert reclaimed[0]["status"] == "failed"
    assert "heartbeat" in reclaimed[0]["error"]


def test_idempotency_key_returns_existing_job_without_duplicate(conn) -> None:
    key = "script:1:auto"
    first, created1 = queue.enqueue(conn, "script_gen", payload={}, idempotency_key=key)
    again, created2 = queue.enqueue(conn, "script_gen", payload={}, idempotency_key=key)
    assert created1 and not created2
    assert first["id"] == again["id"]
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_cancel_only_touches_queued_jobs(conn) -> None:
    job, _ = queue.enqueue(conn, "script_gen", payload={})
    cancelled = queue.cancel(conn, int(job["id"]))
    assert cancelled["status"] == "cancelled"
    assert queue.cancel(conn, int(job["id"])) is None  # already terminal

    running, _ = queue.enqueue(conn, "script_gen", payload={})
    queue.claim_next(conn, worker_id="w")
    assert queue.cancel(conn, int(running["id"])) is None
    assert queue.get_job(conn, int(running["id"]))["status"] == "running"


def test_job_stats_counts_by_status(conn) -> None:
    queue.enqueue(conn, "script_gen", payload={})
    queue.enqueue(conn, "script_gen", payload={})
    job3, _ = queue.enqueue(conn, "script_gen", payload={})
    queue.cancel(conn, int(job3["id"]))
    stats = queue.job_stats(conn)
    assert stats["queued"] == 2 and stats["cancelled"] == 1
    assert stats["running"] == 0 and stats["succeeded"] == 0


def test_list_jobs_filters(conn) -> None:
    queue.enqueue(conn, "script_gen", payload={})
    assert len(queue.list_jobs(conn)) == 1
    assert queue.list_jobs(conn, status="succeeded") == []
    with pytest.raises(ValueError):
        queue.list_jobs(conn, status="bogus")
