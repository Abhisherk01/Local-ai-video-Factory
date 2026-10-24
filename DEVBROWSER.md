# Browser dev mode (`scripts\dev-browser.ps1`)

The desktop app and plain-browser dev reach the backend through two different
transports (ADR-008):

| Mode | How it connects |
|------|-----------------|
| Desktop (`npm run tauri dev`) | The Rust shell spawns the backend on a **random free port** and hands port + session token to the WebView via the `get_backend_info` IPC command. Always works; no configuration needed. |
| Browser (`npm run dev`, then `localhost:5173`) | The Vite proxy targets a **fixed port** (`LAF_PORT`, default `8756`) and injects the `X-LAF-Token` header from `LAF_TOKEN`. Needs a manually started backend on that exact port with the same token. |

This is why opening `localhost:5173` in a browser while `npm run tauri dev` is
running produces endless `ECONNREFUSED 127.0.0.1:8756` in the terminal and a
"Backend failed to start / 500:" card in the browser tab: the proxy is
hammering a port the shell-spawned backend will never bind. It is a dev
workflow gap, not a product bug. The desktop window is unaffected.

## What the script does

1. Resolves the desktop app's real data dir from the Tauri identifier in
   `src-tauri\tauri.conf.json` (e.g. `%LOCALAPPDATA%\com.rajbh.localaivideofactory`),
   so browser mode sees the same episodes and DB as the desktop window.
2. Guards before starting anything:
   - refuses to run if the target port is already in use (with the owning PID);
   - warns if `laf-shell` (desktop app) is running - two backends must never
     share one SQLite DB / job worker.
3. Starts the backend:
   `.venv\Scripts\python.exe -m laf.server --port 8756 --data-dir <app data dir>`
   with `LAF_TOKEN=dev-token`. Backend output goes to
   `logs\dev-backend.out.log` and `logs\dev-backend.err.log`.
4. Polls `/health` until it returns `"status": "ok"` (30 s timeout, with an
   early-exit if the backend process dies during startup).
5. Sets `LAF_PORT` + `LAF_TOKEN` and runs `npm run dev` in the foreground.
6. `Ctrl+C` stops Vite **and** kills the backend process.

## Usage

```powershell
cd C:\Users\rajbh\Documents\local-ai-video-factory
.\scripts\dev-browser.ps1

# custom port (LAF_PORT is set for you automatically):
.\scripts\dev-browser.ps1 -Port 8800

# if execution policy blocks local scripts:
powershell -ExecutionPolicy Bypass -File scripts\dev-browser.ps1
```

Then open `http://localhost:5173` - the badge should flip to green
"local backend" and the episode list should show your real library.

## Notes and limits

- Close the desktop app before using browser dev (see guard 2).
- Stop the script with `Ctrl+C`, not by closing the terminal window, or the
  backend process will be orphaned and will keep holding the port
  (`Get-NetTCPConnection -LocalPort 8756` finds the PID to kill).
- No product code is touched by this patch: backend, frontend, and the Tauri
  shell are unchanged, and the backend version string stays
  `0.4.8-scenecount`. This is dev tooling only.
