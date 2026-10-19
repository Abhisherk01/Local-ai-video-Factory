"""Ollama LLM adapter (Phase 3: script generation).

Talks to the local Ollama daemon over 127.0.0.1 HTTP (default port
11434). Uses the stdlib urllib on purpose: zero new runtime deps for a
two-endpoint integration, and no import-time network activity.

Environment overrides:
- LAF_OLLAMA_URL   (default http://127.0.0.1:11434)
- LAF_OLLAMA_MODEL (default qwen3:4b - the Tier-3 pin from Phase 0)

qwen3 emits `<think>...</think>` reasoning blocks by default; narration
consumers never want them, so `generate()` strips them and reports
whether thinking was present in the result metadata (honesty rule).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from laf.adapters.base import AdapterStatus, AdapterUnavailable

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_PROBE_TIMEOUT_S = 0.6


class OllamaAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        generate_timeout_s: float = 180.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("LAF_OLLAMA_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.model = model or os.environ.get("LAF_OLLAMA_MODEL", "qwen3:4b")
        self.generate_timeout_s = generate_timeout_s

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
    ) -> dict:
        """Non-streaming /api/generate call. Returns the text plus honest
        metadata. Raises AdapterUnavailable when the daemon is unreachable
        or the HTTP call fails for any reason."""
        body: dict = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            body["system"] = system
        if options:
            body["options"] = options
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
        text = _THINK_RE.sub("", raw).strip()
        return {
            "text": text,
            "raw_chars": len(raw),
            "thinking_stripped": bool(_THINK_RE.search(raw)),
            "model": body["model"],
            "method": "local_ollama",
            "total_duration_ns": data.get("total_duration"),
        }
