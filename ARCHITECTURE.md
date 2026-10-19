# Architecture — Local AI Video Factory

Status: Phase 1 — decisions recorded as ADRs; implementation code arrives in Phase 2.
This document is the source of truth for structural decisions. Change requires a new ADR entry.

## 1. System overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Tauri 2 desktop shell (Rust)                                      │
│  └─ WebView2: React 18 + TypeScript + Vite + Tailwind              │
│     12 screens: setup wizard, dashboard, content studio, series    │
│     manager, storyboard preview, clip extraction, render queue,    │
│     model manager, channels, calendar, analytics, settings/logs    │
└──────────────┬─────────────────────────────────────────────────────┘
               │ HTTP + WebSocket (progress events) on 127.0.0.1 only
┌──────────────▼─────────────────────────────────────────────────────┐
│  FastAPI backend (Python 3.12 venv)                                │
│  ├─ REST API + WS progress bus                                     │
│  ├─ SQLite (WAL mode) + migrations                                 │
│  ├─ Durable job queue: claims, heartbeats, retries, boot recovery  │
│  └─ Worker pool with concurrency classes (cpu: N, gpu: 1)          │
└───────┬──────────┬──────────┬──────────┬───────────────────────────┘
        │          │          │          │
   Ollama     faster-     Kokoro/     FFmpeg/FFprobe
   (LLM)      whisper     Piper       (assembly, QC, NVENC)
              (STT)       (TTS)
        │
   Diffusion adapters (optional, hardware-gated):
   SD 1.5 + LCM images now; Wan 2.2 1.3B accent clips in Phase 7
```

## 2. Architectural decision records

### ADR-001 — Desktop stack: Tauri + React/TS + FastAPI backend
**Context.** One unified Windows app must orchestrate a Python-native AI ecosystem (diffusers, faster-whisper, Ollama) on a 16 GB RAM machine.
**Decision.** Tauri 2 shell with a React/TypeScript/Vite/Tailwind frontend; Python 3.12 FastAPI backend as a supervised child process on 127.0.0.1.
**Consequences.** Small installer and low shell memory (Tauri/WebView2) instead of Electron; Python keeps first-class access to the free AI stack; the shell supervises the backend and offers restart/clean shutdown.

### ADR-002 — Database: SQLite with WAL and migrations
**Context.** Local-first, zero-service, backup-friendly storage for projects, jobs, accounts, schedules, metrics.
**Decision.** Single SQLite database in WAL mode, schema managed by a migration tool from Phase 2; backup = file copy with a documented safe-copy procedure.
**Consequences.** No server to install or break; concurrent readers OK; writers serialized by the queue by design.

### ADR-003 — No Docker; native Windows installs
**Context.** Owner prefers native installs; Docker Desktop exists on the machine but adds moving parts and disk weight.
**Decision.** Python venv + Ollama Windows installer + winget for Git/FFmpeg/Rust. Docker is never required by the core pipeline.
**Consequences.** Fewer failure surfaces; packaging (Phase 13) bundles or bootstraps the same natives; if a future component truly needs containers, that becomes a documented optional layer.

### ADR-004 — Visual engines are adapters behind a storyboard contract
**Context.** Ten style families must be interchangeable, hardware-gated, and honestly labeled (spec §8).
**Decision.** A `VisualEngineAdapter` contract converts storyboard scenes into assets. Each engine declares: method label (`vector-animation`, `motion-graphics`, `generative-image`, `video-model`), license, model size, VRAM class, and install status in a model/engine registry. Outputs inherit the method label so slideshows are never presented as generative video.
**Consequences.** Style families slot in incrementally (vector/whiteboard first, SD1.5-LCM in Phase 5, Wan accent in Phase 7); weak hardware degrades gracefully by swapping engines, not rewriting pipelines.

### ADR-005 — One durable job queue; GPU concurrency = 1
**Context.** 100-episode series must resume after crashes; 4 GB VRAM forbids concurrent GPU jobs; publishing must never double-post.
**Decision.** All long work runs as queued jobs in SQLite: states `pending → claimed → running → done | failed | retrying | cancelled`, heartbeat-based stale reclaim, boot-time recovery requeues orphaned `running` jobs as `retrying`. Concurrency classes: CPU pool (configurable), GPU class locked to 1. Publish jobs carry an idempotency key enforced by a unique constraint.
**Consequences.** Cancel/pause/resume/retry are uniform across every feature; restarts lose nothing completed; VRAM OOM cascades are structurally prevented.

### ADR-006 — Credentials only via Windows Credential Manager; no secrets in env or logs
**Context.** OAuth tokens (YouTube, Instagram) and any future secrets must never touch Git, plaintext files, or logs (spec §17).
**Decision.** Secrets stored via Windows Credential Manager (DPAPI-protected) through the `keyring` package from Phase 10. `.env` carries only paths and flags. A log-redaction layer scrubs token patterns and configured secret values before anything is written.
**Consequences.** Backups of app data exclude credentials by default; exporting/restoring accounts requires explicit re-authentication on the target machine.

### ADR-007 — Model plan pinned to Tier 3 hardware
**Context.** Probe found RTX 2050 4 GB VRAM, 16 GB RAM, 12 Mbit/s down, 37 GB free disk (see `docs/PHASE0-HARDWARE-ASSESSMENT.md`).
**Decision.** Core set: Qwen3-4B Q4 (LLM), SD 1.5 + LCM (images, 512–640 px), faster-whisper small int8 (STT), Kokoro-82M with Piper fallback (TTS). Wan 2.2 1.3B GGUF is an optional Phase 7 accent. SDXL, Wan 14B, and LTX-2 are excluded until a documented hardware upgrade.
**Consequences.** Downloads stay ~6–8 GB; throughput targets are 6–12 min per 60 s 9:16 video; every model slot has a named fallback if deprecated.

## 3. Data model preview (normalized in Phase 2 migrations)

| Entity | Notable fields / constraints |
|---|---|
| `Project` | id, name, niche, language, aspect_ratio, settings |
| `Series` | id, project_id, premise, series_bible, style_rules, status |
| `Episode` | id, project_id, series_id?, number, title, script, storyboard, status — UNIQUE(project_id, series_id, number) |
| `Job` | id, type, payload, status, attempts, max_attempts, next_run_at, heartbeat_at, concurrency_class, idempotency_key? |
| `Asset` | id, episode_id, kind (image/audio/video/subtitle), path, engine_label, provenance |
| `AccountProfile` | id, platform, display_name, niche, language, brand rules, schedule tz, enabled — strict isolation; every post references exactly one account |
| `ScheduleEntry` | id, account_id, episode_id, run_at, state, conflict_hash |
| `Post` | id, episode_id, account_id, platform_state, platform_media_id, idempotency_key UNIQUE(account_id, episode_id) |
| `MetricSnapshot` | id, post_id, captured_at, metrics JSON, source (api/csv-import) |
| `ModelRecord` | id, name, engine, license, size_bytes, vram_class, install_status, checksum |

## 4. Adapter contracts (interfaces frozen in Phase 3–4)

```
LLMAdapter.generate(spec) -> text
TTSAdapter.synthesize(text, voice, out_path) -> audio_asset
STTAdapter.transcribe(media_path) -> segments[]
VisualEngineAdapter.render(scene, style, assets) -> asset_refs[]
PlatformAdapter.capabilities() -> capability_set
PlatformAdapter.publish(post, media) -> platform_ref | typed_error
```

Every adapter validates inputs, runs as a job (never inline on the API thread), and reports progress events. Platform adapters run **only** after explicit user authorization, respect published quota/rate limits, and are always mocked in the default test suite (real-account tests are separate, manually invoked scripts in Phases 10–11).

## 5. Security boundaries

- Backend binds `127.0.0.1` only; no inbound firewall rule; the Tauri shell is the sole intended client.
- File-path handling: all user-supplied paths resolved and confined to declared storage roots (no traversal).
- Credentials: DPAPI/Credential Manager (ADR-006); never in Git, env files, or logs.
- Log redaction: configured secret values, bearer tokens, and OAuth codes scrubbed at the logging layer.
- Models: safetensors/ONNX formats preferred over pickle; nothing downloaded is executed as code; registry checksums verified at install.
- Dependency hygiene: lockfiles, periodic `pip audit` / `npm audit`, license checks recorded in LICENSES.md.

## 6. Testing strategy

| Layer | Scope | Runs where |
|---|---|---|
| Unit | Pure logic (planning, dedup, scoring, state machines) | Always, default suite |
| Repo integrity | Docs/tokens/scripts hygiene (this phase) | Always, default suite |
| Integration-local | FFmpeg renders, SQLite migrations, queue recovery against real temp files | Always, fast |
| Hardware-gated | Diffusion/TTS/STT smoke tests | Only with `LAF_ENABLE_GPU_TESTS=1` |
| External-mocked | Platform APIs always mocked in the default suite | Always |
| Real-account | Manual scripts against owner's own accounts | Phases 10–11 only, explicit opt-in |

## 7. Planned repository growth

Phase 2 adds `backend/` (FastAPI app package, migrations, queue, workers), `frontend/` (Vite app), and `src-tauri/` (Rust shell). `design/tokens.json` remains the single source of truth and compiles into Tailwind theme + CSS variables.
