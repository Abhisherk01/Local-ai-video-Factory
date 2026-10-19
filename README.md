# Local AI Video Factory

A local-first Windows desktop application that manages the complete content lifecycle for short-form video: topic → script → research → episode planning → narration → visuals → editing → subtitles → quality assurance → metadata → scheduling → publishing → analytics.

Designed to operate up to **15 YouTube and Instagram accounts** across different niches using **free, open-source, locally executed components**. No paid generation APIs in the core pipeline. Hardware constraints are respected and stated honestly — the app never promises unlimited generation.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Hardware assessment, licensing, cost boundaries | Done — approved 2026-10-19 |
| 1 | Repository foundation, architecture decisions, design system, Git workflow | Done — verified on owner hardware 2026-10-19 |
| 2 | Desktop shell, first-run wizard, backend, database, health checks | Done — verified on owner hardware 2026-10-19 |
| 3 | Episode model, durable job queue, Ollama/Piper adapters, pipeline UI | Built — this release (fallback paths test-verified; model-backed paths await installs) |
| 3–14 | Models, series engine, rendering, clipping, channels, publishing, analytics, packaging | Planned — see [ROADMAP.md](ROADMAP.md) |

Build machine profile: **Tier 3** (RTX 2050 4 GB VRAM, 16 GB RAM, i5-12450H) — full analysis in [docs/PHASE0-HARDWARE-ASSESSMENT.md](docs/PHASE0-HARDWARE-ASSESSMENT.md).

## Architecture at a glance

```
┌─ Tauri 2 desktop shell — React + TypeScript + Tailwind (12 screens)
│        │ localhost HTTP + WebSocket progress
├─ FastAPI backend, bound to 127.0.0.1 only
│   ├─ SQLite (WAL) + migrations
│   ├─ Durable job queue — concurrency caps, retries, resume after restart
│   └─ GPU-aware worker pool (one GPU job at a time)
│        │ adapter layer
├─ Ollama (LLM)      ├─ faster-whisper (STT)   ├─ Kokoro / Piper (TTS)
├─ FFmpeg/FFprobe (assembly + QC)              ├─ vector/whiteboard renderer (no AI)
└─ optional diffusion adapters (SD1.5+LCM now; Wan 1.3B accent in Phase 7)
```

## Repository layout

```
local-ai-video-factory/
├── index.html, vite.config.ts, package.json   # Vite app root (Tauri-standard layout)
├── src/                 # React app (theme, api client, wizard, home)
├── src-tauri/           # Tauri 2 shell (Rust) — spawns and supervises the backend
├── backend/             # laf: FastAPI app, SQLite + migrations, server entrypoint
├── scripts/             # Windows setup, hardware probe, backend dev launcher
├── tests/               # pytest suite (repo integrity + backend)
├── docs/, design/       # architecture + design tokens
```

## Development quick start (Windows PowerShell)

```powershell
# 1. Verify prerequisites (installs nothing)
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check

# 2. Create the pinned Python environment + backend dependencies
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt

# 3. Run the test suite (expect: 29 passed)
pytest -q

# 4. Install frontend dependencies and run the desktop app (first Rust build takes minutes)
npm install
npm run tauri dev
```

Browser-only UI development (no Rust compile):

```powershell
.\scripts\run-backend-dev.ps1   # terminal 1: backend on 127.0.0.1:8756
npm run dev                     # terminal 2: UI at http://localhost:5173
```

Full setup instructions: [INSTALLATION.md](INSTALLATION.md). Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Optional Phase 3 model installs (Windows PowerShell)

```powershell
# LLM scripting (about 2.6 GB): install Ollama, then pull the Tier-3 model
winget install Ollama.Ollama
ollama pull qwen3:4b

# TTS (about 100 MB): unzip a piper release into <data_dir>\models\piper
#   so piper.exe sits at models\piper\piper.exe, and a voice .onnx at
#   models\piper\voices\en_US-amy-medium.onnx (any en_US voice works).
# Overrides if you prefer other locations: LAF_PIPER, LAF_PIPER_VOICE.
```

The app's Pipeline tab shows live adapter chips; `/api/v1/adapters`
reports exactly what it detected and what to fix.

## Documentation index

| Doc | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, ADR decisions, data model, adapter contracts, queue design |
| [ROADMAP.md](ROADMAP.md) | Phases 0–14 with acceptance gates |
| [docs/DESIGN-SYSTEM.md](docs/DESIGN-SYSTEM.md) | Design principles, palette, typography, component inventory |
| [docs/PHASE0-HARDWARE-ASSESSMENT.md](docs/PHASE0-HARDWARE-ASSESSMENT.md) | Hardware verdict, capability matrix, model shortlist |
| [INSTALLATION.md](INSTALLATION.md) | Setup from zero on Windows |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Known issues and fixes |
| [SECURITY.md](SECURITY.md) | Security and privacy model |
| [LICENSES.md](LICENSES.md) | Third-party licenses and verification status |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branching, commit conventions, commit checklist |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Ground rules this project follows

1. Phases are explicit; each phase ends with passing tests and an approval gate.
2. Nothing is marked "complete" without implementation and tests behind the claim.
3. No secrets, model weights, generated media, or account data ever enter Git.
4. Every non-free or non-local capability is labeled, off by default, and honest about its limits.

## Known limitations (Phase 3, stated honestly)

- The desktop app runs from the development layout (`npm run tauri dev`); a packaged installer arrives in Phase 13.
- The shell resolves Python from the repo venv, `py -3.12`, or `LAF_PYTHON` — a bundled runtime comes with packaging.
- Migrations are forward-only; destructive-change down-migrations are deferred until the schema stabilizes.
- The wizard reports prerequisites; it never installs anything by itself.
- Phase 3 ships the script + TTS-audio steps of the pipeline; model-backed script generation needs Ollama installed (`LAF_OLLAMA_URL`/`LAF_OLLAMA_MODEL` override defaults) and real speech needs Piper (`LAF_PIPER`/`LAF_PIPER_VOICE`). Without them the honest fallback paths run: template scripts and a labeled placeholder tone — never passed off as AI output.
- Kokoro TTS is probe-only in this release; its synthesis wiring lands in Phase 5 (ADR-010).
- Job cancellation applies to queued jobs; in-handler cooperative cancellation lands with queue hardening (roadmap row 8).

## License

MIT — see [LICENSE](LICENSE). Third-party components, models, and fonts carry their own licenses, tracked in [LICENSES.md](LICENSES.md). Nothing in this repository redistributes third-party model weights by default.
