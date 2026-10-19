# Installation — Local AI Video Factory (developer setup, Phase 2)

Target: Windows 11, PowerShell. This document gets you from zero to the
running desktop app. Every command is exact and copy-pasteable.

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 11 (build 26300 verified) | Windows 10 22H2+ should also work; WebView2 is preinstalled on both |
| PowerShell 5.1+ | Built into Windows |
| Git 2.5x | Verified present on the build machine |
| Python **3.12** | Installed via winget in a step below — the system Python 3.14 stays untouched |
| Node.js 20+ | Verified (v25.2.1 on the build machine); LTS 22 also fine |
| Rust toolchain (rustup + cargo) | **Required from Phase 2** — installed via winget in a step below |
| MSVC C++ toolset | Required to link Rust (VS 2022 Build Tools or Community with "Desktop development with C++"); the setup script detects it via vswhere |
| FFmpeg | Needed from Phase 5 — safe to defer |
| Disk | Phase 2 needs ~2 GB (Rust toolchain + node_modules). **Before Phase 3 (model installs): ≥ 60 GB free — cleanup gate from Phase 0** |

## Step 1 — Get the repository

```powershell
# Adjust the file name if your phase zip differs
Expand-Archive "$env:USERPROFILE\Downloads\local-ai-video-factory-phase2.zip" -DestinationPath "$env:USERPROFILE\Documents"
Get-ChildItem "$env:USERPROFILE\Documents\local-ai-video-factory" -Recurse | Unblock-File
cd "$env:USERPROFILE\Documents\local-ai-video-factory"
```

`Unblock-File` clears the Mark-of-the-Web that Windows puts on downloaded
files. Run it from **inside** the extracted folder only.

## Step 2 — Verify the Git history arrived intact

```powershell
git log --oneline
git tag
```

Expected: **16 commits** ending in `chore: bump project version to 0.2.0`, plus tags
`v0.1.0-phase1` and `v0.2.0-phase2`. The exact commit list is in the
delivery notes for this phase.

## Step 3 — Check and complete prerequisites

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check
```

The script reports OK/MISSING for: winget, Git, Node.js, FFmpeg, rustup,
cargo, Python 3.12, and the MSVC C++ toolset. It installs nothing.

Install whatever it lists as missing, individually:

```powershell
winget install --id Python.Python.3.12  -e --source winget --accept-package-agreements --accept-source-agreements
winget install --id Rustlang.Rustup     -e --source winget --accept-package-agreements --accept-source-agreements
# FFmpeg (only needed from Phase 5):
winget install --id Gyan.FFmpeg         -e --source winget --accept-package-agreements --accept-source-agreements
```

Then **close every terminal window** (new tabs in an open Windows Terminal
keep the old PATH) and open a fresh one. Verify:

```powershell
cd "$env:USERPROFILE\Documents\local-ai-video-factory"
py -3.12 -V          # Python 3.12.x
cargo --version      # 1.8x or newer; if missing run: rustup default stable
```

## Step 4 — Python environment + backend dependencies

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt
```

The venv pins 3.12 (`requires-python = ">=3.12,<3.13"`): the local AI
stack has dependable wheels for 3.12, not for the system 3.14.

## Step 5 — Run the test suite

```powershell
pytest -q
```

Expected: **29 passed** — repo integrity (7), SQLite connection (4),
migrations incl. rollback (5), health (3), settings/token (5),
system/prereq (5).

## Step 6 — Frontend dependencies

```powershell
npm install
npm run build
```

`npm run build` runs the TypeScript compiler in strict mode and produces
`dist/`. Any error here means the tree was modified — report it rather
than patching blindly.

## Step 7 — Run the desktop app

```powershell
npm run tauri dev
```

First run compiles ~450 Rust crates (several minutes; later runs are
seconds). Expected result:

1. A native window opens with the dark-graphite theme.
2. "Starting local backend..." appears briefly, then either the
   **first-run wizard** (first launch) or the studio home.
3. The wizard's Prerequisites screen shows live detection results for
   python / ffmpeg / ollama / node / GPU / disk.
4. Completing the wizard writes `onboarding_complete` into the SQLite
   database at `%LOCALAPPDATA%\com.rajbh.localaivideofactory\`.

Closing the window stops the backend process.

### Alternative: browser-only UI development (no Rust compile)

```powershell
.\scripts\run-backend-dev.ps1   # terminal 1: backend on 127.0.0.1:8756
npm run dev                     # terminal 2: UI at http://localhost:5173
```

## Step 8 — Sanity checks (optional)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\probe-hardware.ps1   # read-only hardware probe
```

## Where things stand after these steps

- Desktop shell + backend + database running locally; tests green.
- Before Phase 3 begins: complete the disk cleanup to reach ≥ 60 GB free
  (commands in `docs/PHASE0-HARDWARE-ASSESSMENT.md` §6).

## Next phases will add

Phase 3: durable job queue + episode data model + local LLM/TTS
integration. This document grows with each phase.
