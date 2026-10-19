# Security Policy — Local AI Video Factory

Scope: this is a single-owner, local-first desktop application. There is no hosted service, no inbound network exposure, and no third-party data processor in the core pipeline.

## Principles

1. **Local-first.** Content, database, media, and analytics live on the owner's machine. The app functions without any cloud account for local production features.
2. **Least privilege.** The backend binds to `127.0.0.1` only. Platform integrations request the narrowest OAuth scopes that work, and only after explicit owner action.
3. **No silent externals.** Any network call beyond localhost (model downloads, platform APIs, update checks) is user-initiated or user-configured and logged.

## Credential handling (authoritative rules)

- OAuth client secrets and access/refresh tokens are stored **only** in Windows Credential Manager (DPAPI-protected) via the `keyring` package, starting in Phase 10.
- Environment variables and `.env` carry **paths and flags only** — never secret values. `.env.example` ships empty values and is the only env file tracked in Git.
- Logs pass through a redaction layer that scrubs: bearer tokens, OAuth authorization codes and refresh tokens, configured secret values, and account identifiers where feasible. Redaction failures are treated as bugs blocking release.
- App-data backup/restore excludes the credential store by default; restoring accounts on another machine requires explicit re-authentication.
- OAuth tokens are refreshed automatically where the platform allows, and revocable from the app's account screen (which surfaces the platform-side revocation link as well).

## Things that must never enter Git

- Real credentials, tokens, cookies, or `.env` with values.
- Model weights (`*.gguf`, `*.safetensors`, `*.onnx`, `*.ckpt`, `*.pt`, `*.bin`).
- Generated or imported media (video/audio/images) and rendered outputs.
- Account data exports, analytics CSVs, or database files.

The default test suite enforces parts of this mechanically (see `tests/test_repo_integrity.py`).

## Input handling and external content

- All file paths from the UI are validated and confined to declared storage roots (no path traversal out of media/data directories).
- Clip-import URLs: only officially supported, authorized download paths are used; DRM, private-content restrictions, and platform terms are never bypassed — when downloading is not permitted, the workflow falls back to local-file import.
- Downloaded models: safetensors/ONNX formats are preferred over pickle-based formats; models are never executed as code; the model registry records checksums, and installs verify them.
- No arbitrary downloaded scripts are executed without explicit user consent and a review step.

## Dependency and license hygiene

- Python and Node dependencies are pinned via lockfiles; updates are deliberate, not floating.
- `pip audit` / `npm audit` run at each phase boundary; findings triaged before the next phase starts.
- Third-party licenses are tracked in LICENSES.md with a verification status; components with unverified or restrictive licenses are not integrated until cleared.

## Reporting

Single-owner project: security issues are fixed on sight. If you fork or distribute this project, replace this section with your own contact information.
