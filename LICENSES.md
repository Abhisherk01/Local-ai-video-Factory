# Licenses — Local AI Video Factory

This project's own code is MIT-licensed (see `LICENSE`). This file tracks third-party components: what they are, under what license, and their verification status. **Nothing here is legal advice.** License texts for bundled components ship with the installer in Phase 13; nothing restrictive is redistributed before that review.

## Project stack

| Component | Use | License | Commercial use | Verification status |
|---|---|---|---|---|
| Tauri 2 | Desktop shell | MIT / Apache-2.0 | Yes | Verified (upstream) |
| React, Vite | Frontend | MIT | Yes | Verified (upstream) |
| Tailwind CSS | Styling | MIT | Yes | Verified (upstream) |
| FastAPI, Uvicorn, Pydantic | Backend | MIT / BSD-3 | Yes | Verified (upstream) |
| SQLite | Database | Public domain | Yes | Verified (upstream) |
| pytest | Testing | MIT | Yes | Verified (upstream) |
| keyring | Credential storage (Phase 10) | MIT | Yes | Verified (upstream) |
| Inter (font, via @fontsource) | UI typography | SIL OFL 1.1 | Yes (embedding allowed) | Verified |
| JetBrains Mono (font, via @fontsource) | Mono typography | SIL OFL 1.1 | Yes (embedding allowed) | Verified |
| Lucide icons | Icon set | ISC | Yes | Verified |
| FFmpeg / FFprobe | Media assembly and QC | LGPL-2.1+ (GPL build variant when x264 enabled) | Yes, with license texts and source offer distributed | To re-verify exact build config at packaging (Phase 13) |

## Models (downloaded at install time — never committed to this repo)

| Model | Use | License | Commercial use | Verification status |
|---|---|---|---|---|
| Qwen3-4B (Ollama, Q4) | LLM: scripts, captions, series planning | Apache-2.0 | Yes | Verified upstream; re-verify exact build at install |
| Stable Diffusion 1.5 + LCM-LoRA (or DreamShaper 8 LCM) | Scene images, thumbnails | CreativeML OpenRAIL-M (per-model check at download) | Yes, with use restrictions | Re-verify each concrete weight file at install |
| faster-whisper small int8 | Speech transcription | MIT (code); models per OpenAI Whisper terms | Yes | Verified upstream |
| Kokoro-82M ONNX | Primary TTS narration | Apache-2.0 | Yes | Verified upstream; re-verify voice-pack terms |
| Piper (fallback TTS) | Backup narration | MIT | Yes | Verified upstream |
| Wan 2.2 1.3B GGUF (optional, Phase 7 accent) | Short generative clips | Apache-2.0 | Yes | Verified upstream (2026-10); re-verify at install |

## Explicitly excluded for license reasons

| Component | Reason |
|---|---|
| XTTS-v2 (voice cloning) | CPML license is non-commercial |
| Coqui XTTS voice packs (same terms) | Non-commercial |
| Any model with unverified or restrictive custom terms (e.g., some "community license" video models) | Excluded until a documented review clears them |

## Reference repositories — inspected, not yet integrated

| Repository | Intended take-away | License status |
|---|---|---|
| MoneyPrinterTurbo | Pipeline structure patterns | **Unverified — must check before any code use** |
| OpenMontage | Editing/template ideas | **Unverified** |
| Stickman Video Director | Stickman style reference | **Unverified** |
| AnimeGANv3 | Style transfer signals | **Unverified — community reports restrictive custom terms; treat as unusable until cleared** |
| youtube-agent-skill / instagram-agent-skill | Planning/caption/analytics patterns | **Unverified** |

Per project rules, these are inspected for ideas; no code, assets, or characters are copied until licenses are verified as compatible, and integration (if any) happens through modular adapters or isolated packages.

## Reference products (design inspiration only)

Colossyan, TopMediaI, OpenArt, ClipShip, EveryGen — closed products; no code or assets are used from them.
