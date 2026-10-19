# Troubleshooting — Local AI Video Factory

Known issues and fixes, newest phase first. Each entry: symptom → cause → fix. This file grows with every phase; when a fix is found on your machine, it belongs here.

## Phase 1 — repository / environment

### `running scripts is disabled on this system`
**Symptom.** PowerShell refuses to run a `.ps1` file from the repo.
**Cause.** Default execution policy blocks scripts.
**Fix.** Don't loosen the machine-wide policy; bypass per invocation:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check
```

### Downloaded scripts "blocked" even with bypass
**Symptom.** `Unblock-File` needed repeatedly, or zip-extracted files behave oddly.
**Cause.** Windows Mark-of-the-Web on files from the internet.
**Fix.**
```powershell
Get-ChildItem . -Recurse | Unblock-File
```

### `winget` is not recognized
**Cause.** App Installer missing or stale PATH.
**Fix.** Install/update "App Installer" from the Microsoft Store, open a new terminal, retry. If still missing: `winget` lives at `$env:LOCALAPPDATA\Microsoft\WindowsApps\` — confirm that directory is in PATH.

### `py -3.12` works but `python` still shows 3.14
**Cause.** That is expected: `python` resolves to the system install; the project venv pins 3.12.
**Fix.** Always create the venv with `py -3.12 -m venv .venv` and work inside it (prompt shows `(.venv)`). Check with `python --version` *inside* the activated venv — it must print 3.12.x.

### FFmpeg installed but `ffmpeg -version` fails
**Cause.** PATH updated only for new terminals, or winget install completed while old shells stayed open.
**Fix.** Open a new terminal and retry. If still failing:
```powershell
winget list Gyan.FFmpeg
```
If listed but not found, add its install location to PATH (Settings → System → About → Advanced system settings → Environment Variables), or reinstall with `-Install`.

### Git warns `LF will be replaced by CRLF`
**Cause.** Line-ending conversion between Linux-authored files and Windows.
**Fix.** Harmless. To normalize consistently:
```powershell
git config --global core.autocrlf true
```

### `error: filename too long` during Git operations
**Cause.** Windows MAX_PATH limits.
**Fix.**
```powershell
git config --global core.longpaths true
```

### `pytest` runs with the wrong Python or can't find pytest
**Cause.** Venv not activated, or activated in a different terminal tab.
**Fix.** Re-run `.\.venv\Scripts\Activate.ps1` in the terminal you're using; confirm `python --version` shows 3.12.x; then `pytest -q`.

### Model downloads (later phases) crawl at ~12 Mbit/s
**Cause.** Measured link speed — expected, not a bug.
**Fix.** Downloads are staged operations with resume support. Start large model batches overnight; the queue in Phase 8+ treats them as resumable jobs.

## General

### App data, models, and renders filling drive C:
**Fix.** Storage locations are configurable (`LAF_DATA_DIR`, `LAF_MODELS_DIR` — see `.env.example`). The app's storage governor (Phase 8+) warns at configured caps and auto-cleans intermediates after successful renders. Keep ≥ 60 GB free before any model install.

### Docker Desktop is installed — does this project need it?
**No.** The stack is native by decision (ADR-003). Docker is unused by the core pipeline; uninstalling it reclaims several GB if you don't use it for other work (`winget uninstall Docker.DockerDesktop`), but nothing here requires that.
