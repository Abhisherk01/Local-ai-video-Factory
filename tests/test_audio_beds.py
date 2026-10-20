"""Phase 6a bed tests: procedural generators, resolution precedence,
and one real-ffmpeg mix (skipped when ffmpeg is absent).

The mix test runs at 320x180 / 3 s so the suite stays fast; production
beds mix onto the full 1080x1920 render through the exact same code
path.
"""

from __future__ import annotations

import math
import shutil
import wave

import pytest

from laf import renderer

FFMPEG = shutil.which("ffmpeg")


def _rms(path) -> float:
    with wave.open(str(path), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
    vals = []
    for i in range(0, len(frames), 2):
        vals.append(int.from_bytes(frames[i : i + 2], "little", signed=True))
    return math.sqrt(sum(v * v for v in vals) / len(vals)) / 32768.0


@pytest.mark.parametrize("kind", ["drone", "pad", "wind", "rain"])
def test_generate_bed_format_length_level(tmp_path, kind):
    p = renderer.generate_bed(kind, tmp_path / "bed.wav")
    with wave.open(str(p), "rb") as wav:
        assert wav.getnchannels() == 2
        assert wav.getframerate() == renderer.BED_RATE
        dur = wav.getnframes() / wav.getframerate()
    assert 11.9 <= dur <= 12.1
    assert _rms(p) > 0.01, f"{kind} bed is silent"


def test_generate_bed_unknown_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        renderer.generate_bed("thunder", tmp_path / "x.wav")


def test_resolve_bed_owner_file_precedence(tmp_path):
    models = tmp_path / "models"
    beds = models / "audio" / "beds"
    beds.mkdir(parents=True)
    (beds / "dark_cinematic.wav").write_bytes(b"not really audio")
    label, path = renderer.resolve_bed("dark_cinematic", models, tmp_path)
    assert label == "file:dark_cinematic.wav"
    assert path.name == "dark_cinematic.wav"


def test_resolve_bed_procedural_and_none(tmp_path):
    label, path = renderer.resolve_bed(
        "warm_documentary", tmp_path / "models", tmp_path
    )
    assert label == "procedural:wind"
    assert path.exists() and path.name == "bed.wav"
    # minimal_mono intentionally has no bed; unknown slugs get none.
    assert renderer.resolve_bed("minimal_mono", tmp_path, tmp_path) is None
    assert renderer.resolve_bed("unknown_slug", tmp_path, tmp_path) is None
    assert renderer.resolve_bed("warm_documentary", None, tmp_path) is None


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")
def test_mix_bed_real_ffmpeg(tmp_path):
    tone = renderer.tone_wav(tmp_path / "tone.wav", 3.0)
    clip = renderer.render_scene_clip(
        FFMPEG, tmp_path, 1,
        renderer.PALETTES["dark_cinematic"], 3.0, tone,
        width=320, height=180,
    )
    bed = renderer.generate_bed("drone", tmp_path / "bed.wav")
    out = tmp_path / "out.mp4"
    renderer.mix_bed(FFMPEG, clip, bed, out, 3.0)
    qc = renderer.qc_probe(out, 3.0, width=320, height=180)
    by_name = {c["name"]: c for c in qc["checks"]}
    assert by_name["width"]["ok"] and by_name["height"]["ok"]
    assert by_name["duration"]["ok"], by_name["duration"]["detail"]
    assert by_name["audio_stream"]["ok"]
    assert by_name["audio_level"]["ok"], by_name["audio_level"]["detail"]
