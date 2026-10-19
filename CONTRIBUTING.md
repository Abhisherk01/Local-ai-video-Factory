# Contributing — Local AI Video Factory

Single-developer project, but the discipline below is what keeps a 15-phase build coherent. These rules are binding for all future phases.

## Workflow

1. **Phase gates.** Work happens in the numbered phases from ROADMAP.md. A new phase starts only after the previous one's tests pass and the owner approves the summary.
2. **Branches.** Trunk-based: `main` is always shippable. Short-lived branches named `feat/phaseN-<topic>`, `fix/<topic>`, `docs/<topic>` are merged back after tests pass. Direct small commits to `main` are acceptable for solo work when tests pass.
3. **Small, meaningful commits.** One logical change per commit, after it is verified. Never batch unrelated changes.
4. **Tests before "done".** No phase (or feature) is marked complete until its actual implementation and tests support the claim. Run `pytest -q` before committing anything that touches code.
5. **Docs move with code.** Any decision that changes structure updates ARCHITECTURE.md (new ADR if it revises an existing decision), and user-visible changes update the CHANGELOG.

## Commit message convention

Conventional Commits, present tense, no fluff:

```
chore: initialize desktop application
feat: add local model readiness checks
feat: implement script workspace
fix: keep render queue alive after backend restart
docs: record ADR-008 visual engine registry
test: validate vertical video exports
refactor: extract platform adapter base class
```

Scope hints go in the body when useful (what changed, why, what test covers it).

## Commit checklist

- [ ] `pytest -q` passes (or the relevant frontend test runner in later phases)
- [ ] No secrets, tokens, `.env` values, model weights, or media files staged — check `git status` before every commit
- [ ] No generated media or logs accidentally added (`.gitignore` covers the usual paths)
- [ ] Docs updated if behavior or structure changed
- [ ] CHANGELOG.md updated for anything user-visible or decision-level

## Tags

Each approved phase is tagged at its final commit: `v0.X.Y-phaseN` (e.g., `v0.1.0-phase1`), matching the CHANGELOG version entry.

## What never happens

- Force-pushing or rewriting history once a phase is tagged.
- Committing directly on a machine without the tests passing first.
- Bypassing the phase approval gate "just this once".
