# 0.4.10-multilang - Hindi + English narration

Hindi and English narration end to end: Hindi scripts from Ollama, real
Hindi voices in Piper, and Devanagari-safe burned captions. English
behaviour is byte-identical to 0.4.8 - nothing about your existing
episodes changes.

## Quick start (Hindi episode)

1. Apply the patch (`python apply_0410b.py` - see INSTALL.txt).
2. Restart the backend (Ctrl+C the dev session and start it again, or
   relaunch the desktop app).
3. Create a new episode. Write the topic in Hindi, e.g.:
   `तितली के जीवन चक्र पर 60 सेकंड की वीडियो`
   ...or include an explicit request like `write in hindi` in the topic.
   Devanagari in the topic is detected automatically - no setting to flip.
4. Click **Script**. The narration comes back in Hindi (Devanagari).
5. Click **Storyboard**, then **Render**. In the voice dropdown pick:
   - **Pratham** (hi_IN-pratham-medium, male), or
   - **Priyamvada** (hi_IN-priyamvada-medium, female)
6. The rendered MP4 has Hindi narration + Devanagari captions.

English episodes: keep writing topics in English and pick any of the 10
English voices. Nothing to configure.

## How the language is decided

| Signal | Priority |
|---|---|
| `language` field on the script request (API/UI when available) | 1 |
| Devanagari characters anywhere in the topic | 2 |
| Explicit hints in the topic ("in hindi", "hindi mein", "write in hindi", "हिंदी") | 3 |
| Everything else | English |

A topic that merely MENTIONS Hindi ("Hindi cinema history") stays
English - only explicit requests or Devanagari text flip the language.

The job result records the language actually used (`"language": "hi"`),
so the queue history stays honest.

## Voices

| Short name | Slug | Language | Voice |
|---|---|---|---|
| pratham | hi_IN-pratham-medium | Hindi | male, clear natural read |
| priyamvada | hi_IN-priyamvada-medium | Hindi | female, warm classic read |
| ryan | en_US-ryan-high | English | male, deep trailer read |
| ... | (8 more) | English | amy, lessac, kathleen, kristin, harper, joe, norman, marcus, alan |

Both Hindi voices are bundled inside this patch and installed into
`<models_dir>\piper\voices\`. They also appear automatically in the
Render voice dropdown (grouped after the English voices). If you ever
need to re-download them: `.\scripts\add_voice.ps1 pratham`.

## Captions

Burned captions switch to **Noto Sans Devanagari** automatically when
the text contains Devanagari (the font ships inside the patch and is
staged next to the subtitles for libass - no system font install).
English captions keep using Arial exactly as before. Shot descriptions
in the storyboard are still written in English on purpose - they are
planning metadata for the style compositor, not viewer-facing text.

## Known limits (honest list)

- **Hindi quality depends on the Ollama model.** qwen3:4b writes usable
  spoken Hindi; if a generation comes back in Hinglish (Latin script),
  just re-run Script - the retry re-rolls the sampler. A bigger model
  produces cleaner Hindi if your machine can carry it.
- **No-voice / BGM episodes are NOT in this patch.** The "coffee making,
  no voice just bgm" idea needs a skip-TTS + music-bed mode (planned
  0.4.11).
- **Meta-chatter detection is English-tuned.** The anti-planning guard
  knows English leak patterns; a Hindi generation that leaks planning
  chatter in Hindi may pass through - regenerate if a script looks like
  planning text.
- The voice dropdown shows Hindi voices only after the patch is applied
  and the backend restarted.

## Rollback

    python apply_0410b.py --rollback

Every replaced file is in `backups_0410b\` with a manifest. The Hindi
voices and fonts are plain files - delete them manually if you want the
models dir pristine.
