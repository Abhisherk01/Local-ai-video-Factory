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

import json
import math
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
    width: int = WIDTH,
    height: int = HEIGHT,
) -> dict[str, Any]:
    """Render the whole episode. `audio_mode` is "piper" (adapter already
    probed available) or "tone" (honest placeholder). Raises RuntimeError
    on any ffmpeg/QC failure (retryable job failure)."""
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
        qc = qc_probe(out_path, total, width=width, height=height)
        if not qc["ok"]:
            failed = "; ".join(
                f"{c['name']} ({c['detail']})" for c in qc["checks"] if not c["ok"]
            )
            raise RuntimeError(f"render QC failed: {failed}")
        return {
            "method": "local_piper" if audio_mode == "piper" else "fallback_tone",
            "path": str(out_path),
            "bytes": out_path.stat().st_size,
            "duration_s": total,
            "scene_count": len(scenes),
            "style_slug": str(style_slug),
            "qc": qc,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
