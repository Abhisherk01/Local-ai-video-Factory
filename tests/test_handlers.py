"""Handler behavior: honest fallbacks, real WAV output, prereq errors.

No network in this module: Ollama is (a) absent or (b) faked by a
local HTTP server, which is exactly the production contract.
"""

from __future__ import annotations

import http.server
import json
import threading
import wave
from pathlib import Path

import pytest

from laf.db import connect, ensure_schema
from laf.episodes import create_episode, get_episode
from laf.jobs import queue
from laf.jobs.handlers import HandlerContext, known_types
from laf.jobs.handlers import handle_script_fallback, handle_script_gen
from laf.jobs.handlers import looks_like_meta_text
from laf.jobs.handlers import handle_tts_fallback, handle_tts_render
from laf.jobs.handlers import PrereqMissing
from laf.episodes import set_episode_script


@pytest.fixture()
def env(tmp_path: Path):
    conn = connect(tmp_path / "laf.db")
    ensure_schema(conn)
    ctx = HandlerContext(
        conn=conn, data_dir=tmp_path / "data", models_dir=tmp_path / "models"
    )
    yield ctx
    conn.close()


def _job(ctx, job_type="script_gen", episode_id=None):
    job, _created = queue.enqueue(
        ctx.conn, job_type, payload={}, episode_id=episode_id
    )
    return queue.claim_next(ctx.conn, worker_id="w")


def test_known_types_cover_phases_3_and_4() -> None:
    assert known_types() == [
        "script_fallback",
        "script_gen",
        "series_outline_fallback",
        "series_outline_gen",
        "storyboard_fallback",
        "storyboard_gen",
        "tts_fallback",
        "tts_render",
        "video_render",
    ]


def test_script_fallback_writes_template_and_scripts_episode(env) -> None:
    ep = create_episode(env.conn, title="T", topic="sourdough starters")
    job = _job(env, "script_fallback", episode_id=ep["id"])
    result = handle_script_fallback({"topic": ep["topic"]}, job, env)
    assert result["method"] == "fallback_template"
    updated = get_episode(env.conn, ep["id"])
    assert updated["status"] == "scripted"
    assert updated["script_method"] == "fallback_template"
    assert "sourdough starters" in updated["script_text"]


def test_script_gen_without_ollama_fails_with_prereq(env) -> None:
    job = _job(env, "script_gen")
    with pytest.raises(PrereqMissing, match="ollama_unavailable"):
        handle_script_gen({"topic": "x"}, job, env)


def test_script_gen_without_ollama_uses_fallback_when_allowed(env) -> None:
    ep = create_episode(env.conn, title="T", topic="kite physics")
    job = _job(env, "script_gen", episode_id=ep["id"])
    result = handle_script_gen({"topic": "kite physics", "allow_fallback": True}, job, env)
    assert result["method"] == "fallback_template"
    assert result["reason"]  # honest: records WHY it fell back


class _FakeOllama(http.server.BaseHTTPRequestHandler):
    seen_bodies: list = []  # class-level: handler instances are per-request

    def do_GET(self):  # noqa: N802 - stdlib contract
        body = json.dumps({"models": [{"name": "qwen3:4b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        type(self).seen_bodies.append(json.loads(self.rfile.read(length)))
        raw = (
            "<think>internal reasoning must never leak</think>"
            '{"hook": "Hook: line one.", "body": ["Point one."], '
            '"cta": "Follow for more."}'
        )
        body = json.dumps({"response": raw, "total_duration": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture()
def fake_ollama():
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    _FakeOllama.seen_bodies = []
    yield url
    server.shutdown()


def test_script_gen_with_ollama_strips_thinking(env, fake_ollama, monkeypatch) -> None:
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_ollama)
    ep = create_episode(env.conn, title="T", topic="urban beekeeping")
    job = _job(env, "script_gen", episode_id=ep["id"])
    result = handle_script_gen({"topic": ep["topic"]}, job, env)
    assert result["method"] == "local_ollama"
    assert result["model"] == "qwen3:4b"
    assert result["thinking_stripped"] is True
    # Pin the bounded-generation contract: narration must cap output
    # tokens. Job #34's num_predict=-1 let qwen3 fill the whole context
    # window and blind-timeout the backend three times in a row.
    body = _FakeOllama.seen_bodies[0]
    # 0.4.3: narration is grammar-constrained JSON (the storyboard/series
    # mechanism) - the daemon may only emit grammar-valid JSON tokens.
    assert body["format"] == "json"
    assert body["options"]["num_predict"] == 512
    assert body["think"] is False
    # 0.4.2: attempt 1 pins a compliance-first sampler; the ladder is
    # pinned separately below.
    assert body["options"]["temperature"] == 0.6
    assert body["options"]["top_p"] == 0.9
    stored = get_episode(env.conn, ep["id"])
    assert "internal reasoning" not in stored["script_text"]
    assert "Hook: line one." in stored["script_text"]
    assert "Follow for more." in stored["script_text"]


def test_script_gen_into_deleted_episode_is_non_retryable(
    env, fake_ollama, monkeypatch
) -> None:
    """Phase-3 field lesson: a vanished store target must not burn the
    remaining attempts (and another full generation) on a sure failure."""
    from laf.jobs.handlers import NonRetryable
    from laf.episodes import delete_episode

    monkeypatch.setenv("LAF_OLLAMA_URL", fake_ollama)
    ep = create_episode(env.conn, title="T", topic="x")
    job = _job(env, "script_gen", episode_id=ep["id"])
    delete_episode(env.conn, ep["id"])  # the mid-job disappearance
    with pytest.raises(NonRetryable, match="disappeared mid-job"):
        handle_script_gen({"topic": "x"}, job, env)


class _MetaOllama(_FakeOllama):
    """Same daemon, but the JSON string values carry planning chatter -
    the 0.4.3 failure class: under grammar-constrained decoding prose
    openers cannot LEAD the output, but they can still ride inside the
    string values. The 6a.2 guard must catch the assembled narration."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        raw = json.dumps(
            {
                "hook": "Okay, the user wants me to write a narration script.",
                "body": ["We are writing the structure now."],
                "cta": "Follow for more.",
            }
        )
        body = json.dumps({"response": raw, "total_duration": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_meta_ollama():
    server = http.server.HTTPServer(("127.0.0.1", 0), _MetaOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    yield url
    server.shutdown()


class _BadJsonOllama(_FakeOllama):
    """No JSON object at all - the grammar ask was ignored (e.g. an old
    daemon without format support). Must fail retryable, store nothing."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        raw = "A perfectly plain prose reply about the topic with no braces."
        body = json.dumps({"response": raw, "total_duration": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def fake_bad_json_ollama():
    server = http.server.HTTPServer(("127.0.0.1", 0), _BadJsonOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    yield url
    server.shutdown()


def test_looks_like_meta_text_flags_observed_heads() -> None:
    heads = [
        "We are writing a 60-second vertical video narration script.",
        "Okay, the user wants me to write a narration script.",
        "I need to follow their exact structure and word budget.",
        "Below is the script you asked for.",
        "As requested, here is the narration.",
    ]
    for head in heads:
        assert looks_like_meta_text(head), head


def test_looks_like_meta_text_passes_clean_hooks() -> None:
    clean = [
        "Butterflies taste with their feet.",
        "Here is why birds build nests the way they do.",
        "Hook: everything you know about coffee is about to get simpler.",
        "Mud puddles are a butterfly supper club.\nThey land and drink.",
    ]
    for hook in clean:
        assert not looks_like_meta_text(hook), hook


def test_script_gen_meta_chatter_is_retryable_not_stored(
    env, fake_meta_ollama, monkeypatch
) -> None:
    """Phase 6a.2: planning chatter must never be stored as narration.
    The handler raises a retryable error; the queue re-rolls the model."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_meta_ollama)
    ep = create_episode(env.conn, title="T", topic="x")
    job = _job(env, "script_gen", episode_id=ep["id"])
    with pytest.raises(RuntimeError, match="meta/bloated script text"):
        handle_script_gen({"topic": "x"}, job, env)
    stored = get_episode(env.conn, ep["id"])
    assert stored["script_text"] in (None, "")
    assert stored["status"] == "draft"


def test_meta_rejection_error_carries_head_snippet(
    env, fake_meta_ollama, monkeypatch
) -> None:
    """0.4.2 diagnosability: a field rejection must self-describe. Job
    #39's error showed only counts, so the actual chatter shape stayed
    unknown; the error now carries the opening of the rejected text."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_meta_ollama)
    ep = create_episode(env.conn, title="T", topic="x")
    job = _job(env, "script_gen", episode_id=ep["id"])
    with pytest.raises(RuntimeError, match="head: 'Okay, the user wants"):
        handle_script_gen({"topic": "x"}, job, env)


def test_script_gen_attempts_vary_temperature(
    env, fake_ollama, monkeypatch
) -> None:
    """0.4.2: identical retries are correlated retries - #39 went 0/3 on
    the same prompt + params. Attempts must re-roll the sampler."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_ollama)
    ep = create_episode(env.conn, title="T", topic="urban beekeeping")
    temps = []
    for attempt in (1, 2, 3):
        _FakeOllama.seen_bodies = []
        job = dict(_job(env, "script_gen", episode_id=ep["id"]))
        job["attempts"] = attempt
        handle_script_gen({"topic": ep["topic"]}, job, env)
        temps.append(_FakeOllama.seen_bodies[0]["options"]["temperature"])
    assert temps == [0.6, 1.0, 0.3]


def test_we_are_writing_mid_script_is_not_meta() -> None:
    """0.4.2 precision: "we are writing" is head-only now. A narration
    sentence using the phrase inside the first 400 chars must not burn a
    whole job (a false positive went 0/3 in #39)."""
    text = (
        "Every camera you have owned had one ancestor.\n"
        "For a century we are writing light onto film, glass, silicon.\n"
        "Follow for more."
    )
    assert not looks_like_meta_text(text)


def test_script_json_invalid_is_retried_not_stored(
    env, fake_bad_json_ollama, monkeypatch
) -> None:
    """0.4.3: a daemon that ignores format:json (or a model that answers
    in prose anyway) must produce a retryable failure and store nothing."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_bad_json_ollama)
    ep = create_episode(env.conn, title="T", topic="camera evolution")
    job = _job(env, "script_gen", episode_id=ep["id"])
    with pytest.raises(RuntimeError, match="no JSON object"):
        handle_script_gen({"topic": "camera evolution"}, job, env)
    stored = get_episode(env.conn, ep["id"])
    assert stored["script_text"] in (None, "")
    assert stored["status"] == "draft"


def test_tts_fallback_writes_a_real_playable_wav(env) -> None:
    ep = create_episode(env.conn, title="T", topic="t")
    job = _job(env, "tts_fallback", episode_id=ep["id"])
    result = handle_tts_fallback({"text": "ignored-by-fallback"}, job, env)
    assert result["method"] == "fallback_tone"
    out = Path(result["path"])
    assert out.exists() and result["bytes"] > 44
    with wave.open(str(out), "rb") as wav:
        assert wav.getframerate() == 22050
        assert wav.getnframes() == int(22050 * 2.0)
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1


def test_tts_render_without_piper_fails(env) -> None:
    ep = create_episode(env.conn, title="T", topic="t")
    set_episode_script(env.conn, ep["id"], script_text="narration", script_method="fallback_template")
    job = _job(env, "tts_render", episode_id=ep["id"])
    with pytest.raises(PrereqMissing, match="piper_unavailable"):
        handle_tts_render({}, job, env)


def test_tts_render_without_piper_falls_back_when_allowed(env) -> None:
    ep = create_episode(env.conn, title="T", topic="t")
    set_episode_script(env.conn, ep["id"], script_text="narration", script_method="fallback_template")
    job = _job(env, "tts_render", episode_id=ep["id"])
    result = handle_tts_render({"allow_fallback": True}, job, env)
    assert result["method"] == "fallback_tone"


def test_tts_render_requires_script_or_text(env) -> None:
    ep = create_episode(env.conn, title="T", topic="unscripted")
    job = _job(env, "tts_fallback", episode_id=ep["id"])
    with pytest.raises(RuntimeError, match="no text"):
        handle_tts_fallback({}, job, env)
