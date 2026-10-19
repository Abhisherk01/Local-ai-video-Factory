"""Piper TTS adapter (Phase 3 working TTS path).

Piper is a tiny (~10 MB) MIT-licensed local TTS engine with a simple
CLI contract: `piper --model voice.onnx --output_file out.wav` with the
text on stdin. Phase 0 shortlisted Kokoro as primary TTS; Piper ships
first because it needs no Python ML stack - see ADR-010 for the honest
trade-off and where Kokoro lands (Phase 5).

Resolution order for the executable:
  1. LAF_PIPER env var (explicit path)
  2. <models_dir>/piper/piper.exe (Windows release zip layout) or
     <models_dir>/piper/piper
  3. `piper` on PATH

Resolution order for the voice model:
  1. LAF_PIPER_VOICE env var (explicit .onnx path)
  2. first *.onnx in <models_dir>/piper/voices (sorted)
  3. a .onnx sitting next to the executable
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from laf.adapters.base import AdapterStatus, AdapterUnavailable


class PiperAdapter:
    def __init__(
        self,
        models_dir: Path | None = None,
        exe: str | None = None,
        voice: str | None = None,
        timeout_s: float = 300.0,
    ) -> None:
        self.models_dir = Path(models_dir) if models_dir else None
        self._exe_override = exe or os.environ.get("LAF_PIPER")
        self._voice_override = voice or os.environ.get("LAF_PIPER_VOICE")
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    def resolve_exe(self) -> str | None:
        if self._exe_override:
            return self._exe_override if Path(self._exe_override).exists() else None
        if self.models_dir:
            for name in ("piper.exe", "piper"):
                candidate = self.models_dir / "piper" / name
                if candidate.exists():
                    return str(candidate)
        return shutil.which("piper")

    def resolve_voice(self) -> Path | None:
        if self._voice_override:
            p = Path(self._voice_override)
            return p if p.exists() else None
        if not self.models_dir:
            return None
        voices_dir = self.models_dir / "piper" / "voices"
        if voices_dir.is_dir():
            onnx = sorted(voices_dir.glob("*.onnx"))
            if onnx:
                return onnx[0]
        if self.models_dir and (self.models_dir / "piper").is_dir():
            onnx = sorted((self.models_dir / "piper").glob("*.onnx"))
            if onnx:
                return onnx[0]
        return None

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------

    def available(self) -> AdapterStatus:
        exe = self.resolve_exe()
        if not exe:
            return AdapterStatus(
                name="piper",
                available=False,
                detail=(
                    "piper executable not found (set LAF_PIPER, or unzip a "
                    "piper release into <models_dir>/piper, or add it to PATH)"
                ),
            )
        voice = self.resolve_voice()
        if not voice:
            return AdapterStatus(
                name="piper",
                available=False,
                detail=(
                    "piper executable found but no voice model (*.onnx) - "
                    "put one in <models_dir>/piper/voices or set LAF_PIPER_VOICE"
                ),
                extra={"exe": exe},
            )
        return AdapterStatus(
            name="piper",
            available=True,
            detail=f"ready ({Path(exe).name} + {voice.name})",
            extra={"exe": exe, "voice": str(voice)},
        )

    # ------------------------------------------------------------------
    # synthesis
    # ------------------------------------------------------------------

    def synthesize(self, text: str, out_path: Path, *, voice: Path | None = None) -> dict:
        """Render `text` to a WAV file. Raises AdapterUnavailable with a
        fix-it message when piper/voice are missing or the CLI fails."""
        exe = self.resolve_exe()
        if not exe:
            raise AdapterUnavailable("piper executable not found (see /api/v1/adapters)")
        voice_path = voice or self.resolve_voice()
        if not voice_path:
            raise AdapterUnavailable("no piper voice model (*.onnx) configured")

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [exe, "--model", str(voice_path), "--output_file", str(out_path)]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AdapterUnavailable(f"piper failed to run: {exc}") from exc
        if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 44:
            stderr = proc.stderr.decode("utf-8", "replace").strip()[:300]
            raise AdapterUnavailable(
                f"piper exited {proc.returncode} without usable audio"
                + (f": {stderr}" if stderr else "")
            )
        return {
            "path": str(out_path),
            "voice": str(voice_path),
            "bytes": out_path.stat().st_size,
            "method": "local_piper",
        }
