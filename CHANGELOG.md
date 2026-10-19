# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); versioning follows [SemVer](https://semver.org/).

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
