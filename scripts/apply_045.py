"""0.4.5-voices installer patch - run with the project venv:

    python scripts\\apply_045.py

Patches ONLY the three files that must not be wholesale-overwritten
because 0.4.3/0.4.4 changed them on your machine:

  1. backend/laf/jobs/handlers.py
     - threads the render voice through video_render + tts_render at
       anchored, byte-stable locations (the 0.4.3 script_gen block is
       NEVER touched - this patcher cannot regress the JSON-script
       anti-leak engine).
  2. backend/laf/__init__.py - sets __version__ = "0.4.5-voices".
  3. CHANGELOG.md - appends the 0.4.5 entry.

Rules: idempotent (safe to run twice), every insertion anchor must be
found EXACTLY ONCE or the script exits non-zero having changed nothing,
and handlers.py is byte-compiled after patching so an indentation slip
cannot reach your app. A backup copy of each file is left next to it
with a .bak_045 suffix the first time it is patched.
"""

from __future__ import annotations

import py_compile
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = "0.4.5-voices"


def fail(msg: str) -> None:
    print(f"[apply_045] ABORT: {msg}")
    sys.exit(1)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


def backup_once(path: Path) -> None:
    bak = path.with_name(path.name + ".bak_045")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[apply_045] backup: {bak.name}")


def insert_once(text: str, anchor: str, addition: str, label: str) -> str:
    count = text.count(anchor)
    if count == 0:
        # Idempotency: maybe this patch is already applied.
        if addition.strip() and addition.strip() in text:
            print(f"[apply_045] skip {label}: already applied")
            return text
        fail(f"anchor not found for {label}")
    if count > 1:
        fail(f"anchor found {count}x for {label} - refusing to guess")
    print(f"[apply_045] patch: {label}")
    return text.replace(anchor, anchor + addition, 1)


# ---------------------------------------------------------------------------
# 1. handlers.py - voice threading (video_render + tts_render)
# ---------------------------------------------------------------------------

VIDEO_PIPER_ANCHOR = (
    "    piper = PiperAdapter(models_dir=ctx.models_dir)\n"
    "    use_piper = piper.available().available\n"
)
VIDEO_PIPER_ADD = (
    "    voice_slug = str(payload.get(\"voice_slug\") or \"auto\")\n"
    "    voice_path = voices.resolve_voice_path(ctx.models_dir, voice_slug)\n"
    "    voice_scale = (\n"
    "        voices.preset_for(voice_slug) if voice_path is not None else None\n"
    "    )\n"
)

VIDEO_CALL_ANCHOR = (
    '        audio_mode="piper" if use_piper else "tone",\n'
    "        piper=piper if use_piper else None,\n"
    "        models_dir=ctx.models_dir,\n"
)
VIDEO_CALL_ADD = "        voice=voice_path,\n        length_scale=voice_scale,\n"

TTS_PIPER_ANCHOR = (
    "    text = _episode_script(ctx, job, payload)\n"
    "    piper = PiperAdapter(models_dir=ctx.models_dir)\n"
)
TTS_PIPER_ADD = (
    "    voice_slug = str(payload.get(\"voice_slug\") or \"auto\")\n"
    "    voice_path = voices.resolve_voice_path(ctx.models_dir, voice_slug)\n"
    "    voice_scale = (\n"
    "        voices.preset_for(voice_slug) if voice_path is not None else None\n"
    "    )\n"
)

TTS_CALL_ANCHOR = "    result = piper.synthesize(text, out)\n"
TTS_CALL_NEW = (
    "    result = piper.synthesize(\n"
    "        text, out, voice=voice_path, length_scale=voice_scale\n"
    "    )\n"
)

IMPORT_ANCHOR = "from laf import renderer\n"
IMPORT_ADD = "from laf import voices\n"


def patch_handlers() -> None:
    path = REPO / "backend" / "laf" / "jobs" / "handlers.py"
    text = read(path)
    backup_once(path)

    if "voice_slug" in text:
        print("[apply_045] skip handlers.py: voice_slug already present")
    else:
        text = insert_once(text, IMPORT_ANCHOR, IMPORT_ADD, "handlers import voices")
        text = insert_once(
            text, VIDEO_PIPER_ANCHOR, VIDEO_PIPER_ADD, "video_render voice resolve"
        )
        text = insert_once(
            text, VIDEO_CALL_ANCHOR, VIDEO_CALL_ADD, "video_render voice args"
        )
        text = insert_once(
            text, TTS_PIPER_ANCHOR, TTS_PIPER_ADD, "tts_render voice resolve"
        )
        if text.count(TTS_CALL_ANCHOR) != 1:
            fail("tts synthesize anchor not found exactly once")
        print("[apply_045] patch: tts_render synthesize args")
        text = text.replace(TTS_CALL_ANCHOR, TTS_CALL_NEW, 1)

        path.write_text(text, encoding="utf-8")

    # Prove the result is valid Python before anyone restarts the app.
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        fail(f"handlers.py does not compile after patch: {exc}")
    print("[apply_045] ok: handlers.py compiles")


# ---------------------------------------------------------------------------
# 2. __init__.py - version bump
# ---------------------------------------------------------------------------


def patch_version() -> None:
    path = REPO / "backend" / "laf" / "__init__.py"
    text = read(path)
    backup_once(path)
    new_text, n = re.subn(
        r'__version__\s*=\s*"[^"]*"',
        f'__version__ = "{VERSION}"',
        text,
        count=1,
    )
    if n != 1:
        fail("__version__ assignment not found in backend/laf/__init__.py")
    if new_text == text:
        print(f"[apply_045] skip __init__.py: already {VERSION}")
    else:
        path.write_text(new_text, encoding="utf-8")
        print(f"[apply_045] patch: __version__ -> {VERSION}")


# ---------------------------------------------------------------------------
# 3. CHANGELOG.md - append the 0.4.5 entry
# ---------------------------------------------------------------------------

CHANGELOG_ENTRY = """## 0.4.5 - Voices: per-episode narration voice picker

### Added
- Piper voice registry (`laf.voices`): ten curated, download-verified
  en_US/en_GB voices (5 female, 5 male) with honest metadata and a
  per-voice delivery preset (`length_scale` speech-rate dial - piper
  has no native emotion parameter; pace/voice choice is the honest
  lever). Custom on-disk voices are listed too, flagged `custom`.
- `GET /api/v1/voices` (installed voices + catalog + voices_dir).
- Render requests accept `voice_slug`; the UI gained a per-episode
  voice picker next to the style picker. `auto` (the default) keeps
  the pre-0.4.5 behaviour byte-identical. Unknown slugs are rejected
  at enqueue with a 400 - no burned job attempts.
- Render results record the voice actually used (`voice` field);
  the Pipeline mp4 line and job rows surface it.
- `scripts/add_voice.ps1`: downloads any catalog voice (both .onnx and
  .onnx.json) from rhasspy/piper-voices v1.0.0 into
  `<models_dir>/piper/voices/`, e.g. `scripts\\add_voice.ps1 ryan`.
- `video_render` + `tts_render` resolve the voice at run time from the
  job payload; a vanished voice file falls back to the adapter default
  and the result says which voice was used.
"""


def patch_changelog() -> None:
    path = REPO / "CHANGELOG.md"
    text = read(path)
    if "## 0.4.5" in text:
        print("[apply_045] skip CHANGELOG.md: 0.4.5 entry already present")
        return
    backup_once(path)
    path.write_text(text.rstrip("\n") + "\n\n" + CHANGELOG_ENTRY, encoding="utf-8")
    print("[apply_045] patch: CHANGELOG.md 0.4.5 entry appended")


def main() -> int:
    print(f"[apply_045] repo: {REPO}")
    patch_handlers()
    patch_version()
    patch_changelog()
    print("[apply_045] DONE - all three files patched (idempotent).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
