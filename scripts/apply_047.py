"""0.4.7-mp4line installer patch - run with the project venv:

    python scripts\\apply_047.py

0.4.7 is a FRONTEND + VERSION patch:

  1. src/screens/Pipeline.tsx ships WHOLE inside this zip. This script
     does not modify it - it VERIFIES the extraction landed by checking
     for the 0.4.7 markers before anything else.
  2. backend/laf/__init__.py - sets __version__ = "0.4.7-mp4line".
  3. CHANGELOG.md - appends the 0.4.7 entry.

Rules: idempotent (safe to run twice), requires 0.4.6-ui-info to be
applied first (Pipeline.tsx must carry the info-v4-era markers before
this zip replaces it), and aborts with nothing changed on any mismatch.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = "0.4.7-mp4line"
PIPELINE = REPO / "src" / "screens" / "Pipeline.tsx"
# 0.4.7 markers: the new fit-v5 header tag + the rebuilt mp4 line.
MARKERS_047 = ("fit v5", "voice: ${mp4Voice}", "shrink-0 whitespace-nowrap")


def fail(msg: str) -> None:
    print(f"[apply_047] ABORT: {msg}")
    sys.exit(1)


def backup_once(path: Path, suffix: str) -> None:
    bak = path.with_name(path.name + suffix)
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[apply_047] backup: {bak.name}")


def main() -> int:
    print(f"[apply_047] repo: {REPO}")

    # 0. Guard: this patch sits on top of 0.4.5-voices (backend).
    handlers = REPO / "backend" / "laf" / "jobs" / "handlers.py"
    if not handlers.exists():
        fail(f"file not found: {handlers}")
    htext = handlers.read_text(encoding="utf-8")
    if "voice_slug" not in htext:
        fail("handlers.py has no voice_slug - apply 0.4.5-voices FIRST")
    print("[apply_047] ok: 0.4.5-voices detected (handlers.py has voice_slug)")

    # 1. Verify the shipped Pipeline.tsx actually landed on disk.
    if not PIPELINE.exists():
        fail(f"file not found: {PIPELINE} - re-run the Expand-Archive step")
    ptext = PIPELINE.read_text(encoding="utf-8")
    missing = [m for m in MARKERS_047 if m not in ptext]
    if missing:
        fail(
            f"Pipeline.tsx is missing 0.4.7 markers {missing} - the zip did "
            "not extract over the repo root, or 0.4.6-ui-info was never "
            "applied (check the destination path)"
        )
    print("[apply_047] ok: Pipeline.tsx carries the 0.4.7 mp4 line (fit v5)")

    # 2. Version bump (backed up once, idempotent).
    init = REPO / "backend" / "laf" / "__init__.py"
    if not init.exists():
        fail(f"file not found: {init}")
    text = init.read_text(encoding="utf-8")
    backup_once(init, ".bak_047")
    new_text, n = re.subn(
        r'__version__\s*=\s*"[^"]*"',
        f'__version__ = "{VERSION}"',
        text,
        count=1,
    )
    if n != 1:
        fail("__version__ assignment not found in backend/laf/__init__.py")
    if new_text == text:
        print(f"[apply_047] skip __init__.py: already {VERSION}")
    else:
        init.write_text(new_text, encoding="utf-8")
        print(f"[apply_047] patch: __version__ -> {VERSION}")

    # 3. CHANGELOG entry.
    changelog = REPO / "CHANGELOG.md"
    if not changelog.exists():
        print("[apply_047] skip CHANGELOG.md: file not found")
    else:
        ctext = changelog.read_text(encoding="utf-8")
        if "## 0.4.7" in ctext:
            print("[apply_047] skip CHANGELOG.md: 0.4.7 entry already present")
        else:
            backup_once(changelog, ".bak_047")
            changelog.write_text(
                ctext.rstrip("\n") + "\n\n" + CHANGELOG_ENTRY, encoding="utf-8"
            )
            print("[apply_047] patch: CHANGELOG.md 0.4.7 entry appended")

    print("[apply_047] DONE - 0.4.7-mp4line applied (idempotent).")
    return 0


CHANGELOG_ENTRY = """## 0.4.7 - UI fit: render line keeps duration + voice visible

### Fixed
- The green render line truncated as a whole, so on real Windows paths
  the `(32.5s)` duration and the `- voice: en_US-ryan-high` suffix were
  always cut off. The line is now a flex row: the path truncates (hover
  it for the full path via tooltip) while the duration and voice stay
  pinned at the end and never clip.
- Header proof tag bumped to `fit v5`.
"""


if __name__ == "__main__":
    sys.exit(main())
