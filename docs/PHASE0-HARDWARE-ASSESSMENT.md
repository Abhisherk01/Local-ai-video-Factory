# Local AI Video Factory — Phase 0: Hardware Assessment & Feasibility

Owner: rajbh · Assessed: 2026-10-19 · Status: DRAFT — awaiting owner approval
Source data: PowerShell hardware probe (2026-10-19), vendor specifications, license checks where noted. Verify exact model versions and licenses again at install time.

---

## 1. Verdict

The probe corrects two assumptions from the questionnaire:

1. **GPU is an NVIDIA RTX 2050 laptop GPU with 4 GB VRAM** (not "8 GB+"). The machine is **Tier 3 (GPU-lean)**, not Tier 2.
2. The three binding constraints are **4 GB VRAM**, **37 GB free disk (of 476 GB)**, and **12 Mbit/s download**. Disk is the immediate gate; VRAM shapes model selection permanently.

Despite this, the **full end-to-end factory remains viable** on this machine: stylized local image generation + deterministic motion-design visuals carry production quality, narration/subtitles/scripts are unaffected, and generative video is demoted from default to **experimental accent**. Nothing in the core workflow requires a paid API.

## 2. Measured hardware

| Component | Value | Impact on design |
|---|---|---|
| OS | Windows 11 Home Single Language, build 26300, 64-bit | No blockers. WebView2 preinstalled (Tauri OK). No Hyper-V needed. |
| CPU | Intel i5-12450H, 8c/12t | Solid for TTS/ASR/FFmpeg encode; CPU styles fully viable |
| RAM | 15.7 GB | Enough for SD1.5 + 4B LLM + queue; NOT enough for comfortable 14B video offload. One GPU job at a time is mandatory |
| GPU | RTX 2050, 4 GB VRAM (driver 552.27), + Intel UHD iGPU | CUDA works; SD1.5+LCM fine; SDXL/Wan-14B/LTX excluded. NVENC available for fast renders |
| Disk | C: 37 GB free of 476 GB | **Below floor.** Cleanup required before model installs (§6) |
| Network | 12 Mbit/s down (~1.4 MB/s) | Model downloads are deliberate, staged operations (~10 min/GB) |
| Tools | Git, Python 3.14, Node+npm, Docker Desktop, winget present; FFmpeg absent | FFmpeg added Phase 1; Python 3.12 added for backend venv (§10) |

## 3. Feature buckets (per master spec §3)

### A. Runs locally now — no compromise
Desktop shell (Tauri), FastAPI backend, SQLite + migrations, persistent job queue, calendar, analytics UI. Scripts/captions/series bibles via local LLM. Narration (Kokoro/Piper), transcription (faster-whisper). Vector, whiteboard, stickman, diagram, map and motion-graphics styles (programmatic, deterministic, fast). FFmpeg assembly: Ken Burns, transitions, subtitles, audio normalization; NVENC encode. Clip extraction from local videos (transcribe → scene detect → score → vertical crops). All publishing adapters, scheduling, idempotency, QC — CPU-bound work, unaffected by the GPU.

### B. Runs with smaller / quantized models — the Tier-3 way
- Scene images: **SD 1.5 + LCM (4-step)** at 512–640 px vertical, FFmpeg-lanczos upscale to 1080 → ~8–20 s/image
- LLM: **Qwen3-4B Q4** (~2.6 GB, fits or near-fits in VRAM); optional 8B Q4 with partial CPU offload at reduced speed
- ASR: **whisper small int8** (medium optional later)
- TTS: **Kokoro-82M** (strong English) with Piper fallback

### C. Requires stronger hardware — deferred, documented, not silently dropped
SDXL / hi-res photoreal images (8 GB+). Wan 14B, LTX-2 (12–16 GB+). Comfortable Wan 1.3B without offload pain (6–8 GB). These unlock on a future GPU upgrade; the adapter architecture keeps them one config away.

### D. Optional / external — costed, off by default
Paid generation APIs: excluded by spec. XTTS-v2 voice cloning: excluded (non-commercial CPML license). YouTube/Instagram APIs: free but quota- and review-gated (§8).

## 4. Capability matrix

| Capability | Implementation | Local/External | Cost | HW req. | License | Status |
|---|---|---|---|---|---|---|
| Desktop shell | Tauri 2 + React + TS + Tailwind | Local | $0 | CPU | MIT/Apache-2.0 | Phase 2 |
| Backend API | FastAPI, bound 127.0.0.1 | Local | $0 | CPU | MIT | Phase 2 |
| Database | SQLite + migrations | Local | $0 | CPU | Public domain | Phase 2 |
| Job queue | Custom durable queue (one GPU job at a time) | Local | $0 | CPU | Own code | Phase 2/8 |
| LLM (scripts, captions, series) | Ollama + Qwen3-4B Q4 | Local | $0 | 4 GB VRAM or CPU | Apache 2.0 | Phase 3 |
| LLM (higher quality, optional) | Ollama + Qwen3-8B Q4, partial offload | Local | $0 | +16 GB RAM | Apache 2.0 | Optional |
| TTS narration | Kokoro-82M ONNX; Piper fallback | Local CPU | $0 | None | Apache 2.0 / MIT | Phase 3 |
| ASR / subtitles | faster-whisper small int8 | Local | $0 | CPU ok, GPU faster | MIT | Phase 3/6 |
| Scene images | SD 1.5 + LCM-LoRA (or DreamShaper 8 LCM), diffusers | Local GPU | $0 | 4 GB @ 512–640 px | OpenRAIL-M (per-model check) | Phase 5 |
| Motion/vector/whiteboard styles | Programmatic renderer + FFmpeg | Local | $0 | CPU | Own code | Phase 4–5 |
| Generative video (accent) | Wan 2.2 1.3B GGUF, ComfyUI or diffusers | Local | $0 | 4 GB VRAM + offload; 15–30 min/clip | Apache 2.0 | Phase 7, gated |
| Generative video (heavy) / LTX-2 | Excluded on this hardware | — | — | 12–16 GB+ | LTX: custom license | Deferred |
| Assembly / render | FFmpeg/FFprobe (x264 or NVENC) | Local | $0 | CPU/GPU | LGPL-2.1/GPL build | Phase 5 |
| YouTube publishing | YouTube Data API v3 (OAuth) | External API, free | $0 (quota) | — | Google ToS | Phase 10 |
| Instagram publishing | IG Content Publishing API (Reels) | External API, free | $0 | Business acct + Meta review | Meta ToS | Phase 11 |
| Voice cloning | XTTS-v2 | **Excluded** | — | — | CPML non-commercial | Excluded |
| Stock assets | CC0/public-domain sources, per-asset provenance | External download | $0 | — | Per-asset | Phase 5+ |
| Reference repos | MoneyPrinterTurbo, OpenMontage, StickmanVD, AnimeGANv3, 2 agent skills | Inspect only | $0 | — | **Unverified — check before any code use** | Phase 1/7 review |

## 5. Model shortlist — core set ≈ 6–8 GB

Download times at measured 12 Mbit/s ≈ 10 min/GB. Staged as explicit, resumable batch steps.

| Model | Size | Purpose | Time @ 12 Mbit/s |
|---|---|---|---|
| Qwen3-4B (Ollama, Q4_K_M) | ~2.6 GB | Primary LLM: scripts, captions, series bibles | ~30 min |
| SD 1.5 + LCM-LoRA (or DreamShaper 8 LCM) | ~2–4 GB | Scene images, thumbnails | ~25–45 min |
| faster-whisper small int8 | ~0.5 GB | ASR / subtitle timing | ~5 min |
| Kokoro-82M ONNX | ~0.4 GB | Primary TTS narration | ~4 min |
| Piper en_US voices (fallback) | ~0.1 GB | Backup TTS | ~1 min |
| **Core total** | **~6–8 GB** | | **~1.5–2 h staged** |
| *Optional:* Qwen3-8B Q4 | ~5 GB | Higher-quality long-form drafting | ~55 min |
| *Optional:* Wan 2.2 1.3B GGUF | ~3 GB | Experimental hook clips | ~35 min |

Exact current-best variants re-verified at install; alternatives exist in each slot if a model is deprecated.

## 6. Storage plan & the disk gate

**Floor: ≥ 60 GB free before Phase 3 model installs. Target: 80–100 GB. Currently 37 GB → cleanup gate.**

Read-only diagnostics first:

```powershell
docker system df
wsl --list -v
"{0:N1} GB npm cache" -f ((Get-ChildItem "$env:LOCALAPPDATA\npm-cache" -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1GB)
```

Reclaim options (each your call):
- Docker Desktop is installed but this stack does not use it. If unused: uninstall (frees program + WSL vhdx, often 5–15 GB), or `docker system prune -a` if keeping it.
- Windows Settings → System → Storage → Temporary files (Windows Update Cleanup, Delivery Optimization): typically 5–20 GB. Or `cleanmgr /d C:`.
- `npm cache clean --force`; delete `%LOCALAPPDATA%\pip\cache` contents.
- Optional: `powercfg /h off` frees ~6.4 GB (hiberfil) — tradeoff: no hibernate/fast startup.

App storage policy (designed in from Phase 2): configurable model/media/cache directories on C:, automatic intermediate-file cleanup after successful renders (keep finals + quality reports), storage dashboard with a configurable cap and warnings.

Budget: dev tooling ~8 GB (Rust toolchain, node_modules, Python venv incl. PyTorch) + models 6–8 GB + finals ~10–15 GB first year + governed temp ≤ 1 GB.

## 7. Throughput estimates (this machine, 60 s 9:16 video, 8 scenes)

| Stage | Time |
|---|---|
| Script + storyboard (Qwen3-4B, in/near VRAM) | 30–90 s |
| Narration (Kokoro, CPU) | 10–30 s |
| 8 × SD1.5-LCM images (512–640 px) | 1.5–4 min |
| Assembly + subtitles + QC (FFmpeg, NVENC) | 2–5 min |
| **End-to-end** | **≈ 6–12 min, mostly unattended** |

- 15 channels × 1 video/day ≈ 1.5–3 h GPU-active → feasible as an overnight batch
- 100-episode series ≈ 11–20 h across several resumable overnight runs
- Wan 1.3B accent clip adds 15–30 min each — hooks only, optional, never on the critical path
- These are engineering estimates, validated against real renders in Phase 5 before any promise is locked in

## 8. Platform constraints affecting the 15-channel goal (honest math)

- **YouTube quota:** default 10,000 units/day per project; `videos.insert` costs 1,600 units → **~5–6 uploads/day safe ceiling**. 15 channels × 1/day = 15 uploads = 24,000 units → requires either a free quota-extension request to Google or a spread cadence (e.g., each channel every 2–3 days ≈ 5–7 uploads/day). Pilot phase (3 channels daily) fits comfortably.
- **OAuth testing mode:** until the app is verified, refresh tokens expire in 7 days and the app is limited to test users — acceptable for personal use; the UI needs a smooth re-auth flow. Verification is free.
- **Instagram:** Business/Creator account + linked Facebook Page + Meta app with `instagram_content_publish` (App Review). In Development Mode, publishing works only for accounts holding app roles — sufficient for your own pilot accounts. 50 posts/24 h per account.
- **Upload bandwidth:** only download was measured. Run fast.com → "Show more info" and note the upload figure before Phase 10 (affects multi-account upload scheduling).

## 9. Known limitations v1

1. No SDXL/photoreal imagery; stylized SD1.5 at 512–640 px upscaled to 1080.
2. Generative video = experimental accent (Wan 1.3B, 480p, long renders). Not the default visual.
3. LTX-2 and Wan 14B excluded on this hardware; one config change away if the GPU upgrades.
4. 12 Mbit/s: every model change is a deliberate 30–60 min download; no mid-project model churn.
5. Disk gate: cleanup to ≥ 60 GB free is a hard prerequisite for Phase 3.
6. 16 GB RAM: one GPU job at a time (enforced by the queue); heavy multitasking during batches degrades throughput.
7. YouTube quota caps uploads at ~5–6/day/project until an extension is granted — shapes the 15-channel cadence.
8. OAuth testing-mode tokens expire weekly until app verification.
9. TTS voices are recognizably synthetic; mitigate with good voice choice, pacing, music — and recommend YouTube's AI-content disclosure where applicable.
10. Whisper can hallucinate on silence/music; QC checks (§ spec 11) catch and flag it.
11. AnimationGAN-style style transfer (AnimeGANv3) stays unverified until its license is checked; do not plan content around it yet.

## 10. Tooling notes for Phases 1–2

- Python 3.14 is installed, but PyTorch/diffusers/faster-whisper wheel support for 3.14 is not dependable yet → **install Python 3.12 via winget** (`winget install Python.Python.3.12`); the `py` launcher coexists; backend venv pins 3.12 with a lockfile.
- FFmpeg absent → `winget install Gyan.FFmpeg` in Phase 1 dev setup.
- Rust toolchain required for Tauri (`rustup`), installed in Phase 2.
- Node already present for the frontend. Docker present but unused by this stack.

## 11. Approval checklist (gate to Phase 1)

- [ ] Approve Tier-3 plan and the ~6–8 GB core model set
- [ ] Accept the disk-cleanup gate (≥ 60 GB free before Phase 3)
- [ ] Optional decision: Wan 2.2 1.3B in or out of scope for Phase 7
- [ ] Note your fast.com upload speed when convenient
- [ ] Approve Phase 1 scope: repository init, docs skeleton, design system, Git workflow
