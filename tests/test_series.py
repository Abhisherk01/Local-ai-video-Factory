"""Series outline handlers: dedupe acceptance, fallback gate, model path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from laf.db import connect, ensure_schema
from laf.jobs import queue
from laf.jobs.handlers import (
    HandlerContext,
    NonRetryable,
    handle_series_outline_fallback,
    handle_series_outline_gen,
)
from laf.series import (
    create_series,
    get_series,
    list_series_episodes,
)
from tests.test_storyboard import _FakeOllamaJSON  # reusable fake daemon

import http.server
import threading

# Re-import pytest fixture machinery: reuse the fake_ollama fixture from
# test_storyboard by re-declaring it here (fixtures do not cross modules
# without conftest; keeping the test servers explicit is simpler).
@pytest.fixture()
def fake_ollama(monkeypatch):
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllamaJSON)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LAF_OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
    _FakeOllamaJSON.seen_bodies = []
    yield _FakeOllamaJSON
    server.shutdown()


@pytest.fixture()
def env(tmp_path: Path):
    conn = connect(tmp_path / "laf.db")
    ensure_schema(conn)
    ctx = HandlerContext(
        conn=conn, data_dir=tmp_path / "data", models_dir=tmp_path / "models"
    )
    yield ctx
    conn.close()


def _job(ctx, job_type, payload):
    queue.enqueue(ctx.conn, job_type, payload=payload)
    return queue.claim_next(ctx.conn, worker_id="w")


def test_gate_fallback_outline_of_20_all_accepted_and_linked(env) -> None:
    """Roadmap phase-4 gate: a 20-episode sample outline passes duplicate
    detection - all 20 become draft episodes linked to the series."""
    series = create_series(
        env.conn, name="Sourdough series", premise="sourdough baking", requested_count=20
    )
    job = _job(env, "series_outline_fallback", {"series_id": series["id"]})
    result = handle_series_outline_fallback(job["payload"], job, env)

    assert result["method"] == "fallback_angles"
    assert result["accepted"] == 20
    assert result["skipped"] == []
    eps = list_series_episodes(env.conn, series["id"])
    assert len(eps) == 20
    assert all(e["status"] == "draft" for e in eps)
    assert get_series(env.conn, series["id"])["method"] == "fallback_angles"


def test_second_identical_outline_is_all_duplicates_non_retryable(env) -> None:
    series = create_series(
        env.conn, name="S", premise="sourdough baking", requested_count=20
    )
    payload = {"series_id": series["id"]}
    job = _job(env, "series_outline_fallback", payload)
    handle_series_outline_fallback(job["payload"], job, env)

    job2 = _job(env, "series_outline_fallback", payload)
    with pytest.raises(NonRetryable, match="duplicates"):
        handle_series_outline_fallback(job2["payload"], job2, env)


def test_model_outline_is_accepted_and_labeled_local_ollama(
    env, fake_ollama
) -> None:
    series = create_series(
        env.conn, name="S", premise="urban beekeeping", requested_count=3
    )
    _FakeOllamaJSON.response_body = {
        "response": json.dumps(
            {
                "episodes": [
                    {"title": "Hive basics", "topic": "choosing your first hive body"},
                    {"title": "Swarm season", "topic": "preventing swarms in spring"},
                    {"title": "Honey harvest", "topic": "when and how to pull honey frames"},
                ]
            }
        ),
        "total_duration": 1,
    }
    job = _job(env, "series_outline_gen", {"series_id": series["id"]})
    result = handle_series_outline_gen(job["payload"], job, env)
    assert result["method"] == "local_ollama"
    assert result["accepted"] == 3
    assert len(list_series_episodes(env.conn, series["id"])) == 3


def test_model_outline_dedupe_skips_in_batch_duplicates(env, fake_ollama) -> None:
    series = create_series(
        env.conn, name="S", premise="coffee brewing", requested_count=3
    )
    _FakeOllamaJSON.response_body = {
        "response": json.dumps(
            {
                "episodes": [
                    {"title": "Grind size", "topic": "how grind size changes extraction"},
                    {"title": "Grind size again", "topic": "The grind size changes extraction!"},
                    {"title": "Water", "topic": "water temperature for delicate beans"},
                ]
            }
        ),
        "total_duration": 1,
    }
    job = _job(env, "series_outline_gen", {"series_id": series["id"]})
    result = handle_series_outline_gen(job["payload"], job, env)
    assert result["accepted"] == 2
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["title"] == "Grind size again"


def test_outline_into_deleted_series_is_non_retryable(env) -> None:
    payload = {"series_id": 424242}
    job = _job(env, "series_outline_fallback", payload)
    with pytest.raises(NonRetryable, match="disappeared mid-job"):
        handle_series_outline_fallback(job["payload"], job, env)


def test_model_outline_without_ollama_falls_back(env, monkeypatch) -> None:
    series = create_series(
        env.conn, name="S", premise="kite physics", requested_count=5
    )
    job = _job(
        env,
        "series_outline_gen",
        {"series_id": series["id"], "allow_fallback": True},
    )
    result = handle_series_outline_gen(job["payload"], job, env)
    assert result["method"] == "fallback_angles"
    assert result["reason"]  # honest: records WHY it fell back
    assert result["accepted"] == 5
