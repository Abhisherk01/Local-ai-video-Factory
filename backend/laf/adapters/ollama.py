"""Ollama LLM adapter (Phase 3: script generation).

Talks to the local Ollama daemon over 127.0.0.1 HTTP (default port
11434). Uses the stdlib urllib on purpose: zero new runtime deps for a
two-endpoint integration, and no import-time network activity.

Environment overrides:
- LAF_OLLAMA_URL   (default http://127.0.0.1:11434)
- LAF_OLLAMA_MODEL (default qwen3:4b - the Tier-3 pin from Phase 0)
- LAF_OLLAMA_TIMEOUT (generate timeout seconds, default 600)
- LAF_OLLAMA_NUM_PREDICT (hard output-token cap, default 1536)
- LAF_OLLAMA_KEEP_ALIVE (model residency after a call, default "30m")

qwen3 emits `<think>...</think>` reasoning blocks by default; narration
consumers never want them, so `generate()` requests thinking disabled at
the API level (`"think": false`, supported for thinking-capable models)
AND strips any residual block, reporting whether thinking was present in
the result metadata (honesty rule). Reason: with thinking enabled and
non-streaming HTTP, CPU-only machines timed out before a single script
finished (phase-4 hotfix).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from laf.adapters.base import AdapterStatus, AdapterUnavailable

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL)


def strip_think(raw: str) -> tuple[str, bool, bool]:
    """Remove qwen3 reasoning from a raw completion.

    Returns (text, stripped_any, truncated). Closed <think>...</think>
    blocks are removed wherever they appear. A residual UNCLOSED
    <think> means the model ran off mid-reasoning: everything from it
    to the end is thinking, so it is cut too and `truncated` says so
    honestly (an empty result becomes the handler's retryable empty
    failure - truncated reasoning is never stored as narration).
    """
    stripped = bool(_THINK_RE.search(raw))
    text = _THINK_RE.sub("", raw)
    truncated = False
    idx = text.find("<think>")
    if idx != -1:
        text = text[:idx]
        truncated = True
    if "</think>" in text:
        # Orphan closer (no opener): survives both the closed-block
        # regex and the unclosed-cut. Field evidence: post-6a.1 ep9
        # still carried a tag fragment in stored text.
        text = text.replace("</think>", "")
        stripped = True
    return text.strip(), (stripped or truncated), truncated


def effective_prompt(prompt: str, model: str) -> str:
    """qwen3's documented soft switch: `/no_think` in the prompt stops
    reasoning even when a daemon ignores the `think` API flag. No-op
    for non-qwen3 models."""
    if str(model).startswith("qwen3"):
        return f"{prompt} /no_think"
    return prompt
_PROBE_TIMEOUT_S = 0.6


class OllamaAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        generate_timeout_s: float | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("LAF_OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.model = model or os.environ.get("LAF_OLLAMA_MODEL", "qwen3:4b")
        # 600 s default: the timer must cover cold model load + full script
        # generation on CPU-only machines (180 s timed out in the field).
        self.generate_timeout_s = generate_timeout_s if generate_timeout_s is not None else float(
            os.environ.get("LAF_OLLAMA_TIMEOUT", "600")
        )
        # Hard output cap. num_predict=-1 (the phase-4 setting) removed
        # every ceiling, and qwen3's stochastic ramble mode then filled
        # the WHOLE context window: field signature was a non-streaming
        # 600 s timeout with zero bytes returned while the daemon kept
        # decoding (23 K chars generated inside one timed-out attempt;
        # job #34: three consecutive blind timeouts on a fresh daemon).
        # 1536 covers every current consumer (script ~350, storyboard
        # JSON ~400, 20-idea series outline ~1200 tokens) and bounds the
        # worst case to minutes, not timeouts, even at partial CPU/GPU
        # offload. CPU-only owners can tighten via LAF_OLLAMA_NUM_PREDICT.
        self.num_predict = int(os.environ.get("LAF_OLLAMA_NUM_PREDICT", "1536"))
        # Keep the model resident between back-to-back jobs: Ollama's
        # default 5 m keep_alive unloads it mid-session, and every cold
        # reload re-pays load_duration on exactly the machines that can
        # least afford it ("4 minutes from now" churn in the field).
        self.keep_alive = os.environ.get("LAF_OLLAMA_KEEP_ALIVE", "30m")

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------

    def available(self) -> AdapterStatus:
        """Probe /api/tags with a short timeout. Never raises."""
        try:
            with urllib.request.urlopen(  # noqa: S310 - local, user-configured
                f"{self.base_url}/api/tags", timeout=_PROBE_TIMEOUT_S
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return AdapterStatus(
                name="ollama",
                available=False,
                detail=(
                    f"no Ollama daemon at {self.base_url} "
                    "(install Ollama and run `ollama serve`, or set LAF_OLLAMA_URL)"
                ),
            )
        models = sorted(
            str(m.get("name", ""))
            for m in data.get("models", [])
            if isinstance(m, dict)
        )
        return AdapterStatus(
            name="ollama",
            available=True,
            detail=f"daemon at {self.base_url}, {len(models)} model(s) pulled",
            extra={"models": models, "default_model": self.model},
        )

    # ------------------------------------------------------------------
    # generation
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        options: dict | None = None,
        json_mode: bool = False,
        num_predict: int | None = None,
    ) -> dict:
        """Non-streaming /api/generate call. Returns the text plus honest
        metadata. Raises AdapterUnavailable when the daemon is unreachable
        or the HTTP call fails for any reason."""
        body: dict = {
            "model": model or self.model,
            "prompt": effective_prompt(prompt, model or self.model),
            "stream": False,
            # Narration never wants reasoning tokens; generating them (plus
            # the non-streaming wait) timed out CPU-only machines in the
            # field. Keep the post-hoc strip as belt-and-braces.
            "think": False,
        }
        body["keep_alive"] = self.keep_alive
        if json_mode:
            # Grammar-constrained decoding: the daemon's sampler may only
            # emit grammar-valid JSON tokens, so single quotes, trailing
            # commas and prose drafts become impossible at the source
            # (field failures #14/#15/#18/#19 all parsed post-hoc before
            # this; now they cannot be generated at all).
            body["format"] = "json"
        if system:
            body["system"] = system
        # num_predict MUST be pinned - but BOUNDED, not -1. Ollama's
        # documented default (128) truncates storyboard/series JSON
        # mid-structure and silently clips scripts to ~90 words; -1
        # removes every ceiling and lets a qwen3 runaway decode until the
        # context window fills (see __init__ field evidence). Callers may
        # tighten further per call (script_gen passes 512).
        opts = dict(options or {})
        opts.setdefault(
            "num_predict",
            self.num_predict if num_predict is None else int(num_predict),
        )
        body["options"] = opts
        req = urllib.request.Request(  # noqa: S310 - local, user-configured
            f"{self.base_url}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                req, timeout=self.generate_timeout_s
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AdapterUnavailable(
                f"ollama generate failed at {self.base_url}: {exc}"
            ) from exc

        raw = str(data.get("response", ""))
        text, stripped, truncated = strip_think(raw)
        # Honest performance metadata: eval_count / tokens_per_s make a
        # GPU->CPU offload regression (34%/66% split class) visible in job
        # records, instead of diagnosable only via hand-run probes.
        eval_count = data.get("eval_count")
        eval_duration = data.get("eval_duration")
        tokens_per_s = None
        if eval_count and eval_duration:
            tokens_per_s = round(eval_count / (eval_duration / 1e9), 2)
        return {
            "text": text,
            "raw_chars": len(raw),
            "thinking_stripped": stripped,
            "think_truncated": truncated,
            "model": body["model"],
            "method": "local_ollama",
            "total_duration_ns": data.get("total_duration"),
            "load_duration_ns": data.get("load_duration"),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": eval_count,
            "eval_duration_ns": eval_duration,
            "tokens_per_s": tokens_per_s,
        }
