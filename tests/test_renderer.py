"""Phase 5 renderer tests: pure units + one real-ffmpeg integration
render (skipped when ffmpeg is absent).

The integration render runs at quarter resolution (270x480) so the whole
suite stays fast; production renders at 1080x1920 through the exact same
code path.
"""

from __future__ import annotations

import shutil
import wave

import pytest

from laf import renderer

FFMPEG = shutil.which("ffmpeg")

SEEDED_SLUGS = [
    "dark_cinematic",
    "clean_product",
    "warm_documentary",
    "bold_motion",
    "retro_analog",
    "minimal_mono",
]


# ---------------------------------------------------------------------------
# pure units
# ---------------------------------------------------------------------------


def test_resolve_ffmpeg_or_none() -> None:
    # Either a path or None is honest; the handler turns None into
    # PrereqMissing. Just exercise it.
    result = renderer.resolve_ffmpeg()
    assert result is None or isinstance(result, str)


def test_palette_for_all_seeded_styles() -> None:
    palettes = {slug: renderer.palette_for(slug) for slug in SEEDED_SLUGS}
    assert len({p for p in palettes.values()}) == len(SEEDED_SLUGS)
    for top, bottom, _ in palettes.values():
        assert top.startswith("0x") and bottom.startswith("0x")


def test_palette_for_unknown_slug_falls_back() -> None:
    assert renderer.palette_for("no_such_style") == renderer.palette_for(
        "dark_cinematic"
    )


def test_split_caption_word_boundaries() -> None:
    lines = renderer.split_caption("one two three four five six seven", 12)
    assert all(len(line) <= 12 for line in lines)
    assert " ".join(lines) == "one two three four five six seven"


def test_split_caption_empty_and_single_word() -> None:
    assert renderer.split_caption("") == []
    assert renderer.split_caption("   ") == []
    assert renderer.split_caption("word") == ["word"]


def test_effective_duration_rules() -> None:
    assert renderer.effective_duration_s(1.0, None) == 2.0  # 2 s floor
    assert renderer.effective_duration_s(6.0, None) == 6.0  # estimate wins
    # spoken audio stretches the scene, never clips it
    assert renderer.effective_duration_s(2.0, 3.1) == 3.35
    assert renderer.effective_duration_s(5.0, 3.1) == 5.0  # estimate wins


def test_xfade_offsets_two_clips() -> None:
    offsets = renderer.xfade_offsets([4.0, 4.0], td=1.0)
    assert offsets == [3.0]


def test_xfade_offsets_three_clips_total_length() -> None:
    durations = [3.0, 4.0, 2.0]
    offsets = renderer.xfade_offsets(durations, td=0.4)
    assert offsets == [2.6, 6.2]
    total = sum(durations) - 0.4 * (len(durations) - 1)
    assert abs(total - 8.2) < 1e-9


def test_subtitle_events_proportional_and_inside_window() -> None:
    scenes = [
        {"narration": "short one", "duration_s": 2.0},
        {"narration": "a much longer narration line here", "duration_s": 4.0},
    ]
    durations = [2.0, 4.0]
    starts = renderer.scene_starts(durations, td=0.4)  # [0, 1.6]
    events = renderer.subtitle_events(scenes, durations, starts)
    assert events
    assert events[0][0] == 0.0
    # monotonic, no overlaps, everything inside the timeline
    for (a0, b0, t0), (a1, b1, t1) in zip(events, events[1:]):
        assert b0 <= a1 + 1e-6
        assert t0 and t1
    assert events[-1][1] <= 1.6 + 4.0 + 1e-6


def test_write_ass_contains_styles_and_events(tmp_path) -> None:
    path = tmp_path / "subs.ass"
    renderer.write_ass(
        path,
        [(0.0, 1.5, "hello {world}"), (1.5, 3.0, "second line")],
        "My Title",
        width=270,
        height=480,
    )
    text = path.read_text(encoding="utf-8")
    assert "[Script Info]" in text
    assert "PlayResX: 270" in text
    assert "Style: Title,Arial" in text
    assert "Style: Caption,Arial" in text
    # braces stripped so captions can never inject ASS override tags
    assert "hello (world)" in text
    assert text.count("Dialogue: 0,") == 3  # 1 title + 2 captions


def test_tone_wav_duration_exact(tmp_path) -> None:
    path = renderer.tone_wav(tmp_path / "tone.wav", 2.0)
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        frames = wav.getnframes()
    assert abs(frames / rate - 2.0) < 0.01


# ---------------------------------------------------------------------------
# real-ffmpeg integration (quarter resolution for speed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_render_episode_end_to_end_tone(tmp_path) -> None:
    scenes = [
        {"idx": 1, "narration": "Birds build nests with care.", "duration_s": 2.0},
        {"idx": 2, "narration": "Eggs hatch after weeks of warmth.", "duration_s": 2.4},
        {"idx": 3, "narration": "Fledglings learn to fly.", "duration_s": 2.0},
    ]
    out = tmp_path / "out.mp4"
    result = renderer.render_episode(
        FFMPEG,
        workdir=tmp_path / "work",
        out_path=out,
        title="Bird nests",
        style_slug="warm_documentary",
        scenes=scenes,
        audio_mode="tone",
        piper=None,
        width=270,
        height=480,
    )
    assert out.exists()
    assert out.stat().st_size > 1000
    assert result["method"] == "fallback_tone"
    assert result["scene_count"] == 3
    assert result["qc"]["ok"] is True
    expected = round(2.0 + 2.4 + 2.0 - 2 * renderer.TRANSITION_S, 2)
    assert abs(result["duration_s"] - expected) < 0.5
    # workdir cleaned up after render
    assert not (tmp_path / "work").exists()


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_render_qc_detects_wrong_dimensions(tmp_path) -> None:
    """QC must fail honestly when the probe target mismatches the plan."""
    scenes = [
        {"idx": 1, "narration": "Just one scene.", "duration_s": 2.0},
    ]
    out = tmp_path / "out.mp4"
    renderer.render_episode(
        FFMPEG,
        workdir=tmp_path / "work",
        out_path=out,
        title="Single",
        style_slug="dark_cinematic",
        scenes=scenes,
        audio_mode="tone",
        piper=None,
        width=270,
        height=480,
    )
    qc = renderer.qc_probe(out, 2.0, width=1080, height=1920)
    assert qc["ok"] is False
    names = {c["name"] for c in qc["checks"] if not c["ok"]}
    assert "width" in names and "height" in names