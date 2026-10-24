"""Piper voice registry (0.4.5-voices).

A "voice" is one piper acoustic model: ``<slug>.onnx`` plus its
``<slug>.onnx.json`` sidecar inside ``<models_dir>/piper/voices/``. The
slug is the filename stem, which is also the Hugging Face convention
(rhasspy/piper-voices), so a downloaded file works without renaming.

Design contract (mirrors the style registry and the honest-fallback
rules from ADR-010):

- ``auto`` (or no slug at all) is byte-identical to the pre-0.4.5
  behaviour: the adapter resolves its default voice (LAF_PIPER_VOICE
  env override, else the first ``*.onnx`` sorted). Renders queued
  without a voice choice cannot change how the factory sounds.
- A specific slug resolves to exactly one file. The render route
  validates the file exists at enqueue time (fast 400 feedback, no
  burned attempts); the handler re-resolves at run time and falls back
  to the adapter default if the file vanished mid-queue (the job result
  records the voice actually used).
- ``length_scale`` is piper's speech-rate dial (>1 = slower, more
  measured/grave; <1 = faster, more energetic). It is the only honest
  "delivery" control piper has - voices are fixed-speaker models with
  no native emotion parameter, so depth/pace presets are curated per
  voice instead of pretended.
- Voices present on disk but absent from CATALOG are still listed and
  usable (``custom: true``) - the registry never hides an installed
  model.

The catalog below was each verified against the rhasspy/piper-voices
v1.0.0 release (both files exist); the ``scripts/add_voice.ps1`` helper
downloads them by short name.

0.4.10-multilang: entries carry a ``language`` code ("en"/"hi") so the
UI can group voices honestly; custom (non-catalog) slugs get their
language from the slug prefix. The two ``hi_IN`` voices are the official
Piper Hindi models (espeak "hi" phonemes), so a Hindi voice requires a
Devanagari script - generate the episode with language "hi" first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# slug -> metadata. name/gender/quality/description are UI labels;
# length_scale is applied at synthesis time when the voice is used.
# language (0.4.10) is the narration language the voice can read.
CATALOG: dict[str, dict[str, Any]] = {
    # -- hindi (0.4.10-multilang) ---------------------------------------
    "hi_IN-priyamvada-medium": {
        "name": "Priyamvada",
        "gender": "female",
        "quality": "medium",
        "description": "Hindi narrator - warm, classic female read",
        "length_scale": 1.0,
        "language": "hi",
    },
    "hi_IN-pratham-medium": {
        "name": "Pratham",
        "gender": "male",
        "quality": "medium",
        "description": "Hindi narrator - clear, natural male read",
        "length_scale": 1.0,
        "language": "hi",
    },
    # -- female ---------------------------------------------------------
    "en_US-amy-medium": {
        "name": "Amy",
        "gender": "female",
        "quality": "medium",
        "description": "warm, friendly narrator",
        "length_scale": 0.95,
        "language": "en",
    },
    "en_US-lessac-medium": {
        "name": "Lessac",
        "gender": "female",
        "quality": "medium",
        "description": "clear, neutral broadcast read",
        "length_scale": 1.0,
        "language": "en",
    },
    "en_US-kathleen-low": {
        "name": "Kathleen",
        "gender": "female",
        "quality": "low",
        "description": "soft, close-mic calm (16 kHz source)",
        "length_scale": 1.0,
        "language": "en",
    },
    "en_US-kristin-medium": {
        "name": "Kristin",
        "gender": "female",
        "quality": "medium",
        "description": "bright, upbeat energy",
        "length_scale": 0.92,
        "language": "en",
    },
    "en_US-hfc_female-medium": {
        "name": "Harper",
        "gender": "female",
        "quality": "medium",
        "description": "steady, documentary composure",
        "length_scale": 1.0,
        "language": "en",
    },
    # -- male -----------------------------------------------------------
    "en_US-ryan-high": {
        "name": "Ryan",
        "gender": "male",
        "quality": "high",
        "description": "deep, measured trailer read",
        "length_scale": 1.05,
        "language": "en",
    },
    "en_US-joe-medium": {
        "name": "Joe",
        "gender": "male",
        "quality": "medium",
        "description": "gritty baritone, gritty texture",
        "length_scale": 1.08,
        "language": "en",
    },
    "en_US-norman-medium": {
        "name": "Norman",
        "gender": "male",
        "quality": "medium",
        "description": "solid, authoritative delivery",
        "length_scale": 1.05,
        "language": "en",
    },
    "en_US-hfc_male-medium": {
        "name": "Marcus",
        "gender": "male",
        "quality": "medium",
        "description": "warm mid-baritone",
        "length_scale": 1.02,
        "language": "en",
    },
    "en_GB-alan-low": {
        "name": "Alan",
        "gender": "male",
        "quality": "low",
        "description": "gentle British read (16 kHz source)",
        "length_scale": 1.0,
        "language": "en",
    },
}

VOICES_SUBDIR = Path("piper") / "voices"
AUTO_SLUG = "auto"


def voices_dir(models_dir: str | Path | None) -> Path:
    """Directory holding piper voice models for this session."""
    return Path(models_dir) / VOICES_SUBDIR if models_dir else Path()


def _slug_language(slug: str) -> str:
    """Best-effort language from the slug prefix (HuggingFace layout)."""
    if slug.startswith("hi_IN-") or slug.startswith("hi-"):
        return "hi"
    if slug.startswith("en_") or slug.startswith("en-"):
        return "en"
    return "unknown"


def _entry(slug: str, *, installed: bool) -> dict[str, Any]:
    meta = CATALOG.get(slug)
    if meta is None:
        return {
            "slug": slug,
            "name": slug,
            "gender": "unknown",
            "quality": "unknown",
            "description": "custom installed voice (not in catalog)",
            "length_scale": None,
            "language": _slug_language(slug),
            "custom": True,
            "installed": installed,
        }
    return {
        "slug": slug,
        "name": meta["name"],
        "gender": meta["gender"],
        "quality": meta["quality"],
        "description": meta["description"],
        "length_scale": meta.get("length_scale"),
        "language": meta.get("language") or _slug_language(slug),
        "custom": False,
        "installed": installed,
    }


def installed_voices(models_dir: str | Path | None) -> list[dict[str, Any]]:
    """Every usable voice on disk, catalog metadata merged in.

    Order: English catalog first then other languages (within each
    language female before male, alphabetical by display name), custom
    (non-catalog) voices last by slug. Deterministic for the UI
    dropdown; 0.4.10 adds the language group so Hindi voices do not
    hide inside the English block.
    """
    found: list[dict[str, Any]] = []
    vdir = voices_dir(models_dir)
    if vdir.is_dir():
        for onnx in sorted(vdir.glob("*.onnx")):
            found.append(_entry(onnx.stem, installed=True))

    _LANG_RANK = {"en": 0, "hi": 1}

    def sort_key(entry: dict[str, Any]) -> tuple[int, int, str, str]:
        if entry["custom"]:
            return (2, 0, entry["slug"], "")
        gender_rank = 0 if entry["gender"] == "female" else 1
        lang_rank = _LANG_RANK.get(entry.get("language", "en"), 2)
        return (lang_rank, gender_rank, entry["name"], entry["slug"])

    return sorted(found, key=sort_key)


def resolve_voice_path(
    models_dir: str | Path | None, slug: str | None
) -> Path | None:
    """Resolve a voice slug to its .onnx path.

    ``None``/""/``auto`` -> None (caller keeps the adapter default -
    the pre-0.4.5 behaviour). A known slug returns the path only if the
    file actually exists; anything else returns None so callers can
    give fast, honest feedback instead of failing inside a job.
    """
    clean = str(slug or "").strip()
    if not clean or clean == AUTO_SLUG:
        return None
    path = voices_dir(models_dir) / f"{clean}.onnx"
    return path if path.exists() else None


def preset_for(slug: str | None) -> float | None:
    """Delivery preset (length_scale) for a catalog voice; None otherwise."""
    meta = CATALOG.get(str(slug or "").strip())
    value = meta.get("length_scale") if meta else None
    return float(value) if value is not None else None


def catalog_summary(models_dir: str | Path | None) -> list[dict[str, Any]]:
    """The full curated catalog with an installed flag per entry.

    Powers the "how to add more voices" story: the UI can show which
    catalog voices are NOT yet downloaded (scripts/add_voice.ps1).
    Sorted like installed_voices: English block, then other languages.
    """
    vdir = voices_dir(models_dir)
    installed_slugs = {p.stem for p in vdir.glob("*.onnx")} if vdir.is_dir() else set()
    entries = [_entry(slug, installed=slug in installed_slugs) for slug in CATALOG]
    _LANG_RANK = {"en": 0, "hi": 1}
    return sorted(
        entries,
        key=lambda e: (
            _LANG_RANK.get(e.get("language", "en"), 2),
            0 if e["gender"] == "female" else 1,
            e["name"],
        ),
    )
