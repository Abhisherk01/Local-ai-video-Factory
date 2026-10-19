"""Kokoro TTS adapter - availability probe only in Phase 3 (ADR-010).

Kokoro (Apache-2.0) is the Phase 0 primary TTS candidate, but it drags
in the torch/onnxruntime ML stack. Piper ships as the working Phase 3
TTS because it is a 10 MB CLI. This module keeps Kokoro visible and
honest: the UI can show "detected / not installed", and attempting to
synthesize fails with a message that names the phase that wires it -
no silent pretending.
"""

from __future__ import annotations

import importlib.util

from laf.adapters.base import AdapterStatus, AdapterUnavailable


def _kokoro_spec():
    return importlib.util.find_spec("kokoro")


class KokoroAdapter:
    def available(self) -> AdapterStatus:
        installed = _kokoro_spec() is not None
        return AdapterStatus(
            name="kokoro",
            available=False,  # probe only - synthesis wiring lands in Phase 5
            detail=(
                "python package detected; synthesis wiring ships in Phase 5"
                if installed
                else "not installed (planned Phase 5; piper is the working TTS today)"
            ),
            extra={"package_detected": installed},
        )

    def synthesize(self, text: str, out_path, *, voice: str | None = None) -> dict:
        raise AdapterUnavailable(
            "kokoro synthesis is not wired yet (Phase 5); "
            "use the piper adapter or the fallback tone"
        )
