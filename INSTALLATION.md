# Installation — Local AI Video Factory (developer setup, Phase 1)

Target: Windows 11, PowerShell. This document covers validating the repository foundation. The runnable application (desktop shell + backend) arrives in Phase 2 and will extend this document.

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 11 (build 26300 verified) | Windows 10 22H2+ should also work; WebView2 is preinstalled on both |
| PowerShell 5.1+ | Built into Windows |
| Git | Verified present on the build machine |
| Python **3.12** | Installed via winget in the step below — the system Python 3.14 stays untouched |
| Node.js LTS | Verified present; needed from Phase 2 |
| FFmpeg | Installed via winget in the step below; needed from Phase 5 |
| Rust toolchain | Needed from Phase 2 (Tauri); optional to install now |
| Disk | Phase 1 needs < 1 GB. **Before Phase 3 (model installs): ≥ 60 GB free — cleanup gate from Phase 0** |

## Step 1 — Get the repository

```powershell
# Adjust the source path to wherever the phase zip was saved
Expand-Archive "$env:USERPROFILE\Downloads\local-ai-video-factory-phase1.zip" -DestinationPath "$env:USERPROFILE\Documents"
Get-ChildItem "$env:USERPROFILE\Documents\local-ai-video-factory" -Recurse | Unblock-File
cd "$env:USERPROFILE\Documents\local-ai-video-factory"
```

`Unblock-File` clears the Mark-of-the-Web that Windows puts on downloaded files (without it, PowerShell scripts may refuse to run).

## Step 2 — Verify the Git history arrived intact

```powershell
git log --oneline
```

Expected: 8 commits, the oldest being `chore: initialize repository with git hygiene, license, and project metadata`, the newest `docs: add readme`, plus tag `v0.1.0-phase1` on the final commit.

If you plan to commit on this machine (you will, in later phases), set your identity once:

```powershell
git config --global user.name "rajbh"
git config --global user.email "your-email@example.com"
```

## Step 3 — Check prerequisites

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check
```

This reports OK/MISSING for: winget, Git, Python 3.12, Node.js LTS, FFmpeg, Rust. It installs nothing. To install missing items:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Install
```

Then **open a new terminal** (PATH changes only apply to new sessions) and re-run with `-Check`.

## Step 4 — Create the pinned Python environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pytest
```

The `py` launcher keeps Python 3.12 (project) and Python 3.14 (system) side by side without conflict. `requires-python = ">=3.12,<3.13"` in `pyproject.toml` documents the pin: the local AI stack has dependable wheels for 3.12, not for 3.14.

## Step 5 — Run the tests

```powershell
pytest -q
```

Expected: **7 passed** — the repository integrity suite (required files present, design tokens valid, no live secrets in `.env.example`, changelog/roadmap complete, `.gitignore` hygiene, PowerShell scripts ASCII-safe for PS 5.1).

## Step 6 — Sanity-check the hardware probe (optional)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\probe-hardware.ps1
```

Same read-only probe used in Phase 0; useful later to re-verify the machine after upgrades.

## Where things stand after these steps

- Repository foundation validated on your machine, history intact, tests green.
- The application itself (window, wizard, backend, database) is Phase 2 — nothing else to run yet, by design.
- Before Phase 3 begins: complete the disk cleanup to reach ≥ 60 GB free (commands in `docs/PHASE0-HARDWARE-ASSESSMENT.md` §6).

## Next phases will add

Phase 2: `backend/` (FastAPI + SQLite + queue), `frontend/` (React app), `src-tauri/` (Tauri shell), first-run wizard, health checks. This document grows with each phase — commands are always exact and copy-pasteable.
