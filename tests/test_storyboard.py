"""Storyboard handlers: deterministic split, model JSON, honest failures."""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from laf.db import connect, ensure_schema
from laf.episodes import create_episode, get_episode, set_episode_script
from laf.jobs import queue
from laf.jobs.handlers import (
    HandlerContext,
    NonRetryable,
    PrereqMissing,
    _scene_count,
    _split_narration,
    handle_storyboard_fallback,
    handle_storyboard_gen,
)
from laf.storyboards import get_storyboard


@pytest.fixture()
def env(tmp_path: Path):
    conn = connect(tmp_path / "laf.db")
    ensure_schema(conn)
    ctx = HandlerContext(
        conn=conn, data_dir=tmp_path / "data", models_dir=tmp_path / "models"
    )
    yield ctx
    conn.close()


def _job(ctx, job_type, episode_id):
    queue.enqueue(ctx.conn, job_type, payload={}, episode_id=episode_id)
    return queue.claim_next(ctx.conn, worker_id="w")


def _scripted(ctx, topic="sourdough science"):
    ep = create_episode(ctx.conn, title="T", topic=topic)
    set_episode_script(
        ctx.conn,
        ep["id"],
        script_text=(
            "Hook: your starter is lying to you. "
            "Flour is mostly starch, and starch is sugar waiting to happen. "
            "Yeast eats that sugar and burps carbon dioxide into the dough. "
            "The gluten net catches the gas, and the loaf rises. "
            "CTA: follow for the next bake."
        ),
        script_method="fallback_template",
    )
    return get_episode(ctx.conn, ep["id"])


def test_scene_count_clamps_to_three_through_eight() -> None:
    assert _scene_count("one two three") == 1  # one sentence caps it
    long = ". ".join(f"Sentence number {i} here" for i in range(12))
    assert 3 <= _scene_count(long) <= 8


def test_split_narration_conserves_every_sentence(env) -> None:
    script = "A one. B two. C three. D four. E five."
    slices = _split_narration(script, 3)
    assert len(slices) == 3
    assert " ".join(slices) == script  # nothing lost, nothing invented


def test_fallback_storyboard_scripts_episode_and_stores_scenes(env) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_fallback", ep["id"])
    result = handle_storyboard_fallback({"style_slug": "dark_cinematic"}, job, env)
    assert result["method"] == "fallback_split"
    assert result["scene_count"] >= 3

    stored = get_storyboard(env.conn, ep["id"])
    assert stored is not None
    assert stored["style_slug"] == "dark_cinematic"
    assert len(stored["scenes"]) == result["scene_count"]
    assert all(s["narration"] for s in stored["scenes"])
    assert all("dark cinematic" in s["visual_prompt"] for s in stored["scenes"])
    assert stored["total_duration_s"] > 0
    assert get_episode(env.conn, ep["id"])["status"] == "storyboarded"


def test_restoryboarding_replaces_the_previous_plan(env) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_fallback", ep["id"])
    handle_storyboard_fallback({"style_slug": "dark_cinematic"}, job, env)
    handle_storyboard_fallback({"style_slug": "minimal_mono"}, job, env)
    stored = get_storyboard(env.conn, ep["id"])
    assert stored["style_slug"] == "minimal_mono"
    count = env.conn.execute("SELECT COUNT(*) FROM storyboards").fetchone()[0]
    assert count == 1


def test_storyboard_without_script_is_non_retryable(env) -> None:
    ep = create_episode(env.conn, title="T", topic="unscripted")
    job = _job(env, "storyboard_gen", ep["id"])
    with pytest.raises(NonRetryable, match="no script yet"):
        handle_storyboard_gen({}, job, env)


def test_storyboard_with_unknown_style_is_non_retryable(env) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_gen", ep["id"])
    with pytest.raises(NonRetryable, match="not in the registry"):
        handle_storyboard_gen({"style_slug": "nope"}, job, env)


class _FakeOllamaJSON(http.server.BaseHTTPRequestHandler):
    """Fake daemon returning a canned /api/generate body."""

    response_body = {"response": "{}", "total_duration": 1}
    seen_bodies: list[dict] = []

    def do_GET(self):  # noqa: N802 - stdlib contract
        body = json.dumps({"models": [{"name": "qwen3:4b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        type(self).seen_bodies.append(json.loads(raw))
        body = json.dumps(type(self).response_body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture()
def fake_ollama(monkeypatch):
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllamaJSON)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LAF_OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
    _FakeOllamaJSON.seen_bodies = []
    yield _FakeOllamaJSON
    server.shutdown()


def test_storyboard_gen_parses_model_shots_and_stores(env, fake_ollama) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_gen", ep["id"])
    n = _scene_count(str(ep["script_text"]))
    fake_ollama.response_body = {
        "response": json.dumps(
            {"shots": [f"shot {i}: steam rising off the crust" for i in range(n)]}
        ),
        "total_duration": 1,
    }
    result = handle_storyboard_gen({}, job, env)
    assert result["method"] == "local_ollama"
    assert result["scene_count"] == n
    stored = get_storyboard(env.conn, ep["id"])
    assert "steam rising" in stored["scenes"][0]["visual_prompt"]
    # The request asked for thinking-off and a bounded context window:
    # 4096 halves KV-cache VRAM vs 8192 (GPU offload %), and num_predict
    # must be the bounded adapter default, never -1 (job #34 runaway).
    body = fake_ollama.seen_bodies[0]
    assert body["think"] is False
    assert body["options"]["num_ctx"] == 4096
    assert body["options"]["num_predict"] == 1536


def test_storyboard_gen_tolerates_markdown_fences(env, fake_ollama) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_gen", ep["id"])
    n = _scene_count(str(ep["script_text"]))
    inner = json.dumps({"shots": [f"close-up of crust {i}" for i in range(n)]})
    fake_ollama.response_body = {"response": f"```json\n{inner}\n```", "total_duration": 1}
    result = handle_storyboard_gen({}, job, env)
    assert result["method"] == "local_ollama"


def test_storyboard_gen_wrong_shot_count_is_retryable_failure(
    env, fake_ollama
) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_gen", ep["id"])
    fake_ollama.response_body = {
        "response": json.dumps({"shots": ["only one shot"]}),
        "total_duration": 1,
    }
    with pytest.raises(RuntimeError, match="expected"):
        handle_storyboard_gen({}, job, env)


def test_storyboard_gen_without_ollama_prereq_or_fallback(env, monkeypatch) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_gen", ep["id"])
    with pytest.raises(PrereqMissing, match="ollama_unavailable"):
        handle_storyboard_gen({"allow_fallback": False}, job, env)


def test_storyboard_gen_without_ollama_falls_back(env, monkeypatch) -> None:
    ep = _scripted(env)
    job = _job(env, "storyboard_gen", ep["id"])
    result = handle_storyboard_gen({"allow_fallback": True}, job, env)
    assert result["method"] == "fallback_split"
    assert result["reason"]  # honest: records WHY it fell back
