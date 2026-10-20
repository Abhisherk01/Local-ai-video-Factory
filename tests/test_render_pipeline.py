"""Phase 5 render pipeline: API guards + full worker end-to-end.

The e2e test drives the real worker through script_fallback ->
storyboard_fallback -> video_render with no model installed anywhere:
template script, deterministic scene split, tone audio. The only
external binary is ffmpeg/ffprobe (skipped when absent).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laf.api.main import create_app
from laf.db import connect
from laf.jobs.worker import wait_for_job
from tests.conftest import TEST_TOKEN

FFMPEG = shutil.which("ffmpeg")


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


def test_render_route_404_for_missing_episode(client) -> None:
    resp = _post(client, "/api/v1/episodes/9999/render", {"allow_fallback": True})
    assert resp.status_code == 404


def test_render_route_requires_storyboard(client) -> None:
    ep = _post(
        client, "/api/v1/episodes", {"title": "No SB", "topic": "t"}
    ).json()["episode"]
    resp = _post(
        client, f"/api/v1/episodes/{ep['id']}/render", {"allow_fallback": True}
    )
    assert resp.status_code == 400
    assert "Storyboard" in resp.json()["detail"]


def _make_storyboarded_episode(worker_client, tmp_path: Path) -> dict:
    ep = _post(
        worker_client,
        "/api/v1/episodes",
        {"title": "Render me", "topic": "paper boats"},
    ).json()["episode"]
    script_job = _post(
        worker_client, f"/api/v1/episodes/{ep['id']}/script", {"mode": "template"}
    ).json()["job"]
    conn = connect(tmp_path / "data" / "laf.db")
    try:
        assert wait_for_job(conn, int(script_job["id"]), timeout_s=10.0)[
            "status"
        ] == "succeeded"
    finally:
        conn.close()
    sb_job = _post(
        worker_client,
        f"/api/v1/episodes/{ep['id']}/storyboard",
        {"mode": "template", "style_slug": "warm_documentary"},
    ).json()["job"]
    conn = connect(tmp_path / "data" / "laf.db")
    try:
        assert wait_for_job(conn, int(sb_job["id"]), timeout_s=10.0)[
            "status"
        ] == "succeeded"
    finally:
        conn.close()
    return ep


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_worker_renders_storyboarded_episode_end_to_end(
    worker_client, tmp_path: Path
) -> None:
    ep = _make_storyboarded_episode(worker_client, tmp_path)

    render_job = _post(
        worker_client, f"/api/v1/episodes/{ep['id']}/render", {"allow_fallback": True}
    ).json()["job"]
    assert render_job["type"] == "video_render"

    conn = connect(tmp_path / "data" / "laf.db")
    try:
        done = wait_for_job(conn, int(render_job["id"]), timeout_s=90.0)
    finally:
        conn.close()
    assert done["status"] == "succeeded", done["error"]
    result = done["result"]
    assert result["method"] == "fallback_tone"  # no piper installed: honest tone
    assert result["qc"]["ok"] is True
    assert Path(result["path"]).exists()
    assert result["scene_count"] >= 2

    ep_now = worker_client.get(
        f"/api/v1/episodes/{ep['id']}", headers={"X-LAF-Token": TEST_TOKEN}
    ).json()["episode"]
    assert ep_now["status"] == "rendered"