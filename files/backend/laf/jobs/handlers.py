"""Phase 3+4 job handlers (registry).

Every handler: `fn(payload: dict, job: dict, ctx: HandlerContext) -> dict`.
Returning a dict marks the job succeeded with that result payload.
Raising marks it failed; `PrereqMissing` fails it immediately (no
retry - an absent Ollama/Piper install does not heal in 2 seconds).
`NonRetryable` (Phase 4) fails it immediately too: the error is
deterministic (episode/script/style/series missing), so the two extra
attempts would only burn generation time (phase-3 field lesson from the
"episode disappeared mid-job" incident).

Method labels are honest by design (ADR-010):
- script_gen         -> method "local_ollama"  (or fallback template)
- script_fallback    -> method "fallback_template"
- storyboard_gen     -> method "local_ollama"  (or fallback split)
- storyboard_fallback-> method "fallback_split"
- series_outline_gen -> method "local_ollama"  (or fallback angles)
- series_outline_fallback -> method "fallback_angles"
- tts_render         -> method "local_piper"   (or fallback tone)
- tts_fallback       -> method "fallback_tone"
- video_render       -> method "local_piper"   (or fallback tone)

0.4.10-multilang: script_gen carries a language ("en"/"hi") chosen
per request or detected from the topic (laf.lang). Hindi speaks the
same 0.4.3 JSON contract with Devanagari values; English behaviour
stays byte-identical to 0.4.8.
"""

from __future__ import annotations

import json
import logging
import math
import re
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from laf import renderer
from laf import voices
from laf.adapters import AdapterUnavailable, OllamaAdapter, PiperAdapter
from laf.dedupe import filter_duplicates
from laf.episodes import (
    create_episode,
    get_episode,
    set_episode_script,
    set_episode_status,
)
from laf.lang import (
    SCRIPT_SYSTEM_HI,
    detect_language,
    language_directive,
    normalize_language,
)
from laf.series import (
    fallback_outline,
    get_series,
    list_series_episodes,
    set_series_method,
)
from laf.storyboards import get_storyboard, replace_storyboard
from laf.styles import DEFAULT_STYLE_SLUG, get_style

logger = logging.getLogger("laf.jobs.handlers")


class PrereqMissing(RuntimeError):
    """A local prerequisite (Ollama daemon, piper voice) is absent."""


class NonRetryable(RuntimeError):
    """Deterministic handler failure; retrying cannot heal it.

    The worker fails the job on the spot instead of burning the
    remaining attempts (and, on model paths, another full generation)
    on an error that will identically recur.
    """


@dataclass
class HandlerContext:
    conn: Any  # sqlite3.Connection owned by the worker thread
    data_dir: Path
    models_dir: Path


Handler = Callable[[dict, dict, HandlerContext], dict]

# Phase 6a.2: qwen3 plain-text planning guard. Field evidence: the stored
# "scripts" of ep3/6/7/9/10 ARE the reasoning (15K/20K/2.2K/23K/2.4K chars
# for a 150-word target).
# 0.4.2 precision move: "we are writing"/"below is" are HEAD-only now.
# Every field-observed leak OPENS with its marker, so head-only keeps the
# full true-positive catch; but a narration sentence like "we are writing
# history with every frame" inside the first 400 chars can be legitimate -
# and a false positive burns ALL three attempts (job #39 went 0/3, ep11
# stayed empty).
_META_ANYWHERE = ("the user wants", "as requested")
_META_HEAD = (
    "okay,",
    "okay ",
    "i need to",
    "i will write",
    "i'll write",
    "let me write",
    "we are writing",
    "below is",
)


def looks_like_meta_text(text: str) -> bool:
    """Detect planning chatter in a supposedly-final narration script.

    qwen3:4b opens replies with prompt-echo planning ("We are writing...",
    "Okay, the user wants me to...") and ignores the word budget. The
    system prompt alone does not stop it (ep9 proves that), so the head
    is checked against observed meta openers and flagged; the handler
    turns a flag into a retryable error so the queue re-rolls the model.
    Precision-first: a false positive costs one auto-retry, a false
    negative stores chatter as narration.
    """
    head = text[:120].lower().lstrip()
    if head.startswith(_META_HEAD):
        return True
    first = text[:400].lower()
    return any(op in first for op in _META_ANYWHERE)


# 0.4.3: script_gen joins the JSON-grammar club. Field evidence across
# three patch generations:
# - 0.4.1 free-text: qwen3 opened with ~2.1K chars of plain-text plan-
#   chatter ("Okay, the user wants...") even with think=False + /no_think
#   + tightened instructions; identical retries went 0/3 (job #39).
# - 0.4.2 few-shot demo: the example got PARROTED as the script (job #41
#   attempt 1-2 -> the anti-copy sentinel caught it, but the attempts
#   were burned).
# - storyboard/series with format:"json" (grammar-constrained decoding)
#   succeed on the same model: prose openers are structurally impossible
#   under the JSON grammar. So narration is now requested as JSON and
#   reassembled; the 6a.2 guard still applies to the assembled text
#   because chatter can ride inside string values.
_SCRIPT_SYSTEM = (
    "You write short-form vertical video narration scripts. "
    'Output ONLY valid JSON: {"hook": <one attention-grabbing line that '
    'names the topic>, "body": <array of 3-5 short narration sentences>, '
    '"cta": <one closing line asking the viewer to follow>}. '
    "No markdown fences, no commentary, no notes."
)

# 0.4.10-multilang: the English JSON system prompt above stays
# byte-identical to 0.4.8 (pinned by tests/test_multilang.py);
# Hindi speaks the same JSON contract with Devanagari values
# (SCRIPT_SYSTEM_HI in laf.lang).
_SCRIPT_SYSTEMS = {"en": _SCRIPT_SYSTEM, "hi": SCRIPT_SYSTEM_HI}


def _script_from_json(blob: str) -> str:
    """Reassemble plain narration from the model's JSON fields.

    Raises RuntimeError (retryable) when no JSON object can be recovered
    or when the object carries no narration at all."""
    data = _load_json_object(blob)
    hook = str(data.get("hook") or "").strip()
    body = data.get("body") or []
    if isinstance(body, str):
        body = [body]
    elif isinstance(body, (list, tuple)):
        body = list(body)
    else:
        body = [str(body)]
    cta = str(data.get("cta") or "").strip()
    lines = [hook] + [str(s).strip() for s in body] + [cta]
    text = "\n".join(line for line in lines if line)
    if not text:
        raise RuntimeError("script JSON contained no narration fields")
    return text


def _script_prompt(topic: str, target_words: int, language: str = "en") -> str:
    """0.4.10-multilang: appends laf.lang.language_directive - ""
    for English keeps the pre-0.4.10 prompt byte-identical."""
    return (
        f"Topic: {topic}\n"
        f"Write the narration for a ~60 second vertical video (about "
        f"{target_words} words total across hook, body and cta). "
        f"Respond with only the JSON object described in the system "
        f"prompt."
        f"{language_directive(language)}"
    )


def _fallback_script(topic: str, target_words: int, language: str = "en") -> str:
    """Deterministic template script - the no-model pipeline path.

    0.4.10-multilang: Hindi episodes fall back to a Hindi template
    so the narration never switches language mid-pipeline. The
    topic text is embedded as-is, whatever script it uses."""
    if language == "hi":
        return (
            f"हुक: {topic} को आसान भाषा में समझिए।\n"
            f"{topic} के बारे में यह जानकारी आपके लिए ज़रूरी है। "
            "इसे आसान भाषा में जानना हर किसी के लिए फ़ायदेमंद है। "
            "यही सादगी इसे खास बनाती है।\n"
            "सीटीए: ऐसी ही जानकारी के लिए फॉलो करें।"
        )
    sentences = max(3, min(6, target_words // 30))
    body = " ".join(
        f"Point {i}: here is what matters about {topic} and why it "
        "changes how you should look at it."
        for i in range(1, sentences + 1)
    )
    return (
        f"Hook: everything you know about {topic} is about to get simpler.\n"
        f"{body}\n"
        f"CTA: follow for more on {topic}."
    )


# ---------------------------------------------------------------------------
# script handlers
# ---------------------------------------------------------------------------


def _store_script(ctx: HandlerContext, job: dict, text: str, method: str) -> None:
    episode_id = job.get("episode_id")
    if episode_id is None:
        return
    episode = set_episode_script(
        ctx.conn, int(episode_id), script_text=text, script_method=method
    )
    if episode is None:
        # Deterministic: the store target is gone, a re-run would
        # generate another full script only to hit the same wall.
        raise NonRetryable(f"episode {episode_id} disappeared mid-job")


def handle_script_gen(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise RuntimeError("payload.topic is required")
    target_words = int(payload.get("target_words", 150))
    # 0.4.10-multilang: explicit payload.language wins, else detect
    # from the topic (Devanagari presence or an explicit hint).
    language = normalize_language(payload.get("language")) or detect_language(
        topic
    )

    ollama = OllamaAdapter()
    status = ollama.available()
    if not status.available:
        if payload.get("allow_fallback"):
            text = _fallback_script(topic, target_words, language)
            _store_script(ctx, job, text, "fallback_template")
            return {
                "method": "fallback_template",
                "reason": status.detail,
                "chars": len(text),
                "language": language,
            }
        raise PrereqMissing(f"ollama_unavailable: {status.detail}")

    # 0.4.2: identical retries are correlated retries - #39 went 0/3 on
    # the same prompt + params. Each attempt re-rolls the sampler:
    # 0.6 compliance-first baseline, 1.0 escapes attempt 1's attractor,
    # 0.3 near-deterministic final roll.
    attempt = max(1, int(job.get("attempts") or 1))
    temperature = {1: 0.6, 2: 1.0, 3: 0.3}.get(attempt, 0.6)
    result = ollama.generate(
        _script_prompt(topic, target_words, language),
        system=_SCRIPT_SYSTEMS[language],
        # 512 tok ≈ 2x the 150-word target. Bounds a runaway attempt to
        # ~1-2 min even on a partially-CPU-offloaded daemon (34%/66%
        # split class) instead of a blind 600 s timeout (jobs #33/#34).
        # 0.4.10-multilang: Devanagari costs roughly 2-3x the
        # tokens per word, so Hindi gets 768 to avoid clipping
        # mid-script; the word-count guard below still rejects
        # runaway output. English keeps 512 (0.4.8 behaviour).
        num_predict=768 if language == "hi" else 512,
        # 0.4.3: grammar-constrained decoding - the same mechanism that
        # fixed storyboard/series on this model. Prose openers cannot
        # lead the output anymore; chatter may only ride inside JSON
        # string values, where the guard below still catches it.
        json_mode=True,
        options={"temperature": temperature, "top_p": 0.9},
    )
    if not result["text"]:
        raise RuntimeError("ollama returned an empty script")
    text = _script_from_json(result["text"])
    if looks_like_meta_text(text) or len(text.split()) > target_words * 3:
        # Phase 6a.2 field lesson (ep3/6/7/9/10): chatter inside JSON
        # values still counts. 0.4.2: the error carries the opening of
        # the rejected text so the failure self-describes in
        # verify_db.py output.
        head = " ".join(text[:200].split())
        raise RuntimeError(
            "ollama returned meta/bloated script text "
            f"({len(text)} chars, {len(text.split())} words) - retrying; "
            f"head: {head!r}"
        )
    _store_script(ctx, job, text, result["method"])
    return {
        "method": result["method"],
        "model": result["model"],
        "chars": len(result["text"]),
        "thinking_stripped": result["thinking_stripped"],
        "think_truncated": result.get("think_truncated", False),
        "language": language,
    }


def handle_script_fallback(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise RuntimeError("payload.topic is required")
    language = normalize_language(payload.get("language")) or detect_language(
        topic
    )
    text = _fallback_script(
        topic, int(payload.get("target_words", 150)), language
    )
    _store_script(ctx, job, text, "fallback_template")
    return {
        "method": "fallback_template",
        "chars": len(text),
        "language": language,
    }


# ---------------------------------------------------------------------------
# storyboard handlers (Phase 4)
# ---------------------------------------------------------------------------


_JSON_SYSTEM = (
    "You are a video production assistant. Output ONLY valid JSON. "
    "No markdown fences, no commentary, no notes."
)

_FENCE_RE = re.compile(r"```[a-zA-Z]*\n?")

_SCENE_ROLES = (
    "establishing shot",
    "close-up detail shot",
    "medium action shot",
    "on-screen text shot",
    "cutaway detail shot",
    "dynamic motion shot",
    "warm closing shot",
    "end card shot",
)


def _loads_tolerant(blob: str) -> dict:
    """Recover the model's JSON from common qwen3 sloppiness.

    Field-observed failure modes (jobs #14/#15/#18): single-quoted
    strings/keys ("Expecting value: line 1 column 12"), trailing commas
    ("Expecting property name enclosed in double quotes"), and a complete
    object followed by extra drafts ("Extra data: ..."). raw_decode()
    takes the first complete object and ignores trailing data;
    literal_eval rebuilds Python-literal syntax; the comma strip removes
    dangling commas. Raises ValueError (retryable upstream) when nothing
    works.
    """
    candidates = [blob, re.sub(r",\s*([}\]])", r"\1", blob)]
    try:
        import ast

        candidates.append(json.dumps(ast.literal_eval(blob)))
    except (ValueError, SyntaxError):
        pass
    for text in candidates:
        try:
            data, _end = json.JSONDecoder().raw_decode(text)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("unparseable even after tolerant retries")


def _load_json_object(text: str) -> dict:
    """Tolerant JSON extraction: strips code fences, slices the outermost
    braces, raises RuntimeError (retryable) on anything unparseable."""
    cleaned = _FENCE_RE.sub("", str(text))
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise RuntimeError("model output contained no JSON object")
    try:
        data = _loads_tolerant(cleaned[start : end + 1])
    except ValueError as exc:
        raise RuntimeError(f"model JSON invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("model JSON was not an object")
    return data


# Sentence boundaries: terminal punctuation (". "/"! "/"? ") OR a line
# break. qwen scripts are one beat per line and often omit the final
# period - punctuation-only splitting collapsed those scripts to a
# single "sentence", which collapsed the whole storyboard to 1 scene
# (ep10 rendered 22 s on one static card).
# laf 0.4.8-scenecount rev3
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(script: str) -> list[str]:
    """Split a script into beats at punctuation and/or line breaks."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(script) if s.strip()]


def _scene_count(script: str) -> int:
    """Target scene count from script length (~35 words per scene),
    clamped to 3-8 and never more than the sentence count."""
    words = len(script.split())
    sentences = _sentences(script)
    n = max(3, min(8, words // 35))
    return max(1, min(n, len(sentences)))


def _split_narration(script: str, n: int) -> list[str]:
    """Split the script into n ordered narration slices.

    Deterministic: sentences in order, distributed as evenly as
    possible. Concatenated slices reproduce the whole script, so no
    narration is ever lost or invented between scenes.
    """
    sentences = _sentences(script)
    if not sentences:  # single unpunctuated line
        sentences = [script.strip()]
    base, extra = divmod(len(sentences), n)
    slices: list[str] = []
    at = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        chunks = sentences[at : at + size]
        at += size
        if chunks:
            slices.append(" ".join(chunks))
    return slices or [script.strip()]


def _visual_prompt(style: dict, shot: str) -> str:
    """Compose the final text-to-image prompt: style prefix + shot + suffix."""
    parts = [
        str(style.get("prompt_prefix", "")).strip(),
        shot.strip(),
        str(style.get("prompt_suffix", "")).strip(),
    ]
    return ", ".join(p for p in parts if p)


def _storyboard_context(ctx: HandlerContext, job: dict) -> tuple[dict, str]:
    episode_id = job.get("episode_id")
    if episode_id is None:
        raise NonRetryable("storyboard job has no episode bound")
    ep = get_episode(ctx.conn, int(episode_id))
    if ep is None:
        raise NonRetryable(f"episode {episode_id} disappeared mid-job")
    script = str(ep["script_text"] or "").strip()
    if not script:
        raise NonRetryable(
            f"episode {episode_id} has no script yet - run Script first"
        )
    return ep, script


def _resolve_style(ctx: HandlerContext, payload: dict) -> dict:
    slug = str(payload.get("style_slug") or DEFAULT_STYLE_SLUG)
    style = get_style(ctx.conn, slug)
    if style is None:
        raise NonRetryable(f"style '{slug}' is not in the registry")
    return style


def _store_storyboard(
    ctx: HandlerContext,
    ep: dict,
    style: dict,
    narrations: list[str],
    shots: list[str],
    method: str,
) -> dict:
    scenes = [
        {"narration": narr, "visual_prompt": _visual_prompt(style, shot)}
        for narr, shot in zip(narrations, shots)
    ]
    stored = replace_storyboard(
        ctx.conn,
        episode_id=int(ep["id"]),
        style_slug=str(style["slug"]),
        method=method,
        scenes=scenes,
    )
    if stored is None:
        raise NonRetryable(f"episode {ep['id']} disappeared mid-job")
    return {
        "method": method,
        "scene_count": int(stored["scene_count"]),
        "total_duration_s": float(stored["total_duration_s"]),
        "style": str(style["slug"]),
    }


def _storyboard_prompt(script: str, n: int, style: dict) -> str:
    return (
        f"Narration script for a ~60 second vertical video:\n\n{script}\n\n"
        f"Visual style: {style['name']} - "
        f"{str(style['prompt_prefix']).strip()}\n\n"
        f"Plan the shot list: exactly {n} scenes, in script order.\n"
        'Return ONLY JSON like {"shots": ["shot one", "shot two"]} '
        f"with exactly {n} items. Each item is one concrete on-screen "
        "shot description (subject, action, framing, lighting) in the "
        "given style, max 25 words. The narration may be in any "
        "language - write every shot description in English anyway."
    )


def _parse_shots(text: str, expected: int) -> list[str]:
    data = _load_json_object(text)
    shots = data.get("shots")
    if not isinstance(shots, list):
        raise RuntimeError("model JSON missing a 'shots' array")
    out = [str(s).strip() for s in shots if str(s).strip()]
    if len(out) != expected:
        raise RuntimeError(
            f"model returned {len(out)} shots, expected {expected}"
        )
    return out


def handle_storyboard_gen(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    ep, script = _storyboard_context(ctx, job)
    style = _resolve_style(ctx, payload)
    n = _scene_count(script)
    narrations = _split_narration(script, n)

    ollama = OllamaAdapter()
    status = ollama.available()
    if not status.available:
        if payload.get("allow_fallback"):
            shots = [
                f"{_SCENE_ROLES[i % len(_SCENE_ROLES)]} illustrating {ep['topic']}"
                for i in range(n)
            ]
            result = _store_storyboard(
                ctx, ep, style, narrations, shots, "fallback_split"
            )
            return {**result, "reason": status.detail}
        raise PrereqMissing(f"ollama_unavailable: {status.detail}")

    result = ollama.generate(
        _storyboard_prompt(script, n, style),
        system=_JSON_SYSTEM,
        # num_ctx 4096 (was 8192): prompt + shots JSON fit in ~1-2K
        # tokens, and the smaller window halves KV-cache VRAM - on a
        # 4-6 GB GPU that difference decides 100% vs partial CPU/GPU
        # offload, i.e. a 4-6x decode speed change.
        options={"num_ctx": 4096},
        json_mode=True,
    )
    shots = _parse_shots(result["text"], n)
    stored = _store_storyboard(ctx, ep, style, narrations, shots, "local_ollama")
    return {
        **stored,
        "model": result["model"],
        "thinking_stripped": result["thinking_stripped"],
        "think_truncated": result.get("think_truncated", False),
    }


def handle_storyboard_fallback(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    ep, script = _storyboard_context(ctx, job)
    style = _resolve_style(ctx, payload)
    n = _scene_count(script)
    narrations = _split_narration(script, n)
    shots = [
        f"{_SCENE_ROLES[i % len(_SCENE_ROLES)]} illustrating {ep['topic']}"
        for i in range(n)
    ]
    result = _store_storyboard(ctx, ep, style, narrations, shots, "fallback_split")
    return {**result, "note": "deterministic shot templates - no model used"}


# ---------------------------------------------------------------------------
# series outline handlers (Phase 4)
# ---------------------------------------------------------------------------


def _series_prompt(premise: str, count: int) -> str:
    return (
        f"Series premise: {premise}\n\n"
        f"Propose exactly {count} DISTINCT episode ideas for a short-form "
        "vertical video series built on this premise. No two ideas may "
        "cover the same subject.\n"
        'Return ONLY JSON like {"episodes": [{"title": "...", '
        '"topic": "..."}]} with exactly '
        f"{count} items. Each topic is 1-3 sentences of concrete "
        "narration subject matter."
    )


def _parse_ideas(text: str, max_count: int) -> list[dict[str, str]]:
    data = _load_json_object(text)
    eps = data.get("episodes")
    if not isinstance(eps, list) or not eps:
        raise RuntimeError("model JSON missing a non-empty 'episodes' array")
    ideas: list[dict[str, str]] = []
    for item in eps[:max_count]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        topic = str(item.get("topic", "")).strip()
        if title and topic:
            ideas.append({"title": title[:200], "topic": topic[:2000]})
    if not ideas:
        raise RuntimeError("model JSON had no usable title/topic pairs")
    return ideas


def _accept_outline(
    ctx: HandlerContext, series_id: int, ideas: list[dict[str, str]], method: str
) -> dict:
    """Dedupe ideas against existing series episodes + each other, then
    store accepted ones as draft episodes linked to the series."""
    existing = [
        str(r["topic"])
        for r in list_series_episodes(ctx.conn, series_id)
    ]
    flags = filter_duplicates([i["topic"] for i in ideas], existing)
    accepted: list[str] = []
    skipped: list[dict[str, str]] = []
    for idea, dup in zip(ideas, flags):
        if dup:
            skipped.append(
                {"title": idea["title"], "reason": "duplicate topic"}
            )
            continue
        create_episode(ctx.conn, title=idea["title"], topic=idea["topic"], series_id=series_id)
        accepted.append(idea["title"])
    if accepted:
        set_series_method(ctx.conn, series_id, method)
    if not accepted:
        raise NonRetryable(
            f"all {len(ideas)} outline candidates were duplicates of "
            "episodes already in this series"
        )
    return {
        "requested": len(ideas),
        "accepted": len(accepted),
        "skipped": skipped,
        "titles": accepted,
    }


def _series_context(ctx: HandlerContext, payload: dict) -> dict:
    series_id = payload.get("series_id")
    if series_id is None:
        raise NonRetryable("series job has no series bound")
    series = get_series(ctx.conn, int(series_id))
    if series is None:
        raise NonRetryable(f"series {series_id} disappeared mid-job")
    return series


def handle_series_outline_gen(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    series = _series_context(ctx, payload)
    premise = str(series["premise"])
    count = int(series["requested_count"])

    ollama = OllamaAdapter()
    status = ollama.available()
    if not status.available:
        if payload.get("allow_fallback"):
            summary = _accept_outline(
                ctx, int(series["id"]), fallback_outline(premise, count),
                "fallback_angles",
            )
            return {**summary, "method": "fallback_angles", "reason": status.detail}
        raise PrereqMissing(f"ollama_unavailable: {status.detail}")

    result = ollama.generate(
        _series_prompt(premise, count),
        system=_JSON_SYSTEM,
        # Same num_ctx rationale as storyboard_gen (KV-cache VRAM).
        options={"num_ctx": 4096},
        json_mode=True,
    )
    ideas = _parse_ideas(result["text"], count)
    summary = _accept_outline(ctx, int(series["id"]), ideas, "local_ollama")
    return {
        **summary,
        "method": "local_ollama",
        "model": result["model"],
        "thinking_stripped": result["thinking_stripped"],
        "think_truncated": result.get("think_truncated", False),
    }


def handle_series_outline_fallback(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    series = _series_context(ctx, payload)
    ideas = fallback_outline(str(series["premise"]), int(series["requested_count"]))
    summary = _accept_outline(
        ctx, int(series["id"]), ideas, "fallback_angles"
    )
    return {
        **summary,
        "method": "fallback_angles",
        "note": "deterministic 20-angle outline - no model used",
    }


# ---------------------------------------------------------------------------
# tts handlers
# ---------------------------------------------------------------------------


def _media_dir(ctx: HandlerContext) -> Path:
    path = ctx.data_dir / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _episode_script(ctx: HandlerContext, job: dict, payload: dict) -> str:
    text = str(payload.get("text") or "").strip()
    if text:
        return text
    episode_id = job.get("episode_id")
    if episode_id is not None:
        row = ctx.conn.execute(
            "SELECT script_text FROM episodes WHERE id = ?", (int(episode_id),)
        ).fetchone()
        if row and row[0] and str(row[0]).strip():
            return str(row[0]).strip()
    raise RuntimeError("no text: pass payload.text or script the episode first")


def handle_tts_render(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    text = _episode_script(ctx, job, payload)
    piper = PiperAdapter(models_dir=ctx.models_dir)
    voice_slug = str(payload.get("voice_slug") or "auto")
    voice_path = voices.resolve_voice_path(ctx.models_dir, voice_slug)
    voice_scale = (
        voices.preset_for(voice_slug) if voice_path is not None else None
    )
    if not piper.available().available:
        if payload.get("allow_fallback"):
            return handle_tts_fallback(payload, job, ctx)
        raise PrereqMissing("piper_unavailable: see /api/v1/adapters for the fix")
    out = _media_dir(ctx) / f"tts_job{job['id']}.wav"
    result = piper.synthesize(
        text, out, voice=voice_path, length_scale=voice_scale
    )
    return {
        "method": result["method"],
        "path": result["path"],
        "bytes": result["bytes"],
        "voice": result["voice"],
    }


def handle_tts_fallback(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    """Render a 2 s 220 Hz tone WAV with the stdlib only.

    This exists so the render pipeline is provable end-to-end before any
    voice model is installed. It is labeled honestly as a placeholder:
    `fallback_tone` is never passed off as speech.
    """
    _ = _episode_script(ctx, job, payload)  # require a script to exist
    rate = 22050
    seconds = 2.0
    out = _media_dir(ctx) / f"tts_fallback_job{job['id']}.wav"
    frames = _render_tone(rate, seconds)
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return {
        "method": "fallback_tone",
        "path": str(out),
        "bytes": out.stat().st_size,
        "duration_s": seconds,
        "note": "placeholder tone - install piper for real speech",
    }


def _render_tone(rate: int, seconds: float, freq: float = 220.0) -> bytes:
    total = int(rate * seconds)
    fade = int(rate * 0.25)  # 250 ms fade-out, no click on playback stop
    frames = bytearray()
    for i in range(total):
        amp = 0.2
        if i > total - fade:
            amp *= (total - i) / fade
        sample = int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", sample)
    return bytes(frames)


# ---------------------------------------------------------------------------
# video render (Phase 5)
# ---------------------------------------------------------------------------


def handle_video_render(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    """Render a storyboarded episode to a 9:16 MP4 (Phase 5).

    Scene rows from the storyboard are the contract (ADR-011). Audio is
    piper when installed, else the honest tone placeholder when
    allow_fallback. ffmpeg/ffprobe come from PATH (Phase 5 prereq).
    """
    ffmpeg = renderer.resolve_ffmpeg()
    if not ffmpeg:
        raise PrereqMissing(
            "ffmpeg not found on PATH - install it and restart the shell"
        )
    episode_id = job.get("episode_id")
    if episode_id is None:
        raise NonRetryable("render job has no episode_id")
    episode = get_episode(ctx.conn, int(episode_id))
    if episode is None:
        raise NonRetryable(f"episode {episode_id} disappeared mid-job")
    storyboard = get_storyboard(ctx.conn, int(episode_id))
    if storyboard is None or not storyboard.get("scenes"):
        raise NonRetryable("no storyboard - run Storyboard first")

    piper = PiperAdapter(models_dir=ctx.models_dir)
    use_piper = piper.available().available
    voice_slug = str(payload.get("voice_slug") or "auto")
    voice_path = voices.resolve_voice_path(ctx.models_dir, voice_slug)
    voice_scale = (
        voices.preset_for(voice_slug) if voice_path is not None else None
    )
    if not use_piper and not payload.get("allow_fallback", True):
        raise PrereqMissing("piper_unavailable: see /api/v1/adapters for the fix")

    renders_dir = ctx.data_dir / "media" / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    out_path = renders_dir / f"ep{int(episode_id)}_job{int(job['id'])}.mp4"
    workdir = renders_dir / f"_work_job{int(job['id'])}"
    result = renderer.render_episode(
        ffmpeg,
        workdir=workdir,
        out_path=out_path,
        title=str(episode["title"]),
        style_slug=str(storyboard.get("style_slug") or DEFAULT_STYLE_SLUG),
        scenes=list(storyboard["scenes"]),
        audio_mode="piper" if use_piper else "tone",
        piper=piper if use_piper else None,
        models_dir=ctx.models_dir,
        voice=voice_path,
        length_scale=voice_scale,
    )
    set_episode_status(ctx.conn, int(episode_id), "rendered")
    return result


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

JOB_HANDLERS: dict[str, Handler] = {
    "script_gen": handle_script_gen,
    "script_fallback": handle_script_fallback,
    "storyboard_gen": handle_storyboard_gen,
    "storyboard_fallback": handle_storyboard_fallback,
    "series_outline_gen": handle_series_outline_gen,
    "series_outline_fallback": handle_series_outline_fallback,
    "tts_render": handle_tts_render,
    "tts_fallback": handle_tts_fallback,
    "video_render": handle_video_render,
}


def handler_for(job_type: str) -> Handler | None:
    return JOB_HANDLERS.get(job_type)


def known_types() -> list[str]:
    return sorted(JOB_HANDLERS)
