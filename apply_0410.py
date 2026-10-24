#!/usr/bin/env python3
"""Apply 0.4.10-multilang - Hindi + English narration support.

WHAT IT DOES
  1. Verifies the repo layout and the installed 0.4.8-era files.
  2. Backs up every file it touches into backups_0410/ (manifest.json).
  3. Replaces four canonical backend files with their 0.4.10 versions:
       backend/laf/jobs/handlers.py        (language-aware script_gen)
       backend/laf/voices.py               (hi_IN catalog + language meta)
       backend/laf/api/routes/episodes.py  (ScriptRequest.language)
     and adds: backend/laf/lang.py, tests/test_multilang.py,
     tests/test_voices.py (updated canonical), scripts/add_voice.ps1.
  4. Anchor-patches backend/laf/renderer.py so burned captions switch to
     Noto Sans Devanagari whenever the text contains Devanagari (skipped
     as a whole if any anchor is missing - English renders unaffected).
  5. Bumps laf.__version__ to "0.4.10-multilang".
  6. Installs the bundled Hindi voices + Devanagari font into
     <models_dir>/piper/voices|fonts (skips files already present).
  7. Runs `python -m pytest tests -q`. ANY failure -> full auto-rollback.

USAGE (repo root, venv active)
  python apply_0410.py                 # apply + tests
  python apply_0410.py --skip-tests    # apply, do not run pytest
  python apply_0410.py --repo C:\\path\\to\\local-ai-video-factory
  python apply_0410.py --rollback      # restore backups from manifest

If anything aborts, the report (apply_0410_report.txt) says exactly
what was found and what was skipped - paste it back to the maintainer.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "0.4.10-multilang"

# 0.4.8-rev3 field signature - proves the installed handlers.py is the
# verified baseline before we replace it (0.4.8 stale-file lesson).
HANDLERS_MARKERS = (
    "_SENTENCE_SPLIT",
    "think_truncated",
    "_scene_count",
    "handle_series_outline_gen",
)
VOICES_MARKERS = (
    "def catalog_summary",
    '"en_US-ryan-high"',
    "VOICES_SUBDIR",
    "def preset_for",
)
EPISODES_MARKERS = (
    "class RenderRequest",
    "voice_slug",
    "resolve_voice_path",
    "class ScriptRequest",
)

REL_HANDLERS = "backend/laf/jobs/handlers.py"
REL_VOICES = "backend/laf/voices.py"
REL_EPISODES = "backend/laf/api/routes/episodes.py"
REL_RENDERER = "backend/laf/renderer.py"
REL_INIT = "backend/laf/__init__.py"
REL_LANG = "backend/laf/lang.py"
REL_TEST_MULTI = "tests/test_multilang.py"
REL_TEST_VOICES = "tests/test_voices.py"
REL_ADDVOICE = "scripts/add_voice.ps1"

FONT_NAME = "NotoSansDevanagari-Regular.ttf"

REPORT_LINES: list[str] = []


def report(msg: str) -> None:
    print(msg)
    REPORT_LINES.append(msg)


class Patcher:
    def __init__(self, repo: Path, files_dir: Path) -> None:
        self.repo = repo
        self.files = files_dir
        self.backup_dir = repo / "backups_0410"
        self.manifest = {"replaced": {}, "created": []}
        self.ok_steps: list[str] = []

    # -- backup bookkeeping ------------------------------------------------

    def _backup_path(self, rel: str) -> Path:
        return self.backup_dir / (rel.replace("/", "__") + ".bak")

    def backup(self, rel: str) -> None:
        src = self.repo / rel
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        dst = self._backup_path(rel)
        if src.exists():
            shutil.copyfile(src, dst)
            self.manifest["replaced"][rel] = dst.name
        report(f"  backup: {rel} -> backups_0410/{dst.name}")

    def record_created(self, rel: str) -> None:
        self.manifest["created"].append(rel)

    def save_manifest(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        (self.backup_dir / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8"
        )

    # -- primitives ----------------------------------------------------------

    def installed_has_markers(self, rel: str, markers) -> bool:
        path = self.repo / rel
        if not path.exists():
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return False
        return all(m in text for m in markers)

    def git_head_text(self, rel: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "show", f"HEAD:{rel}"],
                cwd=self.repo,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", "replace")

    def replace_canonical(
        self, rel: str, markers, label: str, allow_git_probe: bool = True
    ) -> bool:
        """Replace a tracked file with the shipped canonical version.

        Guard: the installed file must carry the expected baseline
        markers. A stale/divergent file is probed against git HEAD
        (apply_048 pattern); if HEAD carries the markers we proceed
        (field file was dirty), otherwise we abort rather than clobber
        unknown changes.
        """
        src = self.files / rel
        if not src.exists():
            report(f"[{label}] SKIP - shipped canonical missing: {rel}")
            return False
        if not self.installed_has_markers(rel, markers):
            head = self.git_head_text(rel) if allow_git_probe else None
            if head and all(m in head for m in markers):
                report(
                    f"[{label}] NOTE - installed {rel} diverged from "
                    "0.4.8-rev3 markers, but git HEAD matches; replacing "
                    "with canonical (field file was dirty)."
                )
            else:
                report(
                    f"[{label}] ABORT - installed {rel} does not match "
                    "the expected baseline markers and git HEAD does not "
                    "help. Nothing was changed for this file. Paste "
                    "apply_0410_report.txt back for a targeted patch."
                )
                return False
        self.backup(rel)
        dst = self.repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        self.ok_steps.append(f"replace:{rel}")
        report(f"[{label}] OK - replaced {rel} with {VERSION} canonical")
        return True

    def add_file(self, rel: str, label: str, replace: bool = False) -> bool:
        src = self.files / rel
        dst = self.repo / rel
        if not src.exists():
            report(f"[{label}] SKIP - not shipped: {rel}")
            return False
        if dst.exists() and not replace:
            report(f"[{label}] OK - already present: {rel}")
            return True
        existed = dst.exists()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            self.backup(rel)
        else:
            self.record_created(rel)
        shutil.copyfile(src, dst)
        self.ok_steps.append(f"add:{rel}")
        report(f"[{label}] OK - {'updated' if existed else 'added'} {rel}")
        return True

    def rollback(self) -> int:
        manifest_path = self.backup_dir / "manifest.json"
        if not manifest_path.exists():
            report("rollback: no manifest found (nothing to restore)")
            return 1
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rel, bak in data.get("replaced", {}).items():
            src = self.backup_dir / bak
            if src.exists():
                shutil.copyfile(src, self.repo / rel)
                report(f"rollback: restored {rel}")
        for rel in data.get("created", []):
            p = self.repo / rel
            if p.exists():
                p.unlink()
                report(f"rollback: removed {rel}")
        report("rollback complete.")
        return 0

    # -- steps ----------------------------------------------------------------

    def step_canonical_files(self) -> bool:
        report("== step 1: canonical backend files ==")
        ok = True
        ok &= self.replace_canonical(REL_HANDLERS, HANDLERS_MARKERS, "handlers")
        ok &= self.replace_canonical(REL_VOICES, VOICES_MARKERS, "voices")
        ok &= self.replace_canonical(REL_EPISODES, EPISODES_MARKERS, "episodes")
        # lang.py is brand new for most installs; replaced idempotently on
        # re-runs (backed up first either way).
        self.add_file(REL_LANG, "lang", replace=True)
        self.add_file(REL_TEST_MULTI, "tests-multilang")
        self.add_file(REL_TEST_VOICES, "tests-voices", replace=True)
        self.add_file(REL_ADDVOICE, "add-voice", replace=True)
        return ok

    def step_renderer(self) -> bool:
        report("== step 2: renderer.py caption fonts (anchor patch) ==")
        path = self.repo / REL_RENDERER
        if not path.exists():
            report(f"[renderer] SKIP - {REL_RENDERER} not found")
            return False
        text = path.read_text(encoding="utf-8")

        anchor_helpers = "def _ass_time(t: float) -> str:"
        anchor_title = 'f"Style: Title,Arial,'
        anchor_caption = 'f"Style: Caption,Arial,'
        anchor_header = "    header = ("
        anchor_subs = (
            'parts.append(f"[{vchain}]subtitles={ass_name}[vout]")'
        )
        anchor_stage = (
            'write_ass(workdir / "subs.ass", events, title, '
            "width=width, height=height)"
        )
        anchors = {
            "helpers": anchor_helpers,
            "title-style": anchor_title,
            "caption-style": anchor_caption,
            "header": anchor_header,
            "subtitles-filter": anchor_subs,
            "write_ass-call": anchor_stage,
        }
        missing = [k for k, v in anchors.items() if v not in text]
        if missing:
            report(
                f"[renderer] SKIP - anchors missing ({', '.join(missing)}). "
                "renderer.py has drifted from the phase-5 layout (0.4.7 "
                "mp4-line fix?). Nothing changed. Hindi AUDIO still works; "
                "Hindi CAPTIONS may need the follow-up patch. Paste this "
                "report back."
            )
            return False
        if text.count(anchor_header) != 1:
            report("[renderer] SKIP - `header = (` is not unique; refusing to guess.")
            return False

        self.backup(REL_RENDERER)
        helpers = '''# --- 0.4.10-multilang: Devanagari caption support ------------------
# Captions are burned via libass, which shapes complex scripts through
# HarfBuzz - but only if the selected font actually has the glyphs.
# Arial does not cover Devanagari, so a Hindi caption would burn as
# boxes. When any caption/title contains Devanagari, the ASS Fontname
# switches to Noto Sans Devanagari and the bundled TTF is staged next
# to subs.ass (fontsdir=.) so libass finds it without a system install.


def _has_devanagari(text: str) -> bool:
    return any("\\u0900" <= ch <= "\\u097f" for ch in str(text or ""))


def _caption_font(texts: list) -> str:
    if any(_has_devanagari(t) for t in texts):
        return "Noto Sans Devanagari"
    return "Arial"


def _stage_caption_font(workdir, models_dir) -> None:
    """Copy the bundled Devanagari TTF next to subs.ass (best effort)."""
    import os

    name = "NotoSansDevanagari-Regular.ttf"
    candidates = []
    if models_dir:
        candidates.append(Path(models_dir) / "piper" / "fonts" / name)
    env_dir = os.environ.get("LAF_FONTS_DIR")
    if env_dir:
        candidates.append(Path(env_dir) / name)
    here = Path(__file__).resolve().parent / "fonts" / name
    candidates.append(here)
    try:
        for src in candidates:
            if src.exists():
                Path(workdir).mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, Path(workdir) / name)
                return
    except Exception:
        pass  # captions fall back to system fonts; audio is unaffected


'''
        text = text.replace(
            anchor_helpers, helpers + anchor_helpers, 1
        )
        text = text.replace(anchor_title, 'f"Style: Title,{caption_font},', 1)
        text = text.replace(
            anchor_caption, 'f"Style: Caption,{caption_font},', 1
        )
        text = text.replace(
            anchor_header,
            "    caption_font = _caption_font(\n"
            '        [str(title or "")] + [str(ev[2]) for ev in events]\n'
            "    )\n"
            "    header = (",
            1,
        )
        text = text.replace(
            anchor_subs,
            'parts.append(f"[{vchain}]subtitles={ass_name}:fontsdir=.[vout]")',
            1,
        )
        text = text.replace(
            "        " + anchor_stage,
            "        _stage_caption_font(workdir, models_dir)\n"
            "        " + anchor_stage,
            1,
        )
        (self.repo / REL_RENDERER).write_text(text, encoding="utf-8")

        # syntax gate: a broken renderer must never reach the venv
        check = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{path}', encoding='utf-8').read())"],
            capture_output=True,
            timeout=60,
        )
        if check.returncode != 0:
            shutil.copyfile(
                self._backup_path(REL_RENDERER), path
            )
            report(
                "[renderer] ROLLED BACK - patched file failed the syntax "
                f"check: {check.stderr.decode('utf-8', 'replace')[:300]}"
            )
            return False
        self.ok_steps.append("patch:renderer")
        report(
            "[renderer] OK - Devanagari caption font + fontsdir staging "
            "installed (6/6 anchors)."
        )
        return True

    def step_version(self) -> bool:
        report("== step 3: version bump ==")
        path = self.repo / REL_INIT
        if not path.exists():
            report(f"[version] SKIP - {REL_INIT} not found")
            return False
        text = path.read_text(encoding="utf-8")
        new_text, n = re.subn(
            r'(__version__\s*=\s*["\'])[^"\']+(["\'])',
            rf"\g<1>{VERSION}\g<2>",
            text,
        )
        if n != 1:
            report(
                f"[version] SKIP - __version__ assignment not found "
                f"exactly once in {REL_INIT} (matches: {n})"
            )
            return False
        self.backup(REL_INIT)
        path.write_text(new_text, encoding="utf-8")
        self.ok_steps.append("version")
        report(f"[version] OK - __version__ = \"{VERSION}\"")
        return True

    # -- assets ---------------------------------------------------------------

    def resolve_models_dir(self) -> Path:
        env = os_env("LAF_MODELS_DIR")
        if env:
            return Path(env)
        la = os_env("LOCALAPPDATA")
        candidates = []
        if la:
            candidates.append(
                Path(la) / "com.rajbh.localaivideofactory" / "models"
            )
            candidates.append(Path(la) / "LocalAIVideoFactory" / "models")
        candidates.append(self.repo / "models")
        for c in candidates:
            if c.is_dir():
                return c
        return candidates[0]

    def step_assets(self) -> bool:
        report("== step 4: Hindi voices + Devanagari font ==")
        voice_src = self.files / "models/piper/voices"
        font_src = self.files / "fonts" / FONT_NAME
        models = self.resolve_models_dir()
        voices_target = models / "piper" / "voices"
        fonts_target = models / "piper" / "fonts"
        report(f"  models_dir: {models}")
        try:
            voices_target.mkdir(parents=True, exist_ok=True)
            fonts_target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            report(f"[assets] SKIP - cannot create models dirs: {exc}")
            return False

        if voice_src.is_dir():
            for onnx in sorted(voice_src.glob("*.onnx")):
                dst = voices_target / onnx.name
                cfg_src = onnx.with_suffix(".onnx.json")
                cfg_dst = voices_target / (onnx.name + ".json")
                if dst.exists() and dst.stat().st_size > 10_000_000:
                    report(f"[assets] OK - voice already installed: {onnx.name}")
                else:
                    shutil.copyfile(onnx, dst)
                    report(f"[assets] OK - installed voice: {dst}")
                if cfg_src.exists() and not cfg_dst.exists():
                    shutil.copyfile(cfg_src, cfg_dst)
        else:
            report(
                "[assets] NOTE - no bundled voices in this patch; run "
                "scripts\\add_voice.ps1 pratham to download them."
            )

        if font_src.exists():
            shutil.copyfile(font_src, fonts_target / FONT_NAME)
            laf_fonts = self.repo / "backend/laf/fonts"
            laf_fonts.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(font_src, laf_fonts / FONT_NAME)
            self.record_created(f"backend/laf/fonts/{FONT_NAME}")
            report(
                f"[assets] OK - font staged: {fonts_target / FONT_NAME} "
                "+ backend/laf/fonts/ (renderer fallback)"
            )
        else:
            report(
                "[assets] NOTE - font not bundled; Hindi captions will "
                "try Noto Sans Devanagari from system fonts only."
            )
        return True


def os_env(name: str) -> str | None:
    import os

    return os.environ.get(name)


def run_tests(repo: Path) -> tuple[bool, str]:
    report("== step 5: pytest ==")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=repo,
        capture_output=True,
        timeout=1800,
    )
    tail = (proc.stdout + proc.stderr).decode("utf-8", "replace").splitlines()
    tail_text = "\n".join(tail[-25:])
    report(tail_text)
    return proc.returncode == 0, tail_text


def detect_repo(explicit: str | None) -> Path | None:
    candidates = [Path(explicit)] if explicit else [Path.cwd()]
    for cand in candidates:
        if (cand / "backend/laf").is_dir() and (
            (cand / "tests").is_dir() or (cand / "src").is_dir()
        ):
            return cand.resolve()
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None, help="repo root (default: cwd)")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    repo = detect_repo(args.repo)
    if repo is None:
        print(
            "ERROR: run from the repo root (backend/laf + tests/src must "
            "exist), or pass --repo <path>."
        )
        return 2

    files_dir = Path(__file__).resolve().parent / "files"
    patcher = Patcher(repo, files_dir)

    if args.rollback:
        rc = patcher.rollback()
        _write_report(repo, started, "rollback")
        return rc

    report(f"apply_0410: {VERSION}")
    report(f"repo      : {repo}")
    report(f"started   : {started}")

    ok = patcher.step_canonical_files()
    ok = patcher.step_renderer() and ok
    ok = patcher.step_version() and ok
    patcher.step_assets()
    patcher.save_manifest()

    tests_ok = True
    if ok and not args.skip_tests:
        tests_ok, _ = run_tests(repo)
        if not tests_ok:
            report(
                "\nPYTEST FAILED - auto-rollback in progress (0.4.8 rule: "
                "never leave the tree in a state that did not pass)."
            )
            patcher.rollback()
    elif not ok:
        report(
            "\nOne or more canonical steps aborted - nothing was replaced "
            "for those files; assets/tests were still handled where safe. "
            "Paste apply_0410_report.txt back for a targeted follow-up."
        )

    if ok and tests_ok and not args.skip_tests:
        report(
            f"\nDONE - {VERSION} applied and verified. Restart the "
            "backend (Ctrl+C the dev session, or relaunch the app), then: "
            "Hindi episode = write the topic in Hindi (or set language "
            "explicitly) and pick Pratham/Priyamvada in the Render voice "
            "dropdown."
        )
    elif ok and args.skip_tests:
        report(
            f"\nDONE (tests skipped) - {VERSION} applied. Run "
            "`python -m pytest tests -q` yourself before shipping."
        )

    _write_report(repo, started, "applied" if ok else "partial")
    return 0 if ok and tests_ok else 1


def _write_report(repo: Path, started: str, status: str) -> None:
    out = repo / "apply_0410_report.txt"
    out.write_text(
        f"apply_0410 report - {VERSION}\nstatus : {status}\n"
        f"started: {started}\nwritten: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        + "\n".join(REPORT_LINES)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
