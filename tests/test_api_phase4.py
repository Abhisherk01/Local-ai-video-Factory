"""Phase 4 API surface: styles registry, storyboard endpoints, series."""

from __future__ import annotations

from pathlib import Path

from laf.db import connect
from laf.episodes import set_episode_script
from tests.conftest import TEST_TOKEN


def _get(client, path):
    return client.get(path, headers={"X-LAF-Token": TEST_TOKEN})


def _post(client, path, json=None):
    return client.post(path, json=json, headers={"X-LAF-Token": TEST_TOKEN})


def _delete(client, path):
    return client.delete(path, headers={"X-LAF-Token": TEST_TOKEN})


# ---------------------------------------------------------------------------
# styles
# ---------------------------------------------------------------------------


def test_styles_list_seeds_six_builtins(client) -> None:
    body = _get(client, "/api/v1/styles").json()
    slugs = [s["slug"] for s in body["styles"]]
    assert len(body["styles"]) == 6
    assert "dark_cinematic" in slugs and "minimal_mono" in slugs
    assert all(s["is_builtin"] for s in body["styles"])


def test_create_custom_style_and_duplicate_conflict(client) -> None:
    ok = _post(
        client,
        "/api/v1/styles",
        {"slug": "neon_noir", "name": "Neon Noir", "prompt_prefix": "neon lights, rainy streets, "},
    )
    assert ok.status_code == 201
    dup = _post(
        client,
        "/api/v1/styles",
        {"slug": "neon_noir", "name": "Again"},
    )
    assert dup.status_code == 409
    bad = _post(
        client,
        "/api/v1/styles",
        {"slug": "Bad Slug!", "name": "X"},
    )
    assert bad.status_code == 422  # pydantic pattern guard


def test_builtin_styles_cannot_be_deleted_custom_ones_can(client) -> None:
    assert _delete(client, "/api/v1/styles/dark_cinematic").status_code == 400
    assert _delete(client, "/api/v1/styles/does_not_exist").status_code == 404
    _post(client, "/api/v1/styles", {"slug": "temp_style", "name": "Temp"})
    assert _delete(client, "/api/v1/styles/temp_style").status_code == 200


# ---------------------------------------------------------------------------
# storyboard endpoints
# ---------------------------------------------------------------------------


def _scripted_episode(client, tmp_path: Path) -> dict:
    ep = _post(
        client,
        "/api/v1/episodes",
        {"title": "E", "topic": "sourdough science"},
    ).json()["episode"]
    conn = connect(tmp_path / "data" / "laf.db")
    try:
        set_episode_script(
            conn,
            ep["id"],
            script_text="Hook line. Body one. Body two. Body three. CTA line.",
            script_method="fallback_template",
        )
    finally:
        conn.close()
    return ep


def test_storyboard_enqueue_requires_a_script(client, tmp_path: Path) -> None:
    ep = _post(
        client, "/api/v1/episodes", {"title": "Draft", "topic": "t"}
    ).json()["episode"]
    assert (
        _post(client, f"/api/v1/episodes/{ep['id']}/storyboard", {}).status_code
        == 400
    )


def test_storyboard_enqueue_validates_style_and_mode(client, tmp_path: Path) -> None:
    ep = _scripted_episode(client, tmp_path)
    bad_style = _post(
        client,
        f"/api/v1/episodes/{ep['id']}/storyboard",
        {"style_slug": "missing_style"},
    )
    assert bad_style.status_code == 400
    ok = _post(
        client,
        f"/api/v1/episodes/{ep['id']}/storyboard",
        {"style_slug": "dark_cinematic", "mode": "template"},
    )
    assert ok.status_code == 202
    assert ok.json()["job"]["type"] == "storyboard_fallback"
    # No worker in this fixture: nothing stored yet.
    body = _get(client, f"/api/v1/episodes/{ep['id']}/storyboard").json()
    assert body["storyboard"] is None
    assert _get(client, "/api/v1/episodes/999/storyboard").status_code == 404


# ---------------------------------------------------------------------------
# series endpoints
# ---------------------------------------------------------------------------


def test_series_create_lists_and_deletes(client) -> None:
    created = _post(
        client,
        "/api/v1/series",
        {"name": "Bee series", "premise": "urban beekeeping", "count": 5, "mode": "template"},
    )
    assert created.status_code == 202
    payload = created.json()
    assert payload["series"]["requested_count"] == 5
    assert payload["job"]["type"] == "series_outline_fallback"

    listed = _get(client, "/api/v1/series").json()["series"]
    assert listed[0]["episode_count"] == 0

    sid = payload["series"]["id"]
    one = _get(client, f"/api/v1/series/{sid}").json()
    assert one["series"]["id"] == sid and one["episodes"] == []

    assert _delete(client, f"/api/v1/series/{sid}").status_code == 200
    assert _get(client, f"/api/v1/series/{sid}").status_code == 404


def test_series_count_bounds_are_enforced(client) -> None:
    low = _post(
        client, "/api/v1/series", {"name": "S", "premise": "p", "count": 2}
    )
    assert low.status_code == 422
    high = _post(
        client, "/api/v1/series", {"name": "S", "premise": "p", "count": 31}
    )
    assert high.status_code == 422
