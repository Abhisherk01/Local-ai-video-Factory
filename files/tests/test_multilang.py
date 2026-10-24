"""0.4.10-multilang tests: language detection, prompt wiring, catalog
language metadata, route contract, and Devanagari caption support.

Self-contained on purpose: no `client` fixture, no network, no Ollama
(the language tests spin the same kind of local HTTP fake that
test_handlers.py uses). rev 3 pins the 0.4.3 JSON-contract
architecture: the English system prompt stays byte-identical to 0.4.8,
Hindi speaks the same JSON grammar with Devanagari values.
"""

from __future__ import annotations

import ast
import http.server
import json
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

from laf import voices
from laf.api.routes.episodes import ScriptRequest
from laf.db import connect, ensure_schema
from laf.episodes import create_episode, get_episode
from laf.jobs import handlers, queue
from laf.jobs.handlers import HandlerContext, handle_script_fallback, handle_script_gen
from laf.lang import (
    LANGUAGE_CODES,
    SCRIPT_SYSTEM_EN,
    SCRIPT_SYSTEM_HI,
    detect_language,
    language_directive,
    language_name,
    normalize_language,
)

# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


def test_detect_english_stays_default() -> None:
    assert detect_language("Making and preparing food in 60 seconds") == "en"
    assert detect_language("") == "en"
    assert detect_language(None) == "en"  # type: ignore[arg-type]


def test_detect_devanagari_topic_is_hindi() -> None:
    assert (
        detect_language("तितली के जीवन चक्र पर 60 सेकंड की वीडियो")
        == "hi"
    )


def test_detect_explicit_hints() -> None:
    assert detect_language("Write in Hindi please: life of a monarch") == "hi"
    assert detect_language("butterfly life cycle hindi mein banao") == "hi"
    assert detect_language("हिंदी में वीडियो बनाओ") == "hi"


def test_detect_mention_is_not_a_request() -> None:
    # A topic that merely names the language stays English.
    assert detect_language("Hindi cinema history from 1950s") == "en"
    assert detect_language("how hindi cinema changed india") == "en"


def test_normalize_language() -> None:
    assert normalize_language("hi") == "hi"
    assert normalize_language(" HI ") == "hi"
    assert normalize_language("fr") is None
    assert normalize_language(None) is None
    assert normalize_language("") is None
    assert set(LANGUAGE_CODES) == {"en", "hi"}


# ---------------------------------------------------------------------------
# prompts: English byte-identity (the rev1 regression guard), Hindi
# ---------------------------------------------------------------------------

# Byte-for-byte the 0.4.8 _SCRIPT_SYSTEM (0.4.3 JSON contract).
_048_SYSTEM = (
    "You write short-form vertical video narration scripts. "
    'Output ONLY valid JSON: {"hook": <one attention-grabbing line that '
    'names the topic>, "body": <array of 3-5 short narration sentences>, '
    '"cta": <one closing line asking the viewer to follow>}. '
    "No markdown fences, no commentary, no notes."
)


def test_english_system_prompt_is_byte_identical_to_048() -> None:
    """rev1 regression guard: 0.4.10 rev1 shipped a 0.4.2-era prose
    prompt here, which silently dropped the JSON contract and failed
    three test_handlers tests in the field. English must stay pinned to
    the 0.4.8 JSON system prompt - in lang.py AND in the handler."""
    assert SCRIPT_SYSTEM_EN == _048_SYSTEM
    assert handlers._SCRIPT_SYSTEM == _048_SYSTEM
    assert handlers._SCRIPT_SYSTEMS["en"] is handlers._SCRIPT_SYSTEM


def test_hindi_system_prompt_is_same_json_contract() -> None:
    """Hindi speaks the same {"hook"/"body"/"cta"} grammar so
    _script_from_json reassembly and format:json decoding apply; only
    the string values are requested in Devanagari."""
    assert handlers._SCRIPT_SYSTEMS["hi"] is SCRIPT_SYSTEM_HI
    assert "JSON" in SCRIPT_SYSTEM_HI
    for key in ('"hook"', '"body"', '"cta"'):
        assert key in SCRIPT_SYSTEM_HI, key
    assert any("०" <= ch <= "९" or "\u0900" <= ch <= "\u097f" for ch in SCRIPT_SYSTEM_HI)
    # no English few-shot example on the script path any more
    assert "volcano" not in SCRIPT_SYSTEM_HI.lower()
    assert "volcano" not in SCRIPT_SYSTEM_EN.lower()


def test_english_prompt_is_byte_identical_to_048() -> None:
    old = (
        "Topic: monarch butterflies\n"
        "Write the narration for a ~60 second vertical video (about "
        "150 words total across hook, body and cta). "
        "Respond with only the JSON object described in the system "
        "prompt."
    )
    assert handlers._script_prompt("monarch butterflies", 150) == old
    assert handlers._script_prompt("monarch butterflies", 150, "en") == old
    assert language_directive("en") == ""


def test_hindi_prompt_carries_devanagari_directive() -> None:
    prompt = handlers._script_prompt("तितली", 150, "hi")
    assert "देवनागरी" in prompt
    assert "Hinglish" in prompt  # the explicit no-Hinglish rule
    assert prompt.startswith("Topic: तितली\n")


def test_fallback_script_languages() -> None:
    en = handlers._fallback_script("coffee making", 150)
    assert en.startswith("Hook:")
    hi = handlers._fallback_script("coffee making", 150, "hi")
    assert hi.startswith("हुक:")
    assert "coffee making" in hi  # topic embedded as-is
    assert "फॉलो" in hi  # CTA line in Hindi


# ---------------------------------------------------------------------------
# voice catalog: language metadata
# ---------------------------------------------------------------------------


def test_catalog_languages() -> None:
    hi = [s for s, m in voices.CATALOG.items() if m.get("language") == "hi"]
    en = [s for s, m in voices.CATALOG.items() if m.get("language") == "en"]
    assert set(hi) == {"hi_IN-pratham-medium", "hi_IN-priyamvada-medium"}
    assert len(en) == 10


def test_summary_groups_english_before_hindi() -> None:
    summary = voices.catalog_summary(None)
    langs = [e["language"] for e in summary]
    assert langs == sorted(langs, key={"en": 0, "hi": 1}.get)  # type: ignore[arg-type]
    assert langs[-2:] == ["hi", "hi"]


def test_language_name() -> None:
    assert language_name("en") == "English"
    assert "हिन्दी" in language_name("hi")
    assert language_name("xx") == "English"


# ---------------------------------------------------------------------------
# route contract: ScriptRequest.language
# ---------------------------------------------------------------------------


def test_script_request_language_optional() -> None:
    body = ScriptRequest(mode="auto")
    assert body.language is None  # pre-0.4.10 bodies keep working
    assert ScriptRequest(mode="model", language="hi").language == "hi"
    assert ScriptRequest(mode="template", language="en").language == "en"


def test_script_request_language_validated() -> None:
    with pytest.raises(ValidationError):
        ScriptRequest(mode="auto", language="fr")


def test_enqueue_script_payload_threads_language() -> None:
    """The route must put the resolved language into the job payload -
    that field is what the handler (and the job record) honours."""
    route_src = Path(
        __import__("laf.api.routes.episodes", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    tree = ast.parse(route_src)
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "enqueue_script"
    )
    dumped = ast.dump(fn)
    assert "language" in dumped
    assert "detect_language" in dumped  # topic-based fallback at enqueue


# ---------------------------------------------------------------------------
# handler plumbing: language rides the whole job (fake daemon, no net)
# ---------------------------------------------------------------------------


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


class _FakeOllamaHi(http.server.BaseHTTPRequestHandler):
    """Valid JSON reply whose values are Devanagari - the Hindi contract
    path (format:json grammar, _script_from_json reassembly)."""

    seen_bodies: list = []

    def do_GET(self):  # noqa: N802 - stdlib contract
        body = json.dumps({"models": [{"name": "qwen3:4b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        type(self).seen_bodies.append(json.loads(self.rfile.read(length)))
        raw = json.dumps(
            {
                "hook": "मानसून का मौसम आया, और पूरा शहर जैसे जी उठा।",
                "body": [
                    "बादल घटते हैं, और हवा में मिट्टी की खुशबू घुल जाती है।",
                    "किसान इस बरसात को अपनी फसल की जान मानते हैं।",
                    "नदियाँ और तालाब दोबारा जीवित हो उठते हैं।",
                ],
                "cta": "मौसम की हर खबर के लिए फॉलो ज़रूर करें।",
            },
            ensure_ascii=False,
        )
        body = json.dumps({"response": raw, "total_duration": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture()
def fake_ollama_hi():
    server = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllamaHi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    _FakeOllamaHi.seen_bodies = []
    yield url
    server.shutdown()


def test_script_gen_hindi_topic_keeps_json_contract(
    env, fake_ollama_hi, monkeypatch
) -> None:
    """Devanagari topic -> auto-hi; the JSON grammar and the bounded
    generation survive (Hindi only widens num_predict 512 -> 768)."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_ollama_hi)
    ep = create_episode(
        env.conn, title="T", topic="तितली के जीवन चक्र पर 60 सेकंड की वीडियो"
    )
    job = _job(env, "script_gen", episode_id=ep["id"])
    result = handle_script_gen({"topic": ep["topic"]}, job, env)
    assert result["method"] == "local_ollama"
    assert result["language"] == "hi"
    body = _FakeOllamaHi.seen_bodies[0]
    assert body["format"] == "json"  # 0.4.3 grammar survives multilang
    assert body["options"]["num_predict"] == 768  # Devanagari headroom
    assert body["think"] is False
    stored = get_episode(env.conn, ep["id"])
    assert any("\u0900" <= ch <= "\u097f" for ch in stored["script_text"])
    assert "मानसून" in stored["script_text"]


def test_script_gen_explicit_language_wins(
    env, fake_ollama_hi, monkeypatch
) -> None:
    """payload.language beats detection - an English topic with an
    explicit "hi" request generates Hindi (MULTILANG.md priority 1)."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_ollama_hi)
    ep = create_episode(env.conn, title="T", topic="monsoon facts")
    job = _job(env, "script_gen", episode_id=ep["id"])
    result = handle_script_gen({"topic": "monsoon facts", "language": "hi"}, job, env)
    assert result["language"] == "hi"
    assert _FakeOllamaHi.seen_bodies[0]["options"]["num_predict"] == 768


def test_script_gen_english_default_reports_language(
    env, fake_ollama_hi, monkeypatch
) -> None:
    """English episodes keep the 0.4.8 num_predict and now record the
    language honestly in the job result."""
    monkeypatch.setenv("LAF_OLLAMA_URL", fake_ollama_hi)
    ep = create_episode(env.conn, title="T", topic="urban beekeeping")
    job = _job(env, "script_gen", episode_id=ep["id"])
    result = handle_script_gen({"topic": ep["topic"]}, job, env)
    assert result["language"] == "en"
    assert _FakeOllamaHi.seen_bodies[0]["options"]["num_predict"] == 512


def test_script_fallback_hindi_template(env) -> None:
    ep = create_episode(env.conn, title="T", topic="तितली का जीवन चक्र")
    job = _job(env, "script_fallback", episode_id=ep["id"])
    result = handle_script_fallback(
        {"topic": ep["topic"], "language": "hi"}, job, env
    )
    assert result["method"] == "fallback_template"
    assert result["language"] == "hi"
    stored = get_episode(env.conn, ep["id"])
    assert stored["script_text"].startswith("हुक:")


# ---------------------------------------------------------------------------
# renderer: Devanagari caption support (pure functions, no ffmpeg)
# ---------------------------------------------------------------------------


def test_renderer_detects_devanagari() -> None:
    from laf import renderer

    assert renderer._has_devanagari("तितली का जीवन चक्र")
    assert not renderer._has_devanagari("plain english caption")
    assert not renderer._has_devanagari("")
    assert renderer._caption_font(["english only"]) == "Arial"
    assert renderer._caption_font(["english", "तितली"]) == (
        "Noto Sans Devanagari"
    )


def test_write_ass_picks_font_per_language(tmp_path: Path) -> None:
    from laf import renderer

    en_path = renderer.write_ass(
        tmp_path / "en.ass", [(0.0, 2.0, "hello world")], "Title", width=270,
        height=480,
    )
    hi_path = renderer.write_ass(
        tmp_path / "hi.ass",
        [(0.0, 2.0, "तितली का जीवन चक्र")],
        "Title",
        width=270,
        height=480,
    )
    en_text = Path(en_path).read_text(encoding="utf-8")
    hi_text = Path(hi_path).read_text(encoding="utf-8")
    assert "Style: Title,Arial," in en_text
    assert "Noto Sans Devanagari" not in en_text
    assert "Style: Title,Noto Sans Devanagari," in hi_text
    assert "Style: Caption,Noto Sans Devanagari," in hi_text


def test_stage_caption_font_uses_bundled_ttf(tmp_path: Path) -> None:
    """The repo fallback copy (backend/laf/fonts) must land next to
    subs.ass so libass finds it via fontsdir=. without a system font."""
    from laf import renderer

    font_src = Path(renderer.__file__).parent / "fonts" / (
        "NotoSansDevanagari-Regular.ttf"
    )
    workdir = tmp_path / "wd"
    renderer._stage_caption_font(workdir, None)
    staged = workdir / "NotoSansDevanagari-Regular.ttf"
    if font_src.exists():
        assert staged.exists() and staged.stat().st_size > 50_000
    else:
        # best-effort staging: no crash, no partial file
        assert not staged.exists()
