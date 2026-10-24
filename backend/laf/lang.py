"""Narration language support (0.4.10-multilang).

Single source of truth for everything language-aware in the factory.

Design contract:

- ``detect_language`` infers the narration language for an episode from
  its topic text. Devanagari presence wins, explicit "in hindi"-style
  hints come second, everything else stays English. Deliberately
  conservative: a false "hi" flips a whole script (and its captions)
  to Hindi, while a false "en" only costs an explicit ``language``
  field on the script request. A topic that merely MENTIONS Hindi
  ("Hindi cinema history") therefore stays English.
- Both system prompts speak the SAME 0.4.3 JSON contract
  ({"hook"/"body"/"cta"}), so script output keeps grammar-constrained
  decoding and the ``_script_from_json`` reassembly on every language.
  ``SCRIPT_SYSTEM_EN`` is byte-identical to the pre-0.4.10
  ``handlers._SCRIPT_SYSTEM`` - ``tests/test_multilang.py`` pins that
  byte-identity, because a prompt drift here silently downgrades the
  whole English path to pre-0.4.3 behaviour (the 0.4.10 rev1 field
  incident). ``SCRIPT_SYSTEM_HI`` asks for the same JSON shape with
  Devanagari-only string values; there is no few-shot example anywhere
  on the script path any more, so nothing can be parroted and no
  example-copier guard is needed.
- ``language_directive`` is the per-request instruction appended to the
  user prompt. English returns "" - the pre-0.4.10 prompt is unchanged.
- Audio vs. visuals: narration and burned captions follow the script
  language; storyboard SHOT descriptions are requested in English on
  purpose (they are planning metadata for the style compositor, not
  viewer-facing text). Voice discovery stays in ``laf.voices`` - the
  ``hi_IN-*`` catalog entries carry ``language`` metadata so the UI can
  group them honestly.
"""

from __future__ import annotations

import re

LANGUAGE_CODES = ("en", "hi")

_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (हिन्दी)",
}

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Explicit request hints (Latin script). Bare "hindi" is NOT a hint on
# purpose - "Hindi cinema" is a subject, not a language request.
_HI_HINTS = (
    "हिंदी",
    "in hindi",
    "hindi script",
    "hindi narration",
    "hindi language",
    "hindi mein",
    "write in hindi",
    "write hindi",
)

# Byte-identical to the pre-0.4.10 handlers._SCRIPT_SYSTEM (0.4.3 JSON
# contract). Pinned by tests/test_multilang.py against the live handler
# constant - if this equality ever breaks, the English path has drifted.
SCRIPT_SYSTEM_EN = (
    "You write short-form vertical video narration scripts. "
    'Output ONLY valid JSON: {"hook": <one attention-grabbing line that '
    'names the topic>, "body": <array of 3-5 short narration sentences>, '
    '"cta": <one closing line asking the viewer to follow>}. '
    "No markdown fences, no commentary, no notes."
)

# Same JSON contract, Hindi values. The keys stay Latin ("hook"/"body"/
# "cta" - what handlers._script_from_json reads); every STRING VALUE is
# requested in Devanagari. Grammar-constrained decoding (format:json)
# makes prose openers structurally impossible, exactly as on the
# English path - the Hindi risk is only the value language, which the
# prompt and the per-request directive both pin.
SCRIPT_SYSTEM_HI = (
    "आप हिंदी में छोटे वर्टिकल वीडियो नैरेशन स्क्रिप्ट लिखते हैं। "
    'Output ONLY valid JSON: {"hook": <विषय बताने वाली एक ध्यान खींचने '
    'वाली पंक्ति>, "body": <3-5 छोटे नैरेशन वाक्यों की सूची>, '
    '"cta": <दर्शक से फॉलो करने को कहने वाली एक पंक्ति>}. '
    "हर स्ट्रिंग शुद्ध हिंदी में, देवनागरी लिपि में हो - न कोई अंग्रेज़ी "
    "शब्द, न Hinglish, न लैटिन लिपि में हिंदी। संख्याएँ हिंदी शब्दों में "
    "लिखें। No markdown fences, no commentary, no notes."
)


def normalize_language(value: object) -> str | None:
    """Explicit language field -> clean code, or None if unset/unknown."""
    code = str(value or "").strip().lower()
    return code if code in LANGUAGE_CODES else None


def detect_language(text: str) -> str:
    """Infer the narration language from topic text. Never raises."""
    t = str(text or "")
    if _DEVANAGARI_RE.search(t):
        return "hi"
    low = t.lower()
    return "hi" if any(h in low for h in _HI_HINTS) else "en"


def language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(str(code or "").lower(), "English")


def language_directive(language: str) -> str:
    """Per-request instruction appended to the script prompt.

    "" for English keeps the pre-0.4.10 prompt byte-identical.
    """
    if str(language or "").lower() != "hi":
        return ""
    return (
        "\nIMPORTANT: Write the ENTIRE narration script in HINDI, "
        "using Devanagari script (देवनागरी) only. No English words and "
        "no Hinglish - never write Hindi in Latin letters. Spell out "
        "every number in Hindi words. Keep the Hindi simple, warm and "
        "spoken-style, so it sounds natural when read aloud."
    )
