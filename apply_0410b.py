#!/usr/bin/env python3
"""Apply 0.4.10-multilang rev 3 - handler repair + Hindi captions.

WHY rev 3 EXISTS
  rev1 shipped a handlers.py built on a stale pre-0.4.3 base (no
  format:json JSON contract) -> 3 test_handlers failures -> auto-
  rollback. rev2's renderer anchors were written in the already-patched
  form, so they can never match a clean renderer.py, and its run order
  skipped the pytest gate entirely. rev 3 fixes both, and ships a
  handlers.py built from YOUR OWN repo upload + 12 anchor-verified
  surgical multilang edits (English path stays byte-identical to
  0.4.8; Hindi speaks the same JSON contract with Devanagari values).

WHAT IT DOES
  1. Verifies version (0.4.8-scenecount or 0.4.10-multilang) and
     repairs/replaces the multilang canonical set:
       handlers.py  (3-way health check: already-correct / repair / abort)
       voices.py, episodes.py, test_voices.py, add_voice.ps1,
       lang.py, tests/test_multilang.py  (byte-checked replace)
  2. Anchor-patches renderer.py so burned captions switch to
     Noto Sans Devanagari when text contains Devanagari (6/6 anchors,
     idempotent, syntax-gated).
  3. Bumps laf.__version__ to "0.4.10-multilang" (if needed).
  4. VERIFIES the Hindi voices + Devanagari font are installed
     (stages the repo fallback font if missing).
  5. Runs `python -m pytest tests -q`. ANY failure -> auto-rollback of
     everything this script touched. The gate runs even if an earlier
     step skipped - that rev1 flaw is fixed.

USAGE (repo root, venv active)
  python apply_0410b.py                 # apply + tests
  python apply_0410b.py --skip-tests    # apply, do not run pytest
  python apply_0410b.py --repo C:\\path\\to\\local-ai-video-factory
  python apply_0410b.py --rollback      # restore backups from manifest

If anything aborts, the report (apply_0410b_report.txt) says exactly
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
BANNER = "0.4.10-multilang rev 3 (handler repair + Hindi captions)"

ACCEPTED_VERSIONS = {"0.4.8-scenecount", "0.4.10-multilang"}

REL_HANDLERS = "backend/laf/jobs/handlers.py"
REL_VOICES = "backend/laf/voices.py"
REL_EPISODES = "backend/laf/api/routes/episodes.py"
REL_RENDERER = "backend/laf/renderer.py"
REL_INIT = "backend/laf/__init__.py"
REL_LANG = "backend/laf/lang.py"
REL_TEST_MULTI = "tests/test_multilang.py"
REL_TEST_VOICES = "tests/test_voices.py"
REL_ADDVOICE = "scripts/add_voice.ps1"
REL_REPO_FONT = "backend/laf/fonts/NotoSansDevanagari-Regular.ttf"

FONT_NAME = "NotoSansDevanagari-Regular.ttf"

# handlers.py three-way classification -------------------------------
# (a) already the CORRECT 0.4.10 (rev3) multilang handler:
HANDLERS_OK_0410 = (
    '_SCRIPT_SYSTEMS = {"en": _SCRIPT_SYSTEM, "hi": SCRIPT_SYSTEM_HI}',
    'num_predict=768 if language == "hi" else 512',
    'text = _script_from_json(result["text"])',
    "json_mode=True",
    '"language": language,',
)
# (b) the verified 0.4.8-rev3 baseline (replace it):
HANDLERS_BASELINE = (
    "_SENTENCE_SPLIT",
    "think_truncated",
    "_scene_count",
    "handle_series_outline_gen",
    "json_mode=True",
    "no JSON object",
)
# (c) a BROKEN 0.4.10 artifact (rev1/rev2 stale base - repair it):
#     has _SCRIPT_SYSTEMS but lost the JSON reassembly call.
HANDLERS_STALE_0410 = ('_SCRIPT_SYSTEMS', 'text = result["text"]')

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

REPORT_LINES: list[str] = []


def report(msg: str) -> None:
    print(msg)
    REPORT_LINES.append(msg)


class Patcher:
    def __init__(self, repo: Path, files_dir: Path) -> None:
        self.repo = repo
        self.files = files_dir
        self.backup_dir = repo / "backups_0410b"
        self.manifest = {"replaced": {}, "created": []}
        self.touched = False

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
            self.touched = True
            report(f"  backup: {rel} -> backups_0410b/{dst.name}")

    def record_created(self, rel: str) -> None:
        self.manifest["created"].append(rel)
        self.touched = True

    def save_manifest(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        (self.backup_dir / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8"
        )

    # -- primitives ----------------------------------------------------------

    @staticmethod
    def read_text(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def installed_has_markers(self, rel: str, markers) -> bool:
        text = self.read_text(self.repo / rel)
        return text is not None and all(m in text for m in markers)

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

    def step_handlers(self) -> bool:
        report("== step 1a: handlers.py health check / repair ==")
        rel = REL_HANDLERS
        path = self.repo / rel
        src = self.files / rel
        if not path.exists() or not src.exists():
            report(f"[handlers] ABORT - missing file (installed or shipped)")
            return False
        if self.installed_has_markers(rel, HANDLERS_OK_0410):
            report(
                "[handlers] OK - installed handler is already the correct "
                "rev3 multilang version (JSON contract + language intact)."
            )
            return True
        if self.installed_has_markers(rel, HANDLERS_STALE_0410) and not (
            self.installed_has_markers(rel, ('text = _script_from_json(result["text"])',))
        ):
            report(
                "[handlers] REPAIR - installed handler is a broken 0.4.10 "
                "artifact (stale pre-0.4.3 base: JSON reassembly missing, "
                "format:json dropped). This is the exact rev1 field bug."
            )
        elif not self.installed_has_markers(rel, HANDLERS_BASELINE):
            report(
                "[handlers] ABORT - installed handlers.py matches neither "
                "the 0.4.8-rev3 baseline nor a known 0.4.10 state. Nothing "
                "was changed. Paste apply_0410b_report.txt back."
            )
            return False
        else:
            report(
                "[handlers] OK - installed handler is the 0.4.8-rev3 "
                "baseline; replacing with the multilang version."
            )
        self.backup(rel)
        shutil.copyfile(src, path)
        report(f"[handlers] OK - installed rev3 multilang handlers.py")
        return True

    def step_canonical_files(self) -> bool:
        report("== step 1: multilang canonical files ==")
        ok = self.step_handlers()
        for rel, markers, label in [
            (REL_VOICES, VOICES_MARKERS, "voices"),
            (REL_EPISODES, EPISODES_MARKERS, "episodes"),
            (REL_TEST_VOICES, (), "tests-voices"),
            (REL_ADDVOICE, (), "add-voice"),
        ]:
            src = self.files / rel
            dst = self.repo / rel
            if not src.exists():
                report(f"[{label}] SKIP - not shipped: {rel}")
                continue
            if dst.exists() and dst.read_bytes() == src.read_bytes():
                report(f"[{label}] OK - already correct: {rel}")
                continue
            if markers and not self.installed_has_markers(rel, markers):
                report(
                    f"[{label}] ABORT - installed {rel} does not match the "
                    "expected baseline markers. Nothing was changed for "
                    "this file. Paste apply_0410b_report.txt back."
                )
                ok = False
                continue
            self.backup(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            report(f"[{label}] OK - installed 0.4.10-multilang {rel}")
        # 0410-owned files: replaced unconditionally (backed up first)
        for rel, label in [
            (REL_LANG, "lang"),
            (REL_TEST_MULTI, "tests-multilang"),
        ]:
            src = self.files / rel
            dst = self.repo / rel
            if not src.exists():
                report(f"[{label}] SKIP - not shipped: {rel}")
                ok = False
                continue
            if dst.exists() and dst.read_bytes() == src.read_bytes():
                report(f"[{label}] OK - already correct: {rel}")
                continue
            existed = dst.exists()
            if existed:
                self.backup(rel)
            else:
                self.record_created(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            report(
                f"[{label}] OK - {'updated' if existed else 'added'} {rel}"
            )
        # repo fallback font (renderer uses it when models_dir is unset)
        font_src = self.files / "fonts" / FONT_NAME
        font_dst = self.repo / REL_REPO_FONT
        if font_src.exists() and not font_dst.exists():
            font_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(font_src, font_dst)
            self.record_created(REL_REPO_FONT)
            report(f"[font] OK - staged {REL_REPO_FONT}")
        elif font_dst.exists():
            report(f"[font] OK - already present: {REL_REPO_FONT}")
        else:
            report("[font] NOTE - font not shipped; captions fall back to system fonts")
        return ok

    def step_renderer(self) -> bool:
        report("== step 2: renderer.py caption fonts (anchor patch) ==")
        path = self.repo / REL_RENDERER
        if not path.exists():
            report(f"[renderer] SKIP - {REL_RENDERER} not found")
            return False
        text = self.read_text(path) or ""

        already = "_caption_font" in text and "fontsdir=." in text
        if already:
            report("[renderer] OK - Devanagari caption patch already applied.")
            return True

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
                "Nothing changed. Hindi AUDIO still works; Hindi CAPTIONS "
                "need a follow-up. Paste apply_0410b_report.txt back."
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
        text = text.replace(anchor_helpers, helpers + anchor_helpers, 1)
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
        path.write_text(text, encoding="utf-8")

        # syntax gate: a broken renderer must never reach the venv
        check = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open(r'{path}', encoding='utf-8').read())"],
            capture_output=True,
            timeout=60,
        )
        if check.returncode != 0:
            shutil.copyfile(self._backup_path(REL_RENDERER), path)
            report(
                "[renderer] ROLLED BACK - patched file failed the syntax "
                f"check: {check.stderr.decode('utf-8', 'replace')[:300]}"
            )
            return False
        report(
            "[renderer] OK - Devanagari caption font + fontsdir staging "
            "installed (6/6 anchors, syntax gate passed)."
        )
        return True

    def step_version(self) -> bool:
        report("== step 3: version bump ==")
        path = self.repo / REL_INIT
        if not path.exists():
            report(f"[version] SKIP - {REL_INIT} not found")
            return False
        text = self.read_text(path) or ""
        if f'__version__ = "{VERSION}"' in text:
            report(f"[version] OK - already {VERSION}")
            return True
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
        report(f'[version] OK - __version__ = "{VERSION}"')
        return True

    # -- assets: VERIFY only (voices already installed in the field) --

    def resolve_models_dir(self) -> Path:
        import os

        env = os.environ.get("LAF_MODELS_DIR")
        if env:
            return Path(env)
        la = os.environ.get("LOCALAPPDATA")
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
        report("== step 4: Hindi voices + Devanagari font (verify) ==")
        models = self.resolve_models_dir()
        report(f"  models_dir: {models}")
        ok = True
        voices_dir = models / "piper" / "voices"
        fonts_dir = models / "piper" / "fonts"
        for slug in ("hi_IN-pratham-medium", "hi_IN-priyamvada-medium"):
            p = voices_dir / f"{slug}.onnx"
            if p.exists() and p.stat().st_size > 10_000_000:
                report(f"[assets] OK - voice installed: {p.name}")
            else:
                report(
                    f"[assets] MISSING - {p} not found (>10 MB). Run: "
                    f".\\scripts\\add_voice.ps1 {'pratham' if 'pratham' in slug else 'priyamvada'}"
                )
                ok = False
        font_model = fonts_dir / FONT_NAME
        font_repo = self.repo / REL_REPO_FONT
        if font_model.exists():
            report(f"[assets] OK - font staged: {font_model}")
        elif font_repo.exists():
            fonts_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(font_repo, font_model)
            report(f"[assets] OK - font staged from repo fallback: {font_model}")
        else:
            report(
                "[assets] MISSING - Devanagari font not found; Hindi "
                "captions would fall back to system fonts."
            )
            ok = False
        return ok


def run_tests(repo: Path) -> tuple[bool, str]:
    report("== step 5: pytest (full suite) ==")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q"],
            cwd=repo,
            capture_output=True,
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        report("PYTEST TIMEOUT after 1800 s - treated as failure.")
        return False, "timeout"
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    lines = out.splitlines()
    failed = [l for l in lines if l.startswith("FAILED")]
    tail_text = "\n".join(lines[-12:])
    report(tail_text)
    return proc.returncode == 0, "\n".join(failed) or tail_text


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

    # version gate
    init_path = repo / REL_INIT
    ver_text = Patcher.read_text(init_path) or ""
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', ver_text)
    current = m.group(1) if m else "unknown"
    if args.rollback:
        files_dir = Path(__file__).resolve().parent / "files"
        rc = Patcher(repo, files_dir).rollback()
        _write_report(repo, started, "rollback")
        return rc
    if current not in ACCEPTED_VERSIONS:
        report(f"apply_0410b (rev 3): ABORT - repo version is {current!r}")
        report(
            "This patch applies on top of 0.4.8-scenecount or "
            "0.4.10-multilang only. Paste apply_0410b_report.txt back."
        )
        _write_report(repo, started, "aborted")
        return 1

    files_dir = Path(__file__).resolve().parent / "files"
    patcher = Patcher(repo, files_dir)

    report(f"apply_0410b: {BANNER}")
    report(f"repo      : {repo}")
    report(f"version   : {current}")
    report(f"started   : {started}")

    ok = patcher.step_canonical_files()
    ok_renderer = patcher.step_renderer()
    ok_version = patcher.step_version()
    ok_assets = patcher.step_assets()
    patcher.save_manifest()

    tests_ok = True
    if not args.skip_tests:
        # THE GATE RUNS REGARDLESS of earlier skips (rev1 flaw fixed).
        tests_ok, failed_names = run_tests(repo)
        if not tests_ok:
            report(
                "\nPYTEST FAILED - auto-rollback in progress (0.4.8 rule: "
                "never leave the tree in a state that did not pass)."
            )
            if failed_names:
                report("Failing tests:")
                report(failed_names)
            patcher.rollback()
    else:
        report("\n(tests skipped by --skip-tests)")

    if ok and ok_renderer and ok_version and ok_assets and tests_ok:
        report(
            f"\nDONE - {BANNER} applied and verified. Restart the backend "
            "(Ctrl+C the dev session, or relaunch the app), then commit. "
            "Hindi episode = write the topic in Hindi (or set language "
            "explicitly) and pick Pratham/Priyamvada in the Render voice "
            "dropdown."
        )
    elif args.skip_tests and ok:
        report(
            f"\nDONE (tests skipped) - applied. Run "
            "`python -m pytest tests -q` yourself before trusting it."
        )

    _write_report(
        repo, started,
        "applied" if (ok and ok_renderer and ok_version and tests_ok) else "partial",
    )
    return 0 if (ok and ok_renderer and ok_version and tests_ok) else 1


def _write_report(repo: Path, started: str, status: str) -> None:
    out = repo / "apply_0410b_report.txt"
    out.write_text(
        f"apply_0410b report - {BANNER}\nstatus : {status}\n"
        f"started: {started}\nwritten: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        + "\n".join(REPORT_LINES)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
