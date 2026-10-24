"""0.4.5 voice registry tests: catalog integrity, on-disk resolution,
route surface, and render-time voice threading.

The render test uses a FakePiper that records the kwargs it receives,
proving the voice/length_scale thread through render_episode without a
real piper install; ffmpeg render itself is skipped when absent (same
contract as test_renderer.py).
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest

from laf import renderer
from laf.voices import (
    AUTO_SLUG,
    CATALOG,
    catalog_summary,
    installed_voices,
    preset_for,
    resolve_voice_path,
    voices_dir,
)

FFMPEG = shutil.which("ffmpeg")


# ---------------------------------------------------------------------------
# catalog integrity
# ---------------------------------------------------------------------------


def test_catalog_shape_and_uniqueness() -> None:
    slugs = list(CATALOG)
    assert len(slugs) == len(set(slugs))
    assert len(slugs) == 12  # 10 English + 2 Hindi (0.4.10-multilang)
    genders = {m["gender"] for m in CATALOG.values()}
    assert genders == {"male", "female"}
    for slug, meta in CATALOG.items():
        assert (
            slug.startswith("en_US-")
            or slug.startswith("en_GB-")
            or slug.startswith("hi_IN-")
        ), slug
        assert meta["quality"] in {"low", "medium", "high"}
        ls = meta.get("length_scale")
        assert ls is None or 0.5 <= float(ls) <= 1.5
        assert meta["name"] and meta["description"]
        assert meta.get("language") in {"en", "hi"}
    # 0.4.10: language metadata is coherent with the slug prefix
    for slug, meta in CATALOG.items():
        expected = "hi" if slug.startswith("hi_IN-") else "en"
        assert meta["language"] == expected, slug


def test_custom_entry_language_from_slug(models_tmp: Path) -> None:
    """Non-catalog slugs get their language from the prefix, so a Hindi
    model downloaded before a catalog update still reports honestly."""
    (voices_dir(models_tmp) / "hi_IN-future-voice.onnx").write_bytes(b"f")
    (voices_dir(models_tmp) / "zz_unknown_voice.onnx").write_bytes(b"f")
    by_slug = {v["slug"]: v for v in installed_voices(models_tmp)}
    assert by_slug["hi_IN-future-voice"]["language"] == "hi"
    assert by_slug["zz_unknown_voice"]["language"] == "unknown"


# ---------------------------------------------------------------------------
# on-disk resolution
# ---------------------------------------------------------------------------


@pytest.fixture()
def models_tmp(tmp_path: Path) -> Path:
    vdir = voices_dir(tmp_path)
    vdir.mkdir(parents=True)
    return tmp_path


def test_resolve_auto_and_none_are_noop(models_tmp: Path) -> None:
    for slug in (None, "", AUTO_SLUG):
        assert resolve_voice_path(models_tmp, slug) is None


def test_resolve_specific_requires_file_on_disk(models_tmp: Path) -> None:
    assert resolve_voice_path(models_tmp, "en_US-ryan-high") is None
    onnx = voices_dir(models_tmp) / "en_US-ryan-high.onnx"
    onnx.write_bytes(b"fake")
    assert resolve_voice_path(models_tmp, "en_US-ryan-high") == onnx
    assert resolve_voice_path(models_tmp, "en_US-lessac-medium") is None


def test_installed_merges_catalog_and_flags_custom(models_tmp: Path) -> None:
    vdir = voices_dir(models_tmp)
    (vdir / "en_US-amy-medium.onnx").write_bytes(b"f")
    (vdir / "hi_IN-pratham-medium.onnx").write_bytes(b"f")
    (vdir / "my_custom_voice.onnx").write_bytes(b"f")
    voices = installed_voices(models_tmp)
    by_slug = {v["slug"]: v for v in voices}
    assert by_slug["en_US-amy-medium"]["name"] == "Amy"
    assert by_slug["en_US-amy-medium"]["custom"] is False
    assert by_slug["en_US-amy-medium"]["installed"] is True
    assert by_slug["hi_IN-pratham-medium"]["name"] == "Pratham"
    assert by_slug["hi_IN-pratham-medium"]["language"] == "hi"
    custom = by_slug["my_custom_voice"]
    assert custom["custom"] is True
    assert custom["name"] == "my_custom_voice"
    # deterministic order: English block first (female first), then
    # other languages (0.4.10), custom last
    assert voices[0]["slug"] == "en_US-amy-medium"
    assert voices[1]["slug"] == "hi_IN-pratham-medium"
    assert voices[-1]["slug"] == "my_custom_voice"


def test_catalog_summary_marks_installed(models_tmp: Path) -> None:
    (voices_dir(models_tmp) / "en_GB-alan-low.onnx").write_bytes(b"f")
    summary = catalog_summary(models_tmp)
    assert len(summary) == len(CATALOG)
    flags = {e["slug"]: e["installed"] for e in summary}
    assert flags["en_GB-alan-low"] is True
    assert flags["en_US-amy-medium"] is False


def test_preset_for_known_and_unknown() -> None:
    assert preset_for("en_US-ryan-high") == pytest.approx(1.05)
    assert preset_for("en_US-amy-medium") == pytest.approx(0.95)
    assert preset_for("hi_IN-pratham-medium") == pytest.approx(1.0)
    assert preset_for("hi_IN-priyamvada-medium") == pytest.approx(1.0)
    assert preset_for("my_custom_voice") is None
    assert preset_for("auto") is None
    assert preset_for(None) is None


def test_resolve_hindi_slug_requires_file_on_disk(models_tmp: Path) -> None:
    """0.4.10: a Hindi voice resolves exactly like an English one once
    its .onnx sits in the voices dir - the render path is language-agnostic."""
    assert resolve_voice_path(models_tmp, "hi_IN-pratham-medium") is None
    onnx = voices_dir(models_tmp) / "hi_IN-pratham-medium.onnx"
    onnx.write_bytes(b"fake")
    assert resolve_voice_path(models_tmp, "hi_IN-pratham-medium") == onnx


# ---------------------------------------------------------------------------
# route surface
# ---------------------------------------------------------------------------


def test_voices_route_shape(client) -> None:
    resp = client.get("/api/v1/voices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["voices"] == []  # fresh tmp data dir -> nothing installed
    assert len(body["catalog"]) == len(CATALOG)
    assert body["voices_dir"].endswith(str(Path("piper") / "voices"))


def test_render_rejects_unknown_voice_slug(client) -> None:
    ep = client.post(
        "/api/v1/episodes",
        json={"title": "t", "topic": "voice gate"},
    ).json()["episode"]
    resp = client.post(
        f"/api/v1/episodes/{ep['id']}/render",
        json={"voice_slug": "en_US-not-downloaded"},
    )
    assert resp.status_code == 400
    assert "not installed" in resp.json()["detail"]


def test_render_accepts_auto_without_storyboard(client) -> None:
    """auto passes voice validation; the pre-existing storyboard gate
    (400 'no storyboard yet') is what fires next - order preserved."""
    ep = client.post(
        "/api/v1/episodes",
        json={"title": "t", "topic": "gate order"},
    ).json()["episode"]
    resp = client.post(
        f"/api/v1/episodes/{ep['id']}/render",
        json={"voice_slug": "auto"},
    )
    assert resp.status_code == 400
    assert "storyboard" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# render-time threading (FakePiper + real ffmpeg, quarter resolution)
# ---------------------------------------------------------------------------


class FakePiper:
    """Records synthesize kwargs; writes a real wav so the render runs."""

    def __init__(self, tmp_path: Path) -> None:
        self.calls: list[dict] = []
        self._tmp = tmp_path

    def synthesize(self, text: str, out_path: Path, **kwargs) -> dict:
        self.calls.append({"text": text, **kwargs})
        renderer.tone_wav(Path(out_path), 1.0)
        return {"path": str(out_path)}

    def resolve_voice(self):  # adapter default resolution
        return self._tmp / "default_voice.onnx"


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_render_episode_threads_voice_and_length_scale(tmp_path) -> None:
    fake = FakePiper(tmp_path)
    scenes = [
        {"idx": 1, "narration": "First scene narration.", "duration_s": 2.0},
        {"idx": 2, "narration": "Second scene narration.", "duration_s": 2.0},
    ]
    voice = tmp_path / "en_US-ryan-high.onnx"
    voice.write_bytes(b"fake")
    result = renderer.render_episode(
        FFMPEG,
        workdir=tmp_path / "work",
        out_path=tmp_path / "out.mp4",
        title="Voiced",
        style_slug="dark_cinematic",
        scenes=scenes,
        audio_mode="piper",
        piper=fake,
        voice=voice,
        length_scale=1.05,
        width=270,
        height=480,
    )
    assert len(fake.calls) == 2
    assert fake.calls[0]["voice"] == voice
    assert fake.calls[0]["length_scale"] == pytest.approx(1.05)
    assert result["voice"] == "en_US-ryan-high"
    assert result["method"] == "local_piper"


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")
def test_render_episode_auto_voice_calls_piper_plain(tmp_path) -> None:
    """voice=None + length_scale=None must keep the pre-0.4.5 call shape
    (positional text/out only) and report the adapter's default voice."""
    fake = FakePiper(tmp_path)
    (tmp_path / "default_voice.onnx").write_bytes(b"fake")
    scenes = [
        {"idx": 1, "narration": "Only scene.", "duration_s": 2.0},
    ]
    result = renderer.render_episode(
        FFMPEG,
        workdir=tmp_path / "work",
        out_path=tmp_path / "out.mp4",
        title="Auto",
        style_slug="dark_cinematic",
        scenes=scenes,
        audio_mode="piper",
        piper=fake,
        width=270,
        height=480,
    )
    assert fake.calls == [{"text": "Only scene."}]
    assert result["voice"] == "default_voice"


def test_wav_duration_helper_reads_fake_wav(tmp_path) -> None:
    path = renderer.tone_wav(tmp_path / "t.wav", 1.0)
    with wave.open(str(path), "rb") as wav:
        assert wav.getframerate() == renderer.TONE_RATE
