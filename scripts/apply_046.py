"""0.4.6-ui-info installer patch - run with the project venv:

    python scripts\\apply_046.py

0.4.6 is a FRONTEND + VERSION patch:

  1. src/screens/Pipeline.tsx ships WHOLE inside this zip (ep-number
     chips, per-episode Info panel, job-queue ep tags, overlap fix).
     This script does not modify it - it VERIFIES the extraction
     landed by checking for the 0.4.6 markers before anything else.
  2. backend/laf/__init__.py - sets __version__ = "0.4.6-ui-info".
  3. CHANGELOG.md - appends the 0.4.6 entry.

Rules: idempotent (safe to run twice), requires 0.4.5-voices to be
applied first (handlers.py must already carry voice_slug), and aborts
with nothing changed on any mismatch.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION = "0.4.6-ui-info"
PIPELINE = REPO / "src" / "screens" / "Pipeline.tsx"
MARKERS = ("info v4", "epById", "stageJobSummary", "Hide info")


def fail(msg: str) -> None:
    print(f"[apply_046] ABORT: {msg}")
    sys.exit(1)


def backup_once(path: Path, suffix: str) -> None:
    bak = path.with_name(path.name + suffix)
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[apply_046] backup: {bak.name}")


def main() -> int:
    print(f"[apply_046] repo: {REPO}")

    # 0. Guard: this patch sits on top of 0.4.5-voices.
    handlers = REPO / "backend" / "laf" / "jobs" / "handlers.py"
    if not handlers.exists():
        fail(f"file not found: {handlers}")
    htext = handlers.read_text(encoding="utf-8")
    if "voice_slug" not in htext:
        fail("handlers.py has no voice_slug - apply 0.4.5-voices FIRST")
    print("[apply_046] ok: 0.4.5-voices detected (handlers.py has voice_slug)")

    # 1. Verify the shipped Pipeline.tsx actually landed on disk.
    if not PIPELINE.exists():
        fail(f"file not found: {PIPELINE} - re-run the Expand-Archive step")
    ptext = PIPELINE.read_text(encoding="utf-8")
    missing = [m for m in MARKERS if m not in ptext]
    if missing:
        fail(
            f"Pipeline.tsx is missing 0.4.6 markers {missing} - the zip did "
            "not extract over the repo root (check the destination path)"
        )
    print("[apply_046] ok: Pipeline.tsx carries the 0.4.6 UI (Info panel + ep chips)")

    # 2. Version bump (backed up once, idempotent).
    init = REPO / "backend" / "laf" / "__init__.py"
    if not init.exists():
        fail(f"file not found: {init}")
    text = init.read_text(encoding="utf-8")
    backup_once(init, ".bak_046")
    new_text, n = re.subn(
        r'__version__\s*=\s*"[^"]*"',
        f'__version__ = "{VERSION}"',
        text,
        count=1,
    )
    if n != 1:
        fail("__version__ assignment not found in backend/laf/__init__.py")
    if new_text == text:
        print(f"[apply_046] skip __init__.py: already {VERSION}")
    else:
        init.write_text(new_text, encoding="utf-8")
        print(f"[apply_046] patch: __version__ -> {VERSION}")

    # 3. CHANGELOG entry.
    changelog = REPO / "CHANGELOG.md"
    if not changelog.exists():
        print("[apply_046] skip CHANGELOG.md: file not found")
    else:
        ctext = changelog.read_text(encoding="utf-8")
        if "## 0.4.6" in ctext:
            print("[apply_046] skip CHANGELOG.md: 0.4.6 entry already present")
        else:
            backup_once(changelog, ".bak_046")
            changelog.write_text(
                ctext.rstrip("\n") + "\n\n" + CHANGELOG_ENTRY, encoding="utf-8"
            )
            print("[apply_046] patch: CHANGELOG.md 0.4.6 entry appended")

    print("[apply_046] DONE - 0.4.6-ui-info applied (idempotent).")
    return 0


CHANGELOG_ENTRY = """## 0.4.6 - UI info: episode numbers, Info panel, queue ep tags, overlap fix

### Added
- Episode rows carry an `ep<id>` chip, so the episode number is
  visible at every stage - not only after the first render.
- Per-episode Info button (shows Hide info while open): a compact
  detail panel with status, created/updated stamps, full topic,
  script size + method + 90-char preview, the latest job per stage
  (script / storyboard / render), the selected style and voice, and
  the render output line.
- A queued or running storyboard job now surfaces on its episode row
  (the script and render lines already did).

### Fixed
- Job-queue rows never showed their episode: the `ep <id>` chip sat
  behind a dead condition - `jobById.has(job.id) === false` is always
  false for a job that IS in the map. Queue rows now render
  `ep<id> - <title>` for every job, queued ones included.
- Episode rows no longer overlap on narrow windows: the control
  cluster (style + voice + buttons) moved to its own wrapping line
  instead of a `shrink-0` right-hand cluster that overflowed the
  max-w-3xl card and painted over the next row.
"""


if __name__ == "__main__":
    sys.exit(main())
