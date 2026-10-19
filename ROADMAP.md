# Roadmap — Local AI Video Factory

Execution follows the phase order below (aligned with the master spec §21). A phase starts only after the previous phase's tests pass and the owner approves the result. The order may change only when a documented technical dependency requires it (recorded in the changelog).

Status values: Done / In progress / Next / Planned / Blocked.

| Phase | Scope | Acceptance gate | Status |
|---|---|---|---|
| 0 | Hardware assessment, scope, licensing, cost boundaries | Tier-3 plan approved; capability matrix and limitations documented | **Done** (2026-10-19) |
| 1 | Repo init, architecture decisions, design system, Git workflow | Integrity tests pass; docs skeleton complete; conventional commits established | **Done** (this release) |
| 2 | Desktop shell, first-run wizard, FastAPI backend, SQLite + migrations, health checks | App window opens; wizard completes; migrations up/down clean; health checks report GPU/disk/FFmpeg status | Next |
| 3 | Local LLM + TTS integration; script and caption generation | Topic → saved script works with real local model; TTS sample renders; fallback template path proven when no model is installed | Planned |
| 4 | Scene planner, storyboard, style registry, series generation | Script → storyboard with per-scene prompts; 20-episode sample outline passes duplicate detection | Planned |
| 5 | Basic rendering, subtitles, transitions — first complete vertical video | 9:16 MP4 passes automated QC (duration, aspect, audio levels, subtitle timing) | Planned |
| 6 | Clip extraction: transcription, highlight scoring, batch exports | Local video → 5–10 scored, captioned vertical clips with per-clip metadata | Planned |
| 7 | Additional animation engines; optional Wan 2.2 1.3B accent (gated) | Second engine registered end-to-end; Wan accent behind explicit enable + timing budget | Planned |
| 8 | Persistent production queue hardening: quality checks, recovery, resource limits | Kill-and-restart mid-series loses no completed episodes; storage governor enforced | Planned |
| 9 | Multi-account channel manager + editorial calendar | Two isolated account profiles; schedule with conflict detection survives restart | Planned |
| 10 | YouTube publishing adapter + real-account integration tests | Approved-video upload to owner's own channel; idempotent retry proven; quota awareness shown | Planned |
| 11 | Instagram publishing adapter + real-account integration tests | Reel publish to owner's own professional account — or documented honest manual fallback if eligibility fails | Planned |
| 12 | Analytics, experimentation, performance reporting | CSV import works; per-account baselines; weekly summary generated from real metrics only | Planned |
| 13 | Security review, load tests, licensing review, Windows installer | Clean-VM install passes; license audit current; load test at 15-channel schedule simulation | Planned |
| 14 | Final acceptance, backup/restore verification, documentation, release | Definition of Done (spec §22) demonstrated end-to-end, including 100-episode resumability | Planned |

## Standing constraints applied to every phase

- Free and local first; anything paid or cloud-dependent is optional, off by default, and labeled in the UI.
- No fabricated metrics, no fabricated factual claims, no promises of virality or monetization.
- Human approval gates publishing by default; unattended publishing only after explicit per-account opt-in.
- Small, meaningful commits after every verified milestone (see CONTRIBUTING.md).
- Hardware reality is respected: one GPU job at a time; storage governor enforced; 12 Mbit/s downloads are staged operations.

## Explicitly deferred (from Phase 0, owner-approved)

- SDXL / hi-res photoreal images — requires 8 GB+ VRAM.
- Wan 14B, LTX-2 generative video — requires 12–16 GB+ VRAM.
- XTTS-v2 voice cloning — non-commercial license.
- These unlock automatically as config changes if the hardware upgrades; no architectural rework required (ADR-004).
