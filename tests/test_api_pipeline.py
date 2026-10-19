"""API tests: episodes, jobs, adapters endpoints (TestClient, no worker)."""

from __future__ import annotations

from tests.conftest import TEST_TOKEN


def _post(client, path, json=None):
    return client.post(path, json=json, headers={"X-LAF-Token": TEST_TOKEN})


def _get(client, path):
    return client.get(path, headers={"X-LAF-Token": TEST_TOKEN})


def _make_episode(client, title="Ep", topic=" Topic about tea ") -> dict:
    resp = _post(client, "/api/v1/episodes", {"title": title, "topic": topic})
    assert resp.status_code == 201
    return resp.json()["episode"]


# ---------------------------------------------------------------------------
# episodes
# ---------------------------------------------------------------------------


def test_create_and_get_episode(client) -> None:
    ep = _make_episode(client, title="First", topic="cold brew")
    assert ep["status"] == "draft" and ep["channel"] == "default"
    got = _get(client, f"/api/v1/episodes/{ep['id']}")
    assert got.status_code == 200 and got.json()["episode"]["title"] == "First"


def test_create_episode_validates_payload(client) -> None:
    assert _post(client, "/api/v1/episodes", {"title": "", "topic": "x"}).status_code == 422
    assert _post(client, "/api/v1/episodes", {"topic": "x"}).status_code == 422


def test_list_episodes_filters_by_status(client, tmp_path) -> None:
    _make_episode(client, title="A")
    ep = _make_episode(client, title="B")
    # Transition B directly (the quiet fixture has no worker by design;
    # the draft->scripted transition via jobs is covered in the
    # worker-integration suite).
    from laf.db import connect
    from laf.episodes import set_episode_status

    conn = connect(tmp_path / "data" / "laf.db")
    try:
        set_episode_status(conn, ep["id"], "scripted")
    finally:
        conn.close()

    drafts = _get(client, "/api/v1/episodes?status=draft").json()["episodes"]
    scripted = _get(client, "/api/v1/episodes?status=scripted").json()["episodes"]
    assert [e["title"] for e in drafts] == ["A"]
    assert [e["title"] for e in scripted] == ["B"]
    assert _get(client, "/api/v1/episodes?status=bogus").status_code == 400


def test_get_missing_episode_404(client) -> None:
    assert _get(client, "/api/v1/episodes/999").status_code == 404


def test_delete_episode_keeps_job_history(client) -> None:
    ep = _make_episode(client)
    _post(client, f"/api/v1/episodes/{ep['id']}/script", {"mode": "template"})
    assert client.delete(
        f"/api/v1/episodes/{ep['id']}", headers={"X-LAF-Token": TEST_TOKEN}
    ).json()["deleted"] is True
    assert _get(client, f"/api/v1/episodes/{ep['id']}").status_code == 404
    jobs = _get(client, "/api/v1/jobs").json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["episode_id"] is None


def test_script_enqueue_modes_and_404(client) -> None:
    ep = _make_episode(client)
    resp = _post(client, f"/api/v1/episodes/{ep['id']}/script", {"mode": "auto"})
    assert resp.status_code == 202
    job = resp.json()["job"]
    assert job["type"] == "script_gen" and job["payload"]["allow_fallback"] is True

    resp = _post(client, f"/api/v1/episodes/{ep['id']}/script", {"mode": "template"})
    assert resp.json()["job"]["type"] == "script_fallback"

    assert (
        _post(client, "/api/v1/episodes/999/script", {"mode": "auto"}).status_code
        == 404
    )
    assert (
        _post(
            client, f"/api/v1/episodes/{ep['id']}/script", {"mode": "wizard"}
        ).status_code
        == 422
    )


def test_script_enqueue_idempotency(client) -> None:
    ep = _make_episode(client)
    body = {"mode": "auto", "idempotency_key": "ep:1:script"}
    first = _post(client, f"/api/v1/episodes/{ep['id']}/script", body).json()
    second = _post(client, f"/api/v1/episodes/{ep['id']}/script", body).json()
    assert first["created"] is True and second["created"] is False
    assert first["job"]["id"] == second["job"]["id"]


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def test_enqueue_unknown_type_400(client) -> None:
    resp = _post(client, "/api/v1/jobs", {"type": "render_final"})
    assert resp.status_code == 400 and "unknown job type" in resp.json()["detail"]


def test_enqueue_generic_job_and_fetch(client) -> None:
    resp = _post(
        client,
        "/api/v1/jobs",
        {"type": "tts_fallback", "payload": {"text": "hi"}, "gpu": False},
    )
    assert resp.status_code == 201
    job_id = resp.json()["job"]["id"]
    got = _get(client, f"/api/v1/jobs/{job_id}")
    assert got.json()["job"]["payload"] == {"text": "hi"}


def test_jobs_list_and_stats_shape(client) -> None:
    _post(client, "/api/v1/jobs", {"type": "script_fallback"})
    body = _get(client, "/api/v1/jobs").json()
    assert {"jobs", "stats"} <= set(body)
    assert body["stats"]["queued"] == 1
    stats = _get(client, "/api/v1/jobs/stats").json()
    assert stats["worker"]["running"] is False  # conftest client has no worker
    assert "script_gen" in stats["known_types"]


def test_stats_route_declared_before_param_route(client) -> None:
    # Regression: "/stats" must not be swallowed by "/{job_id}".
    assert _get(client, "/api/v1/jobs/stats").status_code == 200


def test_enqueue_job_for_missing_episode_404(client) -> None:
    resp = _post(client, "/api/v1/jobs", {"type": "script_gen", "episode_id": 424242})
    assert resp.status_code == 404


def test_cancel_queued_ok_running_conflict(client) -> None:
    job = _post(client, "/api/v1/jobs", {"type": "script_fallback"}).json()["job"]
    assert _post(client, f"/api/v1/jobs/{job['id']}/cancel").status_code == 200
    assert _post(client, f"/api/v1/jobs/{job['id']}/cancel").status_code == 409
    assert _post(client, "/api/v1/jobs/987654/cancel").status_code == 404


def test_invalid_status_filter_400(client) -> None:
    assert _get(client, "/api/v1/jobs?status=nope").status_code == 400


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------


def test_adapters_endpoint_probes_safely(client) -> None:
    resp = _get(client, "/api/v1/adapters")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["adapters"]) == {"ollama", "piper", "kokoro"}
    for probe in body["adapters"].values():
        assert {"name", "available", "detail"} <= set(probe)
    assert body["adapters"]["kokoro"]["extra"]["package_detected"] in (True, False)
    assert body["worker"]["running"] is False
