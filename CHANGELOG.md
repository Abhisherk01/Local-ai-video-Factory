# Changelog

## 0.4.0 - Phase 4: scene planner, storyboard, style registry, series

### Added
- Scene planner + storyboard (ADR-011): a scripted episode can now be
  split into 3-8 ordered scenes, each with its narration slice, a
  composed text-to-image visual prompt, and a presentation-pace
  duration estimate (~2.5 words/s, computed locally - never invented
  by the model). Migration 0003 ships `styles`, `storyboards`,
  `storyboard_scenes`, `series` and `episodes.series_id`.
- Style registry: 6 builtin visual styles seeded by the migration
  (dark_cinematic, clean_product, warm_documentary, bold_motion,
  retro_analog, minimal_mono); custom styles creatable via
  /api/v1/styles; builtins are undeletable. A style is a reusable
  prompt prefix + suffix pair that conditions every scene prompt.
- Series generation: one premise expands into a season of episode
  drafts (series_outline_gen on Ollama, series_outline_fallback for
  the model-free path - 20 fixed lexically-distinct angles). Outline
  candidates pass deterministic duplicate detection (laf.dedupe:
  normalized token-set Jaccard, function-word stoplist, conservative
  plural folding, 0.6 threshold); duplicates are skipped and reported
  in the job result, never silently dropped. Gate: the 20-episode
  sample outline passes duplicate detection model-free (tested).
- NonRetryable job errors (ADR-010 extension): deterministic failures
  (episode/script/style/series missing) fail the job on attempt 1
  instead of burning the remaining attempts - closes the phase-3
  field lesson from the "episode disappeared mid-job" incident.
- Handlers: storyboard_gen, storyboard_fallback, series_outline_gen,
  series_outline_fallback (registry now 8 types). Model JSON is
  parsed tolerantly (code fences stripped, retryable on invalid
  output); narration splitting is deterministic, so no narration is
  ever lost or invented between scenes on any path.
- API: /api/v1/styles (list/create/delete), /api/v1/series (create +
  outline job, list, inspect, delete), /api/v1/episodes/{id}/storyboard
  (enqueue + fetch; 400 on unscripted episodes and unknown styles).
- Pipeline UI: per-episode style picker + Storyboard action + inline
  scene-plan panel (honest method label per scene plan); Series card
  with outline generation, live job status and accepted/skipped
  counts; storyboarded status chip; series tag on episode rows.
- Tests: 76 -> 108 (dedupe unit + 20-episode gate, storyboard
  handlers incl. fake Ollama JSON/fences/wrong-count paths, series
  acceptance + skip reporting, API surface, worker NonRetryable
  integration).

### Fixed
- Backend: `episode N disappeared mid-job` is now classified
  non-retryable (was: two wasted full generations before the job
  ended failed; observed in the field on 0.3.0).

### Notes
- No Rust changes in this release; the Windows shell is untouched
  (version bump only), so no MSVC compile risk is introduced.
- ollama generate calls for storyboard/series pass `num_ctx: 8192`
  explicitly to avoid silent context truncation on longer scripts.
- LAF_OLLAMA_TIMEOUT (introduced in 0.3.0 hotfix ccc9fc8) applies to
  the new generation paths as well; default 600 s.

## 0.3.0 - Phase 3: content pipeline foundations

### Added
- Durable SQLite job queue (ADR-009): atomic claims, GPU concurrency 1,
  exponential-backoff retries, heartbeat-based stale reclaim on boot,
  idempotent enqueue, queued-job cancellation.
- Episode data model (migration 0002): episodes + jobs tables.
- Background worker thread (own DB connection, heartbeat loop) owned by
  the FastAPI lifespan; `python -m laf.server --no-worker` debug flag.
- Generation adapters (ADR-010): Ollama LLM (stdlib HTTP, <think> strip),
  Piper TTS CLI (exe/voice resolution), Kokoro availability probe
  (synthesis wiring lands in Phase 5). Honest method labels on every
  result: local_ollama / local_piper / fallback_template / fallback_tone.
- Handlers: script_gen, script_fallback, tts_render, tts_fallback -
  the model-free fallback paths make the pipeline provable before any
  model is installed.
- API: /api/v1/episodes (+POST {id}/script), /api/v1/jobs (+/stats,
  +/{id}/cancel), /api/v1/adapters availability probes.
- Pipeline UI screen: episode CRUD, script enqueue, live job queue with
  stats, cancel action, adapter status chips; Studio/Pipeline nav.
- Shell: Windows Job Object kill-on-close for the backend child - the
  Ctrl+C orphaned-backend class of bugs is structurally fixed.
- Tests: 29 → 76 (queue mechanics, handler contracts incl. a fake
  Ollama HTTP server, cross-platform Piper stub, API coverage, worker
  end-to-end + crash-recovery reclaim).

### Fixed
- Shell: enable the windows-sys `Win32_System_Threading` feature —
  `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` is feature-gated behind it
  despite living in the JobObjects module, which broke the MSVC compile
  of the Job Object kill-on-close fix (caught by owner-hardware
  verification; shipped in the phase3-r2 zip).

### Notes
- ADR-009 documents the implemented state names as a deliberate
  simplification of ADR-005's sketch (same guarantees, fewer states).
- Model-backed script/TTS verification on owner hardware requires
  installing Ollama and Piper (optional section in INSTALLATION.md).

## 0.2.0 - Phase 2: desktop shell + backend + health checks

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); versioning follows [SemVer](https://semver.org/).

## [0.2.0] — 2026-10-19

### Added
- Tauri 2 desktop shell (`src-tauri/`): spawns the Python backend as a managed child process on a random 127.0.0.1 port, generates a per-session token (passed via `LAF_TOKEN`, never logged), polls `/health` until ready, exposes `get_backend_info` IPC, kills the backend on exit, and writes per-session backend logs to the data dir (ADR-008).
- FastAPI backend (`backend/laf/`): `/health` probe (db status, version, uptime), token-gated data routes via a constant-time ASGI middleware, system routes for runtime paths, path validation, and real prerequisite detection (python, ffmpeg, ollama, node, GPU via nvidia-smi, disk free), and settings API backed by SQLite. Standalone entrypoint `python -m laf.server` with structured JSON logging (no tokens in logs).
- SQLite layer: WAL-mode connections (autocommit, foreign keys, busy timeout) and a forward-only migration runner (transactional per file, tracked in `schema_migrations`). Migration 0001 ships `app_settings` + `schema_info` (ADR-002, ADR-008).
- React 19 + TypeScript + Vite 7 + Tailwind v4 frontend at the repo root: theme compiled from `design/tokens.json` (dark graphite, teal accent), bundled Inter/JetBrains Mono (OFL, no runtime web fetch), api client with Tauri IPC + browser-proxy fallback, first-run wizard (welcome → live prerequisites → storage validation → finish) and a studio home placeholder.
- Tests: 22 new backend tests (connection, migrations incl. rollback, health, token enforcement, settings, system) — default suite now **29 passed**.
- Windows tooling: `scripts/run-backend-dev.ps1` for browser-mode development.

### Fixed
- `scripts/setup-windows.ps1`: rewritten detection after Phase 1 owner verification exposed Windows PowerShell 5.1 false-OK rows and raw .NET type names in the version column. Verdicts now come only from `Get-Command`; version strings are best-effort; MSVC C++ toolset detection via `vswhere` added (required for Rust/Tauri linking).

### Decisions
- ADR-008 backend sidecar lifecycle: shell-spawned child process, session token over env var, Vite proxy for browser dev, forward-only migrations.

### Known limitations (honest)
- Dev-layout run only (`npm run tauri dev`); packaged installer is Phase 13.
- Python resolution: repo venv → `py -3.12` → `LAF_PYTHON`; bundled runtime comes with packaging.
- Migrations are forward-only; reversible down-migrations deferred (ROADMAP note).

## [0.1.0] — 2026-10-19

### Added
- Phase 1 repository foundation: Git hygiene (`.gitignore`, `.env.example`), MIT license, project metadata with Python pinned to 3.12.x.
- Documentation skeleton: README, ARCHITECTURE (with ADR-001…007), ROADMAP (phases 0–14 with acceptance gates), SECURITY, LICENSES, INSTALLATION, TROUBLESHOOTING, CONTRIBUTING.
- Design system v0.1: `design/tokens.json` (dark graphite theme, teal accent, 4-px grid, density and motion tokens) plus `docs/DESIGN-SYSTEM.md` with the 12-screen component inventory.
- Windows tooling: `scripts/setup-windows.ps1` (prerequisite check / winget install) and `scripts/probe-hardware.ps1` (read-only hardware probe used in Phase 0).
- Repository integrity test suite (pytest, stdlib-only) — 7 tests covering required files, token validity, secret hygiene, and PowerShell ASCII safety.

### Decisions
- ADR-001 Tauri + React/TS + FastAPI stack; ADR-002 SQLite/WAL; ADR-003 no Docker; ADR-004 visual-engine adapter contract with honest method labeling; ADR-005 durable SQLite job queue with GPU concurrency 1 and idempotent publishing; ADR-006 Windows Credential Manager for all secrets; ADR-007 Tier-3 model plan (SD1.5+LCM, Qwen3-4B, whisper small, Kokoro/Piper; Wan 1.3B optional accent in Phase 7).

### Security
- Secrets, model weights, generated media, and app data excluded from Git from the first commit; `.env.example` ships empty values only.

## Phase 0 — 2026-10-19 (pre-repository)
- Hardware probe executed on the build machine: Windows 11 Home (build 26300), i5-12450H, 15.7 GB RAM, RTX 2050 4 GB, 37 GB free disk, 12 Mbit/s down.
- Verdict: Tier 3 (GPU-lean). Full report in `docs/PHASE0-HARDWARE-ASSESSMENT.md`.
- Owner approved the Tier-3 plan, the ~6–8 GB core model set, and the disk-cleanup gate (≥ 60 GB free before Phase 3 installs).

## 0.4.5 - Voices: per-episode narration voice picker

### Added
- Piper voice registry (`laf.voices`): ten curated, download-verified
  en_US/en_GB voices (5 female, 5 male) with honest metadata and a
  per-voice delivery preset (`length_scale` speech-rate dial - piper
  has no native emotion parameter; pace/voice choice is the honest
  lever). Custom on-disk voices are listed too, flagged `custom`.
- `GET /api/v1/voices` (installed voices + catalog + voices_dir).
- Render requests accept `voice_slug`; the UI gained a per-episode
  voice picker next to the style picker. `auto` (the default) keeps
  the pre-0.4.5 behaviour byte-identical. Unknown slugs are rejected
  at enqueue with a 400 - no burned job attempts.
- Render results record the voice actually used (`voice` field);
  the Pipeline mp4 line and job rows surface it.
- `scripts/add_voice.ps1`: downloads any catalog voice (both .onnx and
  .onnx.json) from rhasspy/piper-voices v1.0.0 into
  `<models_dir>/piper/voices/`, e.g. `scripts\add_voice.ps1 ryan`.
- `video_render` + `tts_render` resolve the voice at run time from the
  job payload; a vanished voice file falls back to the adapter default
  and the result says which voice was used.
