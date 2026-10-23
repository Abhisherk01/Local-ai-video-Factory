"""Phase 5 video renderer: storyboard scenes -> one vertical MP4.

The storyboard scene rows (ADR-011) are the render contract: each scene
carries the narration slice, the composed visual prompt, and an honest
duration estimate. The renderer consumes them one by one:

  1. per-scene narration -> WAV (piper when installed, an honest tone
     placeholder otherwise - never passed off as speech)
  2. per-scene visual card: a style-palette gradient rendered by ffmpeg's
     lavfi `gradients` source (SDXL/photoreal visuals are explicitly
     deferred - owner-approved Phase 0 decision)
  3. clips joined with crossfade transitions; timed captions burned via
     libass (subtitle timing is derived from the narration itself)
  4. QC probe (ffprobe + volumedetect) - the roadmap Phase 5 gate:
     duration, aspect, audio presence and level

Zero new Python dependencies: everything is stdlib + the ffmpeg/ffprobe
binaries. Windows path-escaping pitfalls are avoided by running every
ffmpeg call with cwd=workdir and referencing `subs.ass` relatively.
"""

from __future__ import annotations

import array
import json
import math
import random
import re
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

WIDTH = 1080
HEIGHT = 1920
FPS = 30
TRANSITION_S = 0.4
CAPTION_MAX_CHARS = 38
TONE_RATE = 22050

# slug -> (top colour, bottom colour, unused accent) as ffmpeg 0xRRGGBB.
# Covers the six seeded registry styles; unknown slugs fall back to the
# dark_cinematic palette so a custom style still renders (honestly, with
# the default look) instead of crashing the job.
PALETTES: dict[str, tuple[str, str, str]] = {
    "dark_cinematic": ("0x14141E", "0x050508", "0xF0F0F8"),
    "clean_product": ("0xF7F9FC", "0xD9DFEA", "0x16181D"),
    "warm_documentary": ("0x40270F", "0x160C04", "0xF5E6C4"),
    "bold_motion": ("0x2D00E0", "0x12004A", "0xFFFFFF"),
    "retro_analog": ("0x4A3A28", "0x1C140C", "0xF0E4CC"),
    "minimal_mono": ("0x1C1C1C", "0x0A0A0A", "0xFAFAFA"),
}


def resolve_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def resolve_ffprobe() -> str | None:
    return shutil.which("ffprobe")


def palette_for(slug: str) -> tuple[str, str, str]:
    return PALETTES.get(str(slug), PALETTES["dark_cinematic"])


# ---------------------------------------------------------------------------
# music / ambience beds (Phase 6a)
# ---------------------------------------------------------------------------

# Owner channel-audio brief: narration stays clear, the bed sits well
# under the voice, ambience matches the channel. Beds key off the
# EXISTING per-episode style dropdown: a builtin style maps to a
# procedural bed generated as a 12 s stereo loop (stdlib only, seeded ->
# reproducible). Dropping a properly licensed audio file named
# <style_slug>.wav/.mp3/... into <models_dir>/audio/beds/ takes
# precedence. minimal_mono intentionally has no bed (silence is the
# aesthetic); unknown slugs get no bed. Beds only run under real
# narration (audio_mode == "piper") - never under the tone placeholder.
# No bed file + unmapped slug = byte-identical old behaviour (the same
# honest-fallback contract as the tone placeholder).
BED_GAIN_DB = -18.0
BED_RATE = 44100
BED_LOOP_S = 12.0
BED_SEAM_S = 0.15

STYLE_BEDS: dict[str, str] = {
    "dark_cinematic": "drone",   # low tense drone - moody / suspense
    "warm_documentary": "wind",  # soft outdoor air - nature / educational
    "clean_product": "pad",      # subtle modern pad - facts / product
    "bold_motion": "pad",        # quiet bed under kinetic cuts
    "retro_analog": "rain",      # film-era ambience
}

_BED_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".flac")


def _bed_write(path: Path, samples: array.array) -> Path:
    """Write mono samples as a 16-bit stereo wav at BED_RATE."""
    stereo = array.array("h", bytes(4 * len(samples)))
    stereo[0::2] = samples
    stereo[1::2] = samples
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(BED_RATE)
        wav.writeframes(stereo.tobytes())
    return path


def _seam_dip(samples: array.array, fade_s: float = BED_SEAM_S) -> array.array:
    """Fade the loop head/tail down so a noise loop never clicks at the
    wrap point. At bed gain this reads as a breath, not a dip."""
    n = min(len(samples), int(BED_RATE * fade_s))
    for i in range(n):
        w = i / float(n)
        samples[i] = int(samples[i] * w)
        samples[-1 - i] = int(samples[-1 - i] * w)
    return samples


def _sine_bed(
    freqs: list[tuple[float, float]], lfo_hz: float, lfo_depth: float
) -> array.array:
    """Seamless sine-stack loop: every frequency (partials AND the LFO)
    must complete an integer number of cycles per BED_LOOP_S, i.e. be
    k / BED_LOOP_S Hz. 55/110/165/220/330 and 0.25 / (1/12) all are."""
    n = int(BED_RATE * BED_LOOP_S)
    acc = [0.0] * n
    for k, (f, a) in enumerate(freqs):
        phase0 = 2.0 * math.pi * (k / 3.0)  # per-partial LFO phase offset
        for i in range(n):
            t = i / BED_RATE
            lfo = 1.0 - lfo_depth / 2.0 + (lfo_depth / 2.0) * math.sin(
                2.0 * math.pi * lfo_hz * t + phase0
            )
            acc[i] += a * lfo * math.sin(2.0 * math.pi * f * t)
    peak = max(1e-9, max(abs(v) for v in acc))
    g = 0.30 / peak
    return array.array("h", [int(v * g * 32767) for v in acc])


def _noise_bed(
    kind: str, lowpass: float, white_mix: float, gust_depth: float
) -> array.array:
    """Looped filtered-noise bed (wind = dark leaky integrator, rain =
    brighter with a little white shimmer). Gust LFO is 0.25 Hz = 3
    cycles per loop, so it is loop-seamless too. Seeded per kind."""
    rnd = random.Random(kind)
    n = int(BED_RATE * BED_LOOP_S)
    y = 0.0
    out = array.array("h")
    for i in range(n):
        w = rnd.random() * 2.0 - 1.0
        y += lowpass * (w - y)
        t = i / BED_RATE
        lfo = 1.0 - gust_depth / 2.0 + (gust_depth / 2.0) * math.sin(
            2.0 * math.pi * 0.25 * t
        )
        v = (1.0 - white_mix) * y + white_mix * w
        out.append(int(v * lfo * 0.30 * 32767))
    return out


def generate_bed(kind: str, out_path: Path) -> Path:
    """Generate a 12 s ambience loop for `kind` (original audio, zero
    licensing concerns). Sine beds are mathematically seamless; noise
    beds get a seam dip instead."""
    if kind in ("drone", "pad"):
        if kind == "drone":
            samples = _sine_bed(
                [(55.0, 0.50), (110.0, 0.30), (165.0, 0.15)],
                lfo_hz=0.25, lfo_depth=0.6,
            )
        else:
            samples = _sine_bed(
                [(110.0, 0.40), (220.0, 0.25), (330.0, 0.12)],
                lfo_hz=1.0 / 12.0, lfo_depth=0.8,
            )
    elif kind == "wind":
        samples = _seam_dip(
            _noise_bed("wind", lowpass=0.05, white_mix=0.0, gust_depth=0.9)
        )
    elif kind == "rain":
        samples = _seam_dip(
            _noise_bed("rain", lowpass=0.30, white_mix=0.15, gust_depth=0.3)
        )
    else:
        raise ValueError(f"unknown bed kind: {kind}")
    return _bed_write(out_path, samples)


def resolve_bed(
    style_slug: str, models_dir: Path | None, workdir: Path
) -> tuple[str, Path] | None:
    """Pick the bed for an episode: an owner-dropped file named
    <style_slug>.<ext> in <models_dir>/audio/beds/ wins, else the
    style's procedural bed is generated into the render workdir, else
    None (no bed)."""
    if models_dir is None:
        return None
    slug = str(style_slug)
    beds = Path(models_dir) / "audio" / "beds"
    if beds.is_dir():
        for ext in _BED_EXTS:
            candidate = beds / f"{slug}{ext}"
            if candidate.exists():
                return (f"file:{candidate.name}", candidate)
    kind = STYLE_BEDS.get(slug)
    if kind is None:
        return None
    path = Path(workdir) / "bed.wav"
    generate_bed(kind, path)
    return (f"procedural:{kind}", path)


def mix_bed(
    ffmpeg: str,
    video_path: Path,
    bed_path: Path,
    out_path: Path,
    total_s: float,
    *,
    gain_db: float = BED_GAIN_DB,
) -> Path:
    """Loop `bed_path` under the finished video and re-mux in place.

    The video stream is stream-copied (fast); only audio re-encodes.
    The bed is trimmed to the video length, attenuated by gain_db,
    faded in/out, then summed under the voice with amerge+pan - a
    version-proof pair that avoids amix's newer normalize option. The
    voice path passes through at unity gain: narration loudness is
    untouched, only the bed level is set.
    """
    out_path = Path(out_path)
    out_tmp = out_path.with_name(out_path.stem + "_bedtmp.mp4")
    fade_out_start = max(0.0, float(total_s) - 2.5)
    fc = (
        f"[1:a]atrim=0:{float(total_s):.3f},volume={gain_db}dB,"
        f"afade=t=in:d=2.0,afade=t=out:st={fade_out_start:.2f}:d=2.5[bed];"
        f"[0:a][bed]amerge=inputs=2,pan=stereo|c0=c0+c2|c1=c1+c3[aout]"
    )
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(bed_path),
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-ar", "44100", "-ac", "2",
        str(out_tmp),
    ]
    _run(cmd, what="bed mix")
    shutil.move(str(out_tmp), str(out_path))
    return out_path



# ---------------------------------------------------------------------------
# audio helpers
# ---------------------------------------------------------------------------


def tone_wav(
    path: Path, seconds: float, freq: float = 220.0, rate: int = TONE_RATE
) -> Path:
    """Write a sine-tone WAV of exactly `seconds` (250 ms fade-out).

    Same honest-placeholder contract as the tts_fallback handler: the
    render pipeline must be provable before any voice model exists.
    """
    total = max(1, int(rate * seconds))
    fade = min(total, int(rate * 0.25))
    frames = bytearray()
    for i in range(total):
        amp = 0.2
        if i > total - fade:
            amp *= (total - i) / fade
        sample = int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", sample)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return path


def wav_duration_s(path: Path) -> float:
    """Exact duration of a PCM wav via the stdlib wave module."""
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate() or 1
        return wav.getnframes() / float(rate)


def effective_duration_s(planned: float, spoken_s: float | None) -> float:
    """Video seconds for one scene.

    Never shorter than the storyboard estimate (2 s floor lives there,
    re-applied defensively here) and never clipping real speech: when a
    piper wav runs longer than estimated, the scene stretches by the
    difference plus a 0.25 s tail. Subtitles are derived from the same
    numbers, so picture and captions never drift apart.
    """
    base = max(2.0, float(planned))
    if spoken_s is None:
        return round(base, 2)
    return round(max(base, float(spoken_s) + 0.25), 2)


# ---------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------


def split_caption(text: str, max_chars: int = CAPTION_MAX_CHARS) -> list[str]:
    """Split narration into caption-sized chunks at word boundaries."""
    words = str(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def xfade_offsets(durations: list[float], td: float = TRANSITION_S) -> list[float]:
    """xfade offset for each transition (n-1 of them for n clips).

    off[0] = d0 - td; off[i] = off[i-1] + d_i - td. The final timeline
    length is sum(durations) - td*(n-1); scene i becomes visible at
    starts[i] = 0 for i == 0 else offsets[i-1] (where its crossfade in
    begins and where its audio slot starts too).
    """
    offsets: list[float] = []
    off = 0.0
    for i in range(len(durations) - 1):
        off = (durations[i] - td) if i == 0 else off + durations[i] - td
        offsets.append(round(max(0.0, off), 3))
    return offsets


def scene_starts(durations: list[float], td: float = TRANSITION_S) -> list[float]:
    offsets = xfade_offsets(durations, td)
    return [0.0] + offsets


def subtitle_events(
    scenes: list[dict[str, Any]],
    durations: list[float],
    starts: list[float],
    max_chars: int = CAPTION_MAX_CHARS,
) -> list[tuple[float, float, str]]:
    """Timed (start, end, text) caption events on the final timeline.

    Each scene's narration chunks share the scene window proportionally
    to their length, so timing is honest even when scene durations were
    stretched to fit real speech. A scene's captions are clamped to end
    where the NEXT scene's crossfade begins (its audio slot starts there),
    so neighbouring captions never render on top of each other.
    """
    events: list[tuple[float, float, str]] = []
    for i, (scene, dur, start) in enumerate(zip(scenes, durations, starts)):
        if i + 1 < len(starts):
            window_end = min(start + dur, float(starts[i + 1]))
        else:
            window_end = start + dur
        window = window_end - start
        chunks = split_caption(str(scene.get("narration", "")), max_chars)
        if not chunks or window <= 0:
            continue
        weights = [max(1, len(c)) for c in chunks]
        total = float(sum(weights))
        t = float(start)
        for chunk, weight in zip(chunks, weights):
            span = window * (weight / total)
            events.append((round(t, 3), round(t + span, 3), chunk))
            t += span
    return events


def _ass_time(t: float) -> str:
    centis = int(round(max(0.0, t) * 100))
    h, rem = divmod(centis, 360_000)
    m, rem = divmod(rem, 6_000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _ass_escape(text: str) -> str:
    return (
        str(text)
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", "\\N")
        .strip()
    )


def write_ass(
    path: Path,
    events: list[tuple[float, float, str]],
    title: str,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> Path:
    """Write the burned-caption track (libass).

    Title style: top band, first 3 s. Caption style: bottom, opaque
    box (BorderStyle=3) for legibility on any gradient. FontName Arial
    resolves on Windows out of the box and maps to Liberation Sans on
    Linux via fontconfig.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Title,Arial,{int(height * 0.028)},&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2,1,8,80,80,120,1\n"
        f"Style: Caption,Arial,{int(height * 0.032)},&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H00000000,0,0,0,0,100,100,0,0,3,3,0,2,90,90,140,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = [header]
    if str(title or "").strip():
        lines.append(
            f"Dialogue: 0,{_ass_time(0.0)},{_ass_time(3.0)},Title,,0,0,0,,"
            f"{_ass_escape(str(title))}"
        )
    for start, end, text in events:
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
            f"{_ass_escape(text)}"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# ffmpeg subprocess helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str], *, what: str, cwd: Path | None = None
) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, cwd=str(cwd) if cwd else None, capture_output=True
        )
    except OSError as exc:
        raise RuntimeError(f"ffmpeg failed to run for {what}: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()[-500:]
        raise RuntimeError(
            f"ffmpeg failed for {what} (exit {proc.returncode}): {err}"
        )
    return proc


def render_scene_clip(
    ffmpeg: str,
    workdir: Path,
    idx: int,
    palette: tuple[str, str, str],
    duration_s: float,
    audio_path: Path,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> Path:
    """One scene = a static-ish palette gradient + its narration audio,
    encoded to exactly `duration_s` (audio padded, video capped)."""
    top, bottom, _ = palette
    src = (
        f"gradients=s={width}x{height}:c0={top}:c1={bottom}"
        f":x0=0:y0=0:x1=0:y1={height}:speed=0.00001"
    )
    out = Path(workdir) / f"clip_{idx:03d}.mp4"
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", src,
        "-i", str(audio_path),
        "-t", f"{duration_s:.3f}",
        "-af", "apad",
        "-r", str(FPS), "-pix_fmt", "yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(out),
    ]
    _run(cmd, what=f"scene {idx} clip")
    return out


def concat_clips(
    ffmpeg: str,
    clips: list[Path],
    durations: list[float],
    ass_name: str,
    out_path: Path,
    *,
    cwd: Path,
    td: float = TRANSITION_S,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> Path:
    """Join scene clips with crossfades and burn the caption track.

    `cwd` must be the directory holding `ass_name` so the subtitles
    filter never sees a Windows drive-letter path (colon-escaping trap).
    """
    out_path = Path(out_path)
    n = len(clips)
    if n == 0:
        raise RuntimeError("no scene clips to concat")
    cmd: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        cmd += ["-i", str(clip)]
    parts: list[str] = []
    if n == 1:
        vchain = "0:v"
        amap = "0:a"
    else:
        offsets = xfade_offsets(durations, td)
        prev = "0:v"
        for i in range(1, n):
            label = f"vx{i}"
            parts.append(
                f"[{prev}][{i}:v]xfade=transition=fade:duration={td:.2f}"
                f":offset={offsets[i - 1]:.3f}[{label}]"
            )
            prev = label
        vchain = prev
        prev_a = "0:a"
        for i in range(1, n):
            label = f"ax{i}"
            parts.append(f"[{prev_a}][{i}:a]acrossfade=d={td:.2f}[{label}]")
            prev_a = label
        amap = f"[{prev_a}]"
    del width, height  # caption scaling lives in the ass PlayRes header
    parts.append(f"[{vchain}]subtitles={ass_name}[vout]")
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[vout]", "-map", amap,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(out_path),
    ]
    _run(cmd, what="concat+subtitles", cwd=cwd)
    return out_path


# ---------------------------------------------------------------------------
# QC probe (roadmap Phase 5 gate)
# ---------------------------------------------------------------------------


def qc_probe(
    path: Path,
    planned_s: float,
    *,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> dict[str, Any]:
    """Automated QC: dimensions, aspect, duration vs plan, audio presence
    and level. Raises nothing; reports honestly via checks."""
    ffprobe = resolve_ffprobe()
    ffmpeg = resolve_ffmpeg()
    if not ffprobe or not ffmpeg:
        raise RuntimeError("ffprobe/ffmpeg not found - QC cannot run")
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("ffprobe failed on the rendered file")
    meta = json.loads(proc.stdout.decode("utf-8", "replace"))
    streams = meta.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(meta.get("format", {}).get("duration", 0.0) or 0.0)

    got_w = int(video.get("width", 0)) if video else 0
    got_h = int(video.get("height", 0)) if video else 0
    aspect_ok = (
        got_h > 0
        and got_w > 0
        and abs((got_w / got_h) - (width / height)) < 0.01
    )
    dur_tol = max(1.5, planned_s * 0.02)
    checks = [
        {"name": "width", "ok": got_w == width, "detail": f"{got_w}px (planned {width})"},
        {"name": "height", "ok": got_h == height, "detail": f"{got_h}px (planned {height})"},
        {"name": "aspect", "ok": aspect_ok, "detail": f"{got_w}x{got_h}"},
        {
            "name": "duration",
            "ok": abs(duration - planned_s) <= dur_tol,
            "detail": f"{duration:.2f}s vs planned {planned_s:.2f}s",
        },
        {"name": "audio_stream", "ok": audio is not None, "detail": "aac" if audio else "none"},
    ]
    vol = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"],
        capture_output=True,
    )
    match = re.search(
        r"mean_volume:\s*(-?[0-9.]+)\s*dB", vol.stderr.decode("utf-8", "replace")
    )
    mean_db = float(match.group(1)) if match else None
    checks.append(
        {
            "name": "audio_level",
            "ok": mean_db is not None and mean_db > -70.0,
            "detail": f"mean_volume {mean_db} dB" if mean_db is not None else "unreadable",
        }
    )
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "duration_s": round(duration, 2),
    }


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


def render_episode(
    ffmpeg: str,
    *,
    workdir: Path,
    out_path: Path,
    title: str,
    style_slug: str,
    scenes: list[dict[str, Any]],
    audio_mode: str,
    piper: Any | None = None,
    models_dir: Path | None = None,
    width: int = WIDTH,
    height: int = HEIGHT,
    voice: Path | None = None,
    length_scale: float | None = None,
) -> dict[str, Any]:
    """Render the whole episode. `audio_mode` is "piper" (adapter already
    probed available) or "tone" (honest placeholder). Raises RuntimeError
    on any ffmpeg/QC failure (retryable job failure).

    0.4.5: `voice` selects a specific piper .onnx and `length_scale` the
    speech-rate preset; both None = the adapter resolves its default
    voice with the model's own rate - the pre-0.4.5 behaviour. The
    result records the voice actually used (`voice`, file stem)."""
    if not scenes:
        raise RuntimeError("no scenes to render")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    palette = palette_for(style_slug)

    clips: list[Path] = []
    durations: list[float] = []
    try:
        for i, scene in enumerate(scenes, start=1):
            planned = float(scene.get("duration_s") or 2.0)
            narration = str(scene.get("narration") or "").strip()
            spoken: float | None = None
            if audio_mode == "piper" and narration and piper is not None:
                raw = workdir / f"tts_{i:03d}.wav"
                if voice is not None or length_scale is not None:
                    piper.synthesize(
                        narration, raw, voice=voice, length_scale=length_scale
                    )
                else:
                    piper.synthesize(narration, raw)
                spoken = wav_duration_s(raw)
                audio_path: Path = raw
            else:
                audio_path = workdir / f"tone_{i:03d}.wav"
                tone_wav(audio_path, effective_duration_s(planned, None))
            dur = effective_duration_s(planned, spoken)
            durations.append(dur)
            clips.append(
                render_scene_clip(
                    ffmpeg, workdir, i, palette, dur, audio_path,
                    width=width, height=height,
                )
            )

        events = subtitle_events(scenes, durations, scene_starts(durations))
        write_ass(workdir / "subs.ass", events, title, width=width, height=height)
        total = round(sum(durations) - TRANSITION_S * (len(durations) - 1), 2)
        concat_clips(
            ffmpeg, clips, durations, "subs.ass", out_path,
            cwd=workdir, width=width, height=height,
        )

        bed_label: str | None = None
        if models_dir is not None and audio_mode == "piper":
            bed = resolve_bed(style_slug, models_dir, workdir)
            if bed is not None:
                bed_label, bed_path = bed
                mix_bed(ffmpeg, out_path, bed_path, out_path, total)

        qc = qc_probe(out_path, total, width=width, height=height)
        if not qc["ok"]:
            failed = "; ".join(
                f"{c['name']} ({c['detail']})" for c in qc["checks"] if not c["ok"]
            )
            raise RuntimeError(f"render QC failed: {failed}")
        used_voice: str | None = None
        if audio_mode == "piper":
            resolved = voice
            if resolved is None and piper is not None and hasattr(
                piper, "resolve_voice"
            ):
                resolved = piper.resolve_voice()
            used_voice = Path(resolved).stem if resolved else None
        return {
            "method": "local_piper" if audio_mode == "piper" else "fallback_tone",
            "path": str(out_path),
            "bytes": out_path.stat().st_size,
            "duration_s": total,
            "scene_count": len(scenes),
            "style_slug": str(style_slug),
            "voice": used_voice,
            "bed": bed_label,
            "qc": qc,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
