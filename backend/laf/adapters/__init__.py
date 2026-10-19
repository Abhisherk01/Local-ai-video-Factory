"""Generation adapters (ADR-010).

- ollama.py: local LLM scripting (Phase 3 working model path).
- piper.py  : local TTS via the piper CLI (Phase 3 working TTS path).
- kokoro.py : availability probe only; synthesis wiring lands in Phase 5.

`status_summary()` is what /api/v1/adapters returns - one fast,
side-effect-free probe per adapter.
"""

from __future__ import annotations

from pathlib import Path

from laf.adapters.base import AdapterStatus, AdapterUnavailable
from laf.adapters.kokoro import KokoroAdapter
from laf.adapters.ollama import OllamaAdapter
from laf.adapters.piper import PiperAdapter

__all__ = [
    "AdapterStatus",
    "AdapterUnavailable",
    "KokoroAdapter",
    "OllamaAdapter",
    "PiperAdapter",
    "status_summary",
]


def status_summary(models_dir: Path | None) -> dict:
    """Probe every adapter. Cheap and safe to call on every UI refresh."""
    return {
        "ollama": OllamaAdapter().available().as_dict(),
        "piper": PiperAdapter(models_dir=models_dir).available().as_dict(),
        "kokoro": KokoroAdapter().available().as_dict(),
    }
