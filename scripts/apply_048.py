"""0.4.8-scenecount rev3 installer patch - run with the project venv:

    python scripts\\apply_048.py

WHAT REV 3 DOES (and why it exists)

Rev 1/2 of this zip shipped a whole backend/laf/jobs/handlers.py that
was rebuilt from an INCOMPLETE mirror of the repo. Its storyboard
split was correct, but its script_gen path had lost the 0.4.3
JSON-grammar contract (format:json request, no-JSON retry) - the
owner's pytest caught it as 3 failures in test_handlers.py.

Rev 3 therefore does NOT ship handlers.py. It:

  1. Restores YOUR canonical handlers.py from your own git history
     (commit 0406792, the 0.4.5-voices commit; falls back to HEAD),
     after verifying the restored bytes carry the 0.4.5 markers.
  2. Applies the scene-split fix SURGICALLY: two exact line swaps +
     one inserted helper block, each verified by count.
  3. Syntax-checks the result before writing.

Idempotent: a rev3 marker comment in the file makes re-runs no-ops.
Aborts with nothing changed on any mismatch.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = "0.4.8-scenecount"
HANDLERS = REPO / "backend" / "laf" / "jobs" / "handlers.py"
PINNED_COMMIT = "0406792"
GIT_SPEC = "backend/laf/jobs/handlers.py"
REV3_MARKER = "# laf 0.4.8-scenecount rev3"
ACCEPTED_VERSIONS = ("0.4.7-mp4line", VERSION)

OLD_SCENE = '    sentences = [s for s in re.split(r"(?<=[.!?])\\s+", script) if s.strip()]\n'
OLD_NARR = (
    '    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\\s+", script) if s.strip()]\n'
)
NEW_LINE = "    sentences = _sentences(script)\n"

HELPER_BLOCK = (
    '# Sentence boundaries: terminal punctuation (". "/"! "/"? ") OR a line\n'
    "# break. qwen scripts are one beat per line and often omit the final\n"
    "# period - punctuation-only splitting collapsed those scripts to a\n"
    '# single "sentence", which collapsed the whole storyboard to 1 scene\n'
    "# (ep10 rendered 22 s on one static card).\n"
    f"{REV3_MARKER}\n"
    '_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\\s+|\\n+")\n'
    "\n"
    "\n"
    "def _sentences(script: str) -> list[str]:\n"
    '    """Split a script into beats at punctuation and/or line breaks."""\n'
    "    return [s.strip() for s in _SENTENCE_SPLIT.split(script) if s.strip()]\n"
    "\n"
    "\n"
)


def fail(msg: str) -> None:
    print(f"[apply_048] ABORT: {msg}")
    sys.exit(1)


def git_show(spec: str) -> str | None:
    for cmd in (["git", "-C", str(REPO), "show", f"{PINNED_COMMIT}:{spec}"],
                ["git", "-C", str(REPO), "show", f"HEAD:{spec}"]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return None
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    return None


def backup_once(path: Path, suffix: str) -> None:
    bak = path.with_name(path.name + suffix)
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[apply_048] backup: {bak.name}")


def read_version() -> str:
    init = REPO / "backend" / "laf" / "__init__.py"
    if not init.exists():
        fail(f"file not found: {init}")
    m = re.search(r'__version__\s*=\s*"([^"]*)"', init.read_text(encoding="utf-8"))
    if m is None:
        fail("__version__ assignment not found in backend/laf/__init__.py")
    return m.group(1)


def main() -> int:
    print(f"[apply_048] repo: {REPO} (rev 3)")

    ver = read_version()
    if ver not in ACCEPTED_VERSIONS:
        fail(
            f"repo is {ver}; this patch needs 0.4.7-mp4line applied first "
            "(apply laf-0.4.7-mp4line-patch.zip, then re-run apply_048.py)"
        )

    if not HANDLERS.exists():
        fail(f"file not found: {HANDLERS} - re-run the Expand-Archive step")
    current = HANDLERS.read_text(encoding="utf-8")

    if REV3_MARKER in current:
        print("[apply_048] ok: handlers.py already carries the rev3 fix")
        print(f"[apply_048] skip __init__.py: already {ver}")
        print("[apply_048] DONE - nothing to do (idempotent).")
        return 0

    # 1. Determine the canonical base.
    if "_SENTENCE_SPLIT" in current:
        print("[apply_048] detect: handlers.py is the rev1/rev2 whole-file "
              "ship (stale script_gen) - restoring canonical from git")
        base = git_show(GIT_SPEC)
        if base is None:
            fail(
                "could not read handlers.py from git. Run:\n"
                "    git show 0406792:backend/laf/jobs/handlers.py > handlers_from_git.py\n"
                "and send me that file - nothing was changed."
            )
        if "voice_slug" not in base:
            fail(
                "git-restored handlers.py has no voice_slug (wrong commit?) "
                "- nothing was changed. Send me handlers_from_git.py "
                "(see previous message)."
            )
        if "_SENTENCE_SPLIT" in base:
            fail("git-restored handlers.py unexpectedly already has the fix "
                 "- nothing was changed; tell me what commit HEAD is.")
        backup_once(HANDLERS, ".bak_048_clobber")
        print(f"[apply_048] ok: canonical handlers.py restored "
              f"(source: {PINNED_COMMIT} or HEAD)")
    else:
        if "voice_slug" not in current:
            fail("handlers.py has no voice_slug - apply 0.4.5-voices FIRST")
        base = current
        print("[apply_048] ok: canonical handlers.py detected on disk "
              "(0.4.5-voices base)")

    # 2. Surgical scene-split edit, each step counted.
    if base.count(OLD_SCENE) != 1:
        fail(f"anchor _scene_count splitter found {base.count(OLD_SCENE)}x "
             "(expected 1) - nothing was changed. Send me handlers_from_git.py.")
    if base.count(OLD_NARR) != 1:
        fail(f"anchor _split_narration splitter found {base.count(OLD_NARR)}x "
             "(expected 1) - nothing was changed. Send me handlers_from_git.py.")
    if base.count("def _scene_count(") != 1:
        fail("anchor 'def _scene_count(' not found uniquely - nothing was changed")

    base = base.replace(OLD_SCENE, NEW_LINE, 1)
    base = base.replace(OLD_NARR, NEW_LINE, 1)
    base = base.replace("def _scene_count(", HELPER_BLOCK + "def _scene_count(", 1)

    # 3. Verify + syntax-check before writing.
    for must in ("_SENTENCE_SPLIT", "def _sentences(", REV3_MARKER):
        if must not in base:
            fail(f"post-edit verification failed: {must!r} missing")
    if OLD_SCENE in base or OLD_NARR in base:
        fail("post-edit verification failed: old punctuation-only split still present")
    try:
        compile(base, "handlers.py", "exec")
    except SyntaxError as exc:
        fail(f"post-edit syntax check failed: {exc} - nothing was changed")
    print("[apply_048] patch: scene split -> newline-aware (both estimators)")
    print("[apply_048] ok: syntax check passed")

    HANDLERS.write_text(base, encoding="utf-8")

    # 4. Version + changelog (idempotent).
    init = REPO / "backend" / "laf" / "__init__.py"
    if ver == VERSION:
        print(f"[apply_048] skip __init__.py: already {VERSION}")
    else:
        backup_once(init, ".bak_048")
        init.write_text(
            re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{VERSION}"',
                   init.read_text(encoding="utf-8"), count=1),
            encoding="utf-8",
        )
        print(f"[apply_048] patch: __version__ -> {VERSION}")

    changelog = REPO / "CHANGELOG.md"
    if not changelog.exists():
        print("[apply_048] skip CHANGELOG.md: file not found")
    elif "## 0.4.8" in changelog.read_text(encoding="utf-8"):
        print("[apply_048] skip CHANGELOG.md: 0.4.8 entry already present")
    else:
        backup_once(changelog, ".bak_048")
        changelog.write_text(
            changelog.read_text(encoding="utf-8").rstrip("\n") + "\n\n"
            + CHANGELOG_ENTRY,
            encoding="utf-8",
        )
        print("[apply_048] patch: CHANGELOG.md 0.4.8 entry appended")

    print("[apply_048] DONE - 0.4.8-scenecount rev3 applied.")
    print("[apply_048] next: python -m pytest tests\\ -q   (expect 161 passed)")
    return 0


CHANGELOG_ENTRY = """## 0.4.8 - Storyboard scenes: newline-aware beat splitting

### Fixed
- Scripts written as one beat per line with no terminal punctuation
  (a qwen3 habit) counted as a SINGLE sentence, so the storyboard
  collapsed to 1 scene and short episodes rendered as one static
  card for their whole runtime (ep10: 22 s on one card).
- Sentence splitting now treats a line break as a boundary too, in
  both the scene-count estimator and the narration splitter. Short
  unpunctuated scripts now get the 3-scene floor; properly
  punctuated scripts are unaffected.
- rev3: the fix is applied surgically on top of the canonical
  handlers.py restored from the project's own git history, so the
  0.4.3 script JSON-grammar contract stays intact.
- Re-run Storyboard on any 1-scene episode to rebuild it, then
  Render again.
"""


if __name__ == "__main__":
    sys.exit(main())
