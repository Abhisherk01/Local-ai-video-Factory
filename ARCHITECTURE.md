# Architecture — Local AI Video Factory

Status: Phase 2 — desktop shell, backend, and database implemented and tested; AI integrations arrive in Phase 3+.
This document is the source of truth for structural decisions. Change requires a new ADR entry.

## 1. System overview

```
┌────────────────────────────────────────────────────────────────────┐
│  Tauri 2 desktop shell (Rust)                                      │
│  └─ WebView2: React 19 + TypeScript + Vite + Tailwind v4              │
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

### ADR-008 — Backend sidecar lifecycle: spawned by the shell, session token, forward-only migrations
**Context.** The React UI needs a stable, secure way to reach the FastAPI backend regardless of which port it binds; the backend must die with the app; the schema must evolve across 14 phases without corrupting user data.
**Decision.** The Tauri shell picks a free 127.0.0.1 port, generates a 128-bit session token, and launches `python -m laf.server` as a child process, passing the token via the `LAF_TOKEN` environment variable (never via argv, never logged). The shell polls `/health` (open endpoint, token-free) until ready or fails honestly after 30 s, pointing at `backend.log` in the data dir. The UI learns the port/token only via the `get_backend_info` IPC command; browser dev mode uses a Vite proxy at `/laf-api` that injects a documented dev token. Migrations are versioned SQL files applied in ascending order inside explicit transactions, tracked in `schema_migrations`; they are forward-only — no down-migrations until the schema stabilizes.
**Consequences.** No port/feature negotiation in config files; another local process cannot call data routes without the token (defense-in-depth on top of 127.0.0.1 binding); backend logs land in one per-session file for support; schema changes are reviewable, ordered, and idempotent to re-run. Packaged-install Python resolution (bundled runtime) replaces the dev-layout resolution in Phase 3+ packaging.

### ADR-009 — Durable job queue, implemented (Phase 3): claims, backoff, heartbeat reclaim, idempotency
**Context.** ADR-005 fixed the architecture (SQLite queue, GPU concurrency 1, idempotent publishing). Phase 3 ships the first real implementation and has to resolve the state machine concretely.
**Decision.** Jobs live in the `jobs` table (migration 0002). Implemented state names: `queued → running → succeeded | failed | cancelled`. This maps ADR-005's sketch onto fewer states with the same guarantees: `pending`/`claimed` merge into `queued` because claiming is a single atomic transition (`BEGIN IMMEDIATE` … `UPDATE … status='running'` — two claims can never take one job); `retrying` becomes `queued` + a `run_after` backoff timestamp (exponential: ~2 s → 8 s → 32 s), so retries are just due-time gating on the same claim path. GPU jobs carry `gpu=1` and are claimable only while no other gpu job is `running` (enforced inside the claim transaction). Every execution increments `attempts`; exhausting `max_attempts` (or a `PrereqMissing` error — retrying cannot install Ollama) ends the job as `failed`. A heartbeat thread refreshes `heartbeat_at` every 20 s while a handler runs; `reclaim_stale()` requeues running jobs whose heartbeat is older than 120 s (boot-time crash recovery — a hard-killed backend loses nothing but the interrupted attempt). `idempotency_key` has a UNIQUE index: a repeated enqueue returns the existing row instead of duplicating it. The worker is one daemon thread with its own SQLite connection (per-thread connections are now the rule, as anticipated in Phase 2); its lifecycle is owned by the FastAPI lifespan, so tests and `python -m laf.server` behave identically. Handlers are pure functions `(payload, job, ctx) -> result` registered in `laf.jobs.handlers`.
**Consequences.** Restart-resume, uniform retry/cancel semantics, and GPU serialization are real today (tested), not roadmap promises. Cancel currently applies to queued jobs only — in-handler cooperative cancellation lands with the queue hardening phase (roadmap row 8). API-route writes still share one connection; correct at single-user scale, revisited if a second worker process is ever added.

### ADR-010 — Generation adapters: probe, honest method labels, no-retry prereqs (Phase 3)
**Context.** The pipeline must work end-to-end on machines without any model installed, must never fake AI output, and later phases add visual engines behind the same seam (ADR-004).
**Decision.** Every adapter answers three contracts: (1) `available()` — a fast, side-effect-free probe returning structured status the UI renders as chips with fix-it detail; (2) generation methods that raise `AdapterUnavailable` with a human-fixable message instead of pretending; (3) results carry an honest `method` label (`local_ollama`, `local_piper`, `fallback_template`, `fallback_tone`) that is stored with the content and shown in the UI. Phase 3 ships: **Ollama** (stdlib urllib against 127.0.0.1:11434; strips qwen3 `<think>` blocks and records that it did), **Piper** (CLI adapter with exe/voice resolution via `LAF_PIPER`/`LAF_PIPER_VOICE` or the models dir), and a **Kokoro probe** that reports detection but refuses synthesis until Phase 5 (kokoro drags in the torch stack; piper is a 10 MB MIT CLI and keeps Tier-3 installs cheap). Job handlers treat missing prerequisites as `PrereqMissing` → immediate failure without retry, unless the caller allowed a fallback (`allow_fallback`), in which case the honest fallback path (template script / placeholder tone) runs and is labeled as such.
**Consequences.** The "no model installed" demo is the same code path as production — only the method label differs. The Phase 3 roadmap gate ("fallback template path proven when no model is installed") is satisfiable by automated tests. Visual engines (Phase 5+) plug into the identical probe/label/refuse contracts.

### ADR-011 — Scene planning is deterministic + model-assisted; duplicate detection is deterministic only (Phase 4)
**Context.** Phase 4 needs script → storyboard with per-scene prompts and a 20-episode series outline that passes duplicate detection. A 4 B model on CPU is unreliable at exactly reproducing narration or emitting strict JSON, and duplicate judgment must be explainable and testable without a model.
**Decision.** (1) The model never touches narration: the script is split into 3-8 ordered scenes deterministically (sentence boundaries, even distribution — concatenated slices always reproduce the full script), and the model only proposes one visual shot per scene as a JSON array validated against the expected count; invalid output fails retryable, and `allow_fallback` substitutes deterministic shot templates labeled `fallback_split`. (2) Scene durations are computed locally from narration length (~2.5 words/s), never generated. (3) Visual prompts compose a registry style (prompt prefix + suffix; 6 builtins seeded by migration 0003, custom styles user-addable, builtins undeletable) around the shot description. (4) Series outline candidates pass through `laf.dedupe` — normalized token-set Jaccard (function-word stoplist, conservative plural folding, 0.6 threshold) — against existing series episodes and each other; duplicates are skipped and reported in the job result, and an all-duplicates outcome is `NonRetryable` (honest, not an error loop). The fallback outline is 20 fixed lexically-distinct angles (`fallback_angles`), which is what makes the roadmap gate testable model-free. (5) `NonRetryable` joins `PrereqMissing` as an immediate-failure class: deterministic store-target losses (episode/series deleted mid-job) end the job on attempt 1 instead of burning full generations — the phase-3 field lesson, promoted to a contract.
**Consequences.** Every storyboard is guaranteed narration-complete on any path; the model's failure surface is a single short shot description per scene (small JSON, high success rate, cheap retries). Duplicate detection is deterministic, explainable ("these two topics share 67% of their content tokens"), and provable in CI without Ollama. The cost: near-duplicates with disjoint wording can pass the detector (it is conservative by design); semantic dedupe, if ever needed, must remain deterministic-and-labeled or become an explicitly opt-in model step.

## 3. Data model (baseline shipped in Phase 2; domain tables arrive with the phases that use them)

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

Phase 2 ships migration 0001 with `app_settings` (key/value, wizard state) and `schema_info`. Phase 3 ships migration 0002 — the first domain slice: `episodes` (title, topic, channel TEXT, status, script_text, script_method) and `jobs` (ADR-009). Phase 4 ships migration 0003: `styles` (slug UNIQUE, prompt prefix/suffix, is_builtin — 6 builtins seeded), `storyboards` (one per episode, UNIQUE, ON DELETE CASCADE, style_slug + method + scene_count + total_duration_s), `storyboard_scenes` (UNIQUE(storyboard_id, idx), narration + visual_prompt + duration_s), `series` (name, premise, requested_count, method), and `episodes.series_id` (ON DELETE SET NULL — deleting a series keeps its episodes). Project/AccountProfile tables deliberately wait for the phases that need them; `channel` stays a plain string until the account model lands (Phase 9), and the end-state `Episode` UNIQUE(project, series, number) constraint arrives with that migration. Each later phase adds its tables in their own numbered migrations as the features that need them land — never before.

## 4. Adapter contracts (interfaces frozen in Phase 3–4)

```
LLMAdapter.generate(spec) -> text
TTSAdapter.synthesize(text, voice, out_path) -> audio_asset
STTAdapter.transcribe(media_path) -> segments[]
VisualEngineAdapter.render(scene, style, assets) -> asset_refs[]
PlatformAdapter.capabilities() -> capability_set
PlatformAdapter.publish(post, media) -> platform_ref | typed_error
```

Every adapter validates inputs, runs as a job (never inline on the API thread), and reports progress events. Phase 3 freezes the concrete shape in `laf/adapters/` (probe/status, generation, honest method labels — ADR-010); LLM and TTS adapters exist today, visual and platform adapters join the same registry later. Platform adapters run **only** after explicit user authorization, respect published quota/rate limits, and are always mocked in the default test suite (real-account tests are separate, manually invoked scripts in Phases 10–11).

## 5. Security boundaries

- Backend binds `127.0.0.1` only; no inbound firewall rule; the Tauri shell is the sole intended client.
- File-path handling: all user-supplied paths resolved and confined to declared storage roots (no traversal).
- Credentials: DPAPI/Credential Manager (ADR-006); never in Git, env files, or logs.
- Log redaction: configured secret values, bearer tokens, and OAuth codes scrubbed at the logging layer.
- Models: safetensors/ONNX formats preferred over pickle; nothing downloaded is executed as code; registry checksums verified at install.
- Dependency hygiene: lockfiles, periodic `pip audit` / `npm audit`, license checks recorded in LICENSES.md.

## 6. Testing strategy

Current default suite: **29 tests** — 7 repo-integrity, 4 SQLite connection, 5 migrations, 3 health, 5 settings/token, 5 system/prereq. Breakdown by layer:

| Layer | Scope | Runs where |
|---|---|---|
| Unit | Pure logic (planning, dedup, scoring, state machines) | Always, default suite |
| Repo integrity | Docs/tokens/scripts hygiene (Phase 1) | Always, default suite |
| Integration-local | FFmpeg renders, SQLite migrations, queue recovery against real temp files | Always, fast |
| Hardware-gated | Diffusion/TTS/STT smoke tests | Only with `LAF_ENABLE_GPU_TESTS=1` |
| External-mocked | Platform APIs always mocked in the default suite | Always |
| Real-account | Manual scripts against owner's own accounts | Phases 10–11 only, explicit opt-in |

## 7. Repository layout (Phase 2 actual)

```
local-ai-video-factory/
├── index.html, vite.config.ts, package.json   # Vite app root (UI at repo root, Tauri-standard)
├── src/                # React app: theme.css (compiled tokens), api client, wizard, home
├── src-tauri/          # Tauri 2 shell: Cargo.toml, main.rs (sidecar lifecycle), icons
├── backend/            # laf package: FastAPI app, SQLite layer, migrations, server entrypoint
├── scripts/            # setup-windows.ps1, probe-hardware.ps1, run-backend-dev.ps1
├── tests/              # pytest: integrity + backend suites (single suite, repo-root run)
├── docs/, design/      # architecture docs, design tokens
```

`design/tokens.json` remains the single source of truth and is compiled into the Tailwind v4 `@theme` block in `src/theme.css`.
