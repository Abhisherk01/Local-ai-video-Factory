# Troubleshooting — Local AI Video Factory

Known issues and fixes, newest phase first. Each entry: symptom → cause → fix. This file grows with every phase; when a fix is found on your machine, it belongs here.

## Phase 3 — pipeline / job queue / adapters

### Two `laf.server` python processes show in Task Manager
**Symptom.** `Get-CimInstance Win32_Process` finds two PIDs matching `*laf.server*` while the app runs.
**Cause.** The backend is spawned with `CREATE_NO_WINDOW` (detached hidden console). Pressing Ctrl+C on the dev terminal kills `laf-shell.exe` but never reaches the backend; `kill_backend` only runs on the graceful exit path. Each hard-killed run leaked one orphan. **Fixed in 0.3.0**: the backend child is assigned to a Windows Job Object with kill-on-close, so it dies with the shell on any exit path. Orphans from *pre-fix* runs still need one manual cleanup:
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*laf.server*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
**Habit.** Close the app window with the X button *before* Ctrl+C-ing the terminal.

### Pipeline shows "ollama off" and script jobs fail with `prereq_missing: ollama_unavailable`
**Cause.** No Ollama daemon is listening on `127.0.0.1:11434` (not installed, not running, or a non-default port).
**Fix.** `winget install Ollama.Ollama`, then `ollama pull qwen3:4b` (about 2.6 GB). If it runs on another port or you want a different model: `LAF_OLLAMA_URL` / `LAF_OLLAMA_MODEL` environment variables. The `/api/v1/adapters` chips update on the next refresh. Until then, script jobs run the labeled template fallback (`fallback_template`).

### Script jobs fail with `prereq_missing: piper_unavailable` or "no voice model"
**Cause.** Piper is resolved as: `LAF_PIPER` env var → `<models_dir>\piper\piper.exe` → `piper` on PATH; voices come from `LAF_PIPER_VOICE` → first `*.onnx` in `<models_dir>\piper\voices`.
**Fix.** Unzip a piper release into the models dir and drop one `.onnx` voice next to it (README "Optional Phase 3 model installs"). Without piper, TTS jobs run the honestly-labeled `fallback_tone` placeholder instead of pretending.

### Jobs are stuck in `queued` and the worker chip says "worker stopped"
**Cause.** The backend was started with `python -m laf.server --no-worker` (debug flag), or the worker thread crashed at boot (check `backend.log` in the data dir).
**Fix.** Restart the backend without `--no-worker`. Queued jobs survive restarts - that is the point of the durable queue - so nothing was lost.

## Phase 2 — desktop shell / backend

### `cargo` / `rustup` is not recognized after installing Rust
**Cause.** PATH changes only reach **new** processes — and new tabs in an already-open Windows Terminal inherit the old PATH.
**Fix.** Close *every* terminal window and open a brand-new one. To verify without a new window:
```powershell
& "$env:USERPROFILE\.cargo\bin\cargo.exe" --version
```
If that works, the install is fine — only your shell is stale.

### `cargo --version` works but building fails with a linker error (`link.exe not found`)
**Cause.** The MSVC C++ toolset is missing (Rust on Windows links with it).
**Fix.** Install Visual Studio 2022 Build Tools with the "Desktop development with C++" workload (`winget install --id Microsoft.VisualStudio.2022.BuildTools -e`), or point the setup script at an existing Visual Studio via vswhere detection: re-run `scripts/setup-windows.ps1 -Check` and read the MSVC row.

### The app window opens but shows "Backend failed to start"
**Diagnosis.** Read the per-session log first: `%LOCALAPPDATA%\com.rajbh.localaivideofactory\backend.log` (or the data dir you configured).
**Common causes.**
- Python 3.12 missing → `py -3.12 -V` must print a version; else `winget install --id Python.Python.3.12 -e`.
- Backend dependencies missing → inside the activated venv: `pip install -r backend/requirements-dev.txt`.
- Custom interpreter needed → set the `LAF_PYTHON` environment variable to a Python 3.12 `python.exe` before launching.

### "the backend did not become healthy within 30 seconds"
**Cause.** The backend process is alive but `/health` never answered — usually an import error inside `laf` (bad venv) or a blocked loopback port.
**Fix.** Check `backend.log` in the data dir. Test the backend manually:
```powershell
.\scripts\run-backend-dev.ps1
# in a second terminal:
curl.exe http://127.0.0.1:8756/health
```

### `npm run tauri dev` fails on the first compile
**Cause.** The first Rust build downloads and compiles ~450 crates; flaky networks or antivirus interference can interrupt it.
**Fix.** Just re-run `npm run tauri dev` (cargo resumes). Exclude the project folder and `%LOCALAPPDATA%\cargo` from real-time scanning if it recurs.

### `npm run dev` shows "Starting local backend..." forever
**Cause.** Browser mode expects the backend from `scripts/run-backend-dev.ps1` (Vite proxies `/laf-api` to port 8756). Without it, every request fails.
**Fix.** Start the backend first, or use the full desktop flow (`npm run tauri dev`) which spawns its own backend.

### Stale `runtime.json` in the data dir after a crash
**Cause.** The handshake file is deleted on clean shutdown only.
**Fix.** Harmless — ignore or delete it. The desktop shell never reads it (it passes its own port/token to the backend); it exists for standalone dev tooling.

### Node warns about engines (v25 "Current" line)
**Cause.** The build machine runs Node 25.x (non-LTS). Vite 7 supports it; some packages warn.
**Fix.** Informational only. If a package ever hard-fails its engines check, install LTS 22 alongside (`winget install --id OpenJS.NodeJS.LTS -e`) — both can coexist.

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
