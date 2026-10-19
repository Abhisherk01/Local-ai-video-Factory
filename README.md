# Local AI Video Factory

A local-first Windows desktop application that manages the complete content lifecycle for short-form video: topic → script → research → episode planning → narration → visuals → editing → subtitles → quality assurance → metadata → scheduling → publishing → analytics.

Designed to operate up to **15 YouTube and Instagram accounts** across different niches using **free, open-source, locally executed components**. No paid generation APIs in the core pipeline. Hardware constraints are respected and stated honestly — the app never promises unlimited generation.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Hardware assessment, licensing, cost boundaries | Done — approved 2026-10-19 |
| 1 | Repository foundation, architecture decisions, design system, Git workflow | Done — this release |
| 2 | Desktop shell, first-run wizard, backend, database, health checks | Next — awaiting approval |
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
├── docs/                 # Architecture docs, design system, phase reports
├── design/               # Design tokens (single source of truth for UI)
├── scripts/              # Windows setup + hardware probe (PowerShell)
├── tests/                # Test suites (pytest)
├── backend/              # Phase 2: FastAPI app, workers, queue, DB
├── frontend/             # Phase 2: React app consumed by Tauri
└── src-tauri/            # Phase 2: Tauri shell (Rust)
```

## Development quick start (Windows PowerShell)

```powershell
# 1. Verify prerequisites (installs nothing)
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check

# 2. Create the pinned Python environment
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pytest

# 3. Run the test suite
pytest -q
```

Full setup instructions: [INSTALLATION.md](INSTALLATION.md). Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

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

## License

MIT — see [LICENSE](LICENSE). Third-party components, models, and fonts carry their own licenses, tracked in [LICENSES.md](LICENSES.md). Nothing in this repository redistributes third-party model weights by default.
