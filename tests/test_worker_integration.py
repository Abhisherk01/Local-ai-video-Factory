"""Worker integration: real thread, real handlers, real db file.

Also covers the crash-recovery story the roadmap demands: a backend
kill mid-job loses nothing - the next boot reclaims the row.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laf.api.main import create_app
from laf.db import connect
from laf.jobs.worker import Worker, wait_for_job
from tests.conftest import TEST_TOKEN


@pytest.fixture()
def worker_client(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "data",
        token=TEST_TOKEN,
        worker_enabled=True,
    )
    with TestClient(app) as c:
        c.headers.update({"X-LAF-Token": TEST_TOKEN})
        yield c


def _post(client, path, json=None):
    return client.post(path, json=json, headers={"X-LAF-Token": TEST_TOKEN})


def test_worker_processes_script_fallback_end_to_end(
    worker_client, tmp_path: Path
) -> None:
    ep = _post(
        worker_client, "/api/v1/episodes", {"title": "E2E", "topic": "paper boats"}
    ).json()["episode"]
    job = _post(
        worker_client, f"/api/v1/episodes/{ep['id']}/script", {"mode": "template"}
    ).json()["job"]

    conn = connect(tmp_path / "data" / "laf.db")
    try:
        done = wait_for_job(conn, int(job["id"]), timeout_s=10.0)
        assert done["status"] == "succeeded"
        assert done["result"]["method"] == "fallback_template"

        ep_now = worker_client.get(
            f"/api/v1/episodes/{ep['id']}", headers={"X-LAF-Token": TEST_TOKEN}
        ).json()["episode"]
        assert ep_now["status"] == "scripted"
        assert "paper boats" in ep_now["script_text"]
    finally:
        conn.close()


def test_worker_reports_running_in_stats(worker_client) -> None:
    stats = worker_client.get(
        "/api/v1/jobs/stats", headers={"X-LAF-Token": TEST_TOKEN}
    ).json()
    assert stats["worker"]["running"] is True
    adapters = worker_client.get(
        "/api/v1/adapters", headers={"X-LAF-Token": TEST_TOKEN}
    ).json()
    assert adapters["worker"]["running"] is True


def test_stale_running_job_is_reclaimed_on_next_worker_start(tmp_path: Path) -> None:
    """Simulate a crash: a 'running' row with an ancient heartbeat is
    left in the db; a freshly started worker must reclaim it, run the
    handler, and finish the job - no manual cleanup, no lost work."""
    from laf.jobs import queue

    data_dir = tmp_path / "data"
    db_path = data_dir / "laf.db"
    conn = connect(db_path)
    from laf.db import ensure_schema

    ensure_schema(conn)
    job, _ = queue.enqueue(conn, "script_fallback", payload={"topic": "crash test"})
    conn.execute(
        """
        UPDATE jobs SET status = 'running', worker_id = 'dead-worker',
               started_at = '2020-01-01T00:00:00.000Z',
               heartbeat_at = '2020-01-01T00:00:00.000Z', attempts = 1
        WHERE id = ?
        """,
        (job["id"],),
    )
    conn.close()

    worker = Worker(
        db_path,
        data_dir=data_dir,
        models_dir=tmp_path / "models",
        stale_after_s=120.0,
    )
    worker.start()
    try:
        conn = connect(db_path)
        try:
            done = wait_for_job(conn, int(job["id"]), timeout_s=10.0)
            assert done["status"] == "succeeded"
            assert done["attempts"] == 2  # reclaim counts as the second attempt
        finally:
            conn.close()
    finally:
        worker.stop()


def test_stop_is_idempotent_and_fast(tmp_path: Path) -> None:
    worker = Worker(
        tmp_path / "laf.db",
        data_dir=tmp_path,
        models_dir=tmp_path,
        poll_interval_s=0.05,
    )
    worker.start()
    assert worker.is_alive()
    started = time.monotonic()
    worker.stop()
    worker.stop()  # second call must not raise
    assert time.monotonic() - started < 3.0
    assert not worker.is_alive()


def test_non_retryable_handler_error_fails_immediately(tmp_path: Path) -> None:
    """Deterministic failures must not burn their remaining attempts:
    a NonRetryable error ends the job on attempt 1."""
    from laf.jobs import queue
    from laf.jobs.handlers import HandlerContext, NonRetryable

    data_dir = tmp_path / "data"
    db_path = data_dir / "laf.db"
    conn = connect(db_path)
    from laf.db import ensure_schema

    ensure_schema(conn)
    job, _ = queue.enqueue(conn, "doomed", payload={})
    conn.close()

    def doomed(payload: dict, job: dict, ctx: HandlerContext) -> dict:
        raise NonRetryable("store target gone - retrying cannot fix it")

    worker = Worker(
        db_path,
        data_dir=data_dir,
        models_dir=tmp_path / "models",
        poll_interval_s=0.05,
        handlers={"doomed": doomed},
    )
    worker.start()
    try:
        conn = connect(db_path)
        try:
            done = wait_for_job(conn, int(job["id"]), timeout_s=10.0)
            assert done["status"] == "failed"
            assert done["attempts"] == 1
            assert done["error"].startswith("non_retryable:")
            assert "store target gone" in done["error"]
        finally:
            conn.close()
    finally:
        worker.stop()
