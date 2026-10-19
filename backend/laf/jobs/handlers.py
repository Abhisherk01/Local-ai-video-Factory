"""Phase 3 job handlers (registry).

Every handler: `fn(payload: dict, job: dict, ctx: HandlerContext) -> dict`.
Returning a dict marks the job succeeded with that result payload.
Raising marks it failed; `PrereqMissing` fails it immediately (no
retry - an absent Ollama/Piper install does not heal in 2 seconds).

Method labels are honest by design (ADR-010):
- script_gen      -> method "local_ollama"  (or fallback template)
- script_fallback -> method "fallback_template"
- tts_render      -> method "local_piper"   (or fallback tone)
- tts_fallback    -> method "fallback_tone"
"""

from __future__ import annotations

import logging
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from laf.adapters import AdapterUnavailable, OllamaAdapter, PiperAdapter
from laf.episodes import set_episode_script

logger = logging.getLogger("laf.jobs.handlers")


class PrereqMissing(RuntimeError):
    """A local prerequisite (Ollama daemon, piper voice) is absent."""


@dataclass
class HandlerContext:
    conn: Any  # sqlite3.Connection owned by the worker thread
    data_dir: Path
    models_dir: Path


Handler = Callable[[dict, dict, HandlerContext], dict]

_SCRIPT_SYSTEM = (
    "You write short-form vertical video narration scripts. "
    "Output ONLY the narration script as plain text: one HOOK line, "
    "3-5 BODY sentences, one CTA line. No markdown, no headings, no "
    "stage directions, no emojis."
)


def _script_prompt(topic: str, target_words: int) -> str:
    return (
        f"Topic: {topic}\n"
        f"Write a narration script for a ~60 second vertical video "
        f"(about {target_words} words). Start with a hook that names "
        f"the topic, then the body, end with a call to action."
    )


def _fallback_script(topic: str, target_words: int) -> str:
    """Deterministic template script - the no-model pipeline path."""
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
        raise RuntimeError(f"episode {episode_id} disappeared mid-job")


def handle_script_gen(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise RuntimeError("payload.topic is required")
    target_words = int(payload.get("target_words", 150))

    ollama = OllamaAdapter()
    status = ollama.available()
    if not status.available:
        if payload.get("allow_fallback"):
            text = _fallback_script(topic, target_words)
            _store_script(ctx, job, text, "fallback_template")
            return {
                "method": "fallback_template",
                "reason": status.detail,
                "chars": len(text),
            }
        raise PrereqMissing(f"ollama_unavailable: {status.detail}")

    result = ollama.generate(
        _script_prompt(topic, target_words), system=_SCRIPT_SYSTEM
    )
    if not result["text"]:
        raise RuntimeError("ollama returned an empty script")
    _store_script(ctx, job, result["text"], result["method"])
    return {
        "method": result["method"],
        "model": result["model"],
        "chars": len(result["text"]),
        "thinking_stripped": result["thinking_stripped"],
    }


def handle_script_fallback(payload: dict, job: dict, ctx: HandlerContext) -> dict:
    topic = str(payload.get("topic") or "").strip()
    if not topic:
        raise RuntimeError("payload.topic is required")
    text = _fallback_script(topic, int(payload.get("target_words", 150)))
    _store_script(ctx, job, text, "fallback_template")
    return {"method": "fallback_template", "chars": len(text)}


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
    if not piper.available().available:
        if payload.get("allow_fallback"):
            return handle_tts_fallback(payload, job, ctx)
        raise PrereqMissing("piper_unavailable: see /api/v1/adapters for the fix")
    out = _media_dir(ctx) / f"tts_job{job['id']}.wav"
    result = piper.synthesize(text, out)
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
# registry
# ---------------------------------------------------------------------------

JOB_HANDLERS: dict[str, Handler] = {
    "script_gen": handle_script_gen,
    "script_fallback": handle_script_fallback,
    "tts_render": handle_tts_render,
    "tts_fallback": handle_tts_fallback,
}


def handler_for(job_type: str) -> Handler | None:
    return JOB_HANDLERS.get(job_type)


def known_types() -> list[str]:
    return sorted(JOB_HANDLERS)
