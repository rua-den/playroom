# Playroom — main re-review and stabilization gate (2026-10-14)

## Verified source state

- Repository: `rua-den/playroom`; reviewed **main** at `88330516c7bb9b266267c68369f09783711e6227`.
- PR #1 is **merged**, not draft/open. `feat/playroom-mvp` is an ancestor of main and is behind main by two commits.
- Main includes local synthetic demo, chat-first auto-commit, additive roleplay segments, OpenRouter and Ollama Cloud integration.
- At review time, the repository did not contain `.github/workflows/`; GitHub listed no Actions runs or commit statuses for this HEAD.
- This was a **GitHub source/document review only**. No local checkout, Python/Node test run, model API call, deployment, or live phone trial was performed in this review. Old handoff test totals do not certify this HEAD.

## Findings, ordered for the next coding batch

### S1 — High: Definitive generation failure can leave the composer blocked

**Evidence:** `frontend/src/components/GenerationComposer.tsx` persists a generation identity before POST. In `startGeneration`, a non-quota, non-recoverable HTTP error from `api.generate` is thrown without clearing or resolving that identity. On a subsequent Send, `submit` blocks whenever `identity.idempotencyKey && !job`. The current 503 failure test checks only that the button is enabled and input retained, not that a subsequent Send can complete.

**Risk:** A definitive validation/configuration error can trap the user in an unrecoverable local identity while the Send button appears usable.

**Required RED/GREEN:** After a definite 4xx with verified no-created-job semantics, preserve user text, clear/resolve only the definitively failed identity, and allow a fresh preview/key/Send. For ambiguous network/5xx and failed by-key lookup, **retain the original identity**; never issue a second generate POST automatically. Add explicit 409/stale-checkpoint behavior that refreshes authoritative state without discarding the draft. Test second-click behavior, not just button appearance. Do not treat an arbitrary 404 lookup as proof that an uncertain POST never reached the backend.

### S2 — High risk to live trial: Ollama narrator requires structured segments without native enforcement

**Evidence:** `backend/playroom/model_profiles.py` pins Ollama `structured_output=False`; `backend/playroom/generation.py::_narrator_request` accordingly sends no native narrator schema. For non-test/non-legacy profiles, `_narrate` nevertheless requires the response to parse as attributed `segments` JSON or reports `SCHEMA_INVALID`. The adapter mock proves transport/usage normalization, not prose-model compliance.

**Risk:** A successful Ollama streaming HTTP response may still fail the Playroom narrator contract. This is **a compatibility risk, not a measured live-model failure**.

**Required RED/GREEN:** Mock valid/invalid/truncated Ollama completion and prove valid text is parsed, attributed and committed exactly once, while malformed/refused/truncated output never commits. Preserve cost/attempt accounting and zero implicit paid retries. Only after the owner has explicitly configured the credential and confirmed a positive cap should a separately authorized live narrator trial occur; log no key or private transcript.

### S3 — Medium: Player markup policy and tests disagree with the latest UI spec

**Evidence:** `docs/superpowers/specs/2026-10-13-chat-story-first-design.md` defines `**...**` as the action/thought notation. `backend/playroom/roleplay_segments.py` also interprets `*...*` as action; `backend/tests/test_roleplay_segments.py` deliberately tests this extra behavior.

**Disposition:** Do **not** blindly change parser semantics. First decide whether single-star is a supported alias or should be ordinary dialogue; then synchronize product spec, composer help, parser and regression tests. Preserve raw input, escaped stars and incomplete delimiters.

### S4 — Medium: CI and outdated status documentation

**Evidence:** No GitHub Actions workflow or main-head checks were found. `README.md` and `docs/handoff/2026-10-13-state.md` still describe feature-branch/PR handoff as current despite the main merge. The latter remains valuable historical evidence and should not be rewritten as if it described today's HEAD.

**Required:** Add minimal CI covering locked Python tests/compile and frontend install/test/typecheck/build, without real-provider calls or secrets. Correct README main-branch pointers; preserve old handoff as dated historical record and link to this new review.

### S5 — Test debt, not by itself a runtime failure

**Evidence:** `frontend/src/components/GenerationComposer.test.tsx` still contains skipped tests with expectations tied to removed draft/commit controls. Review their intent and replace with current one-button/immutable-candidate behavior where relevant; do not unskip obsolete requirements.

## Execution plan (small batches; each gated)

### B0 — Reproduce baseline at exact HEAD before implementation

1. Check main SHA and worktree status; preserve user changes. Follow `AGENTS.md` and local `RTK.md` only when running on the named Windows host.
2. Run `uv sync --locked --extra test`, `uv run --locked --extra test pytest backend/tests -q`, `uv run --locked python -m compileall -q backend/playroom`.
3. From `frontend/`: `npm ci`, `npm test`, `npm run typecheck`, `npm run build`.
4. Record exact outputs. A failure triggers scoped recovery and a concrete failing test; never replace failure evidence with historical totals.

### B1 — Repair definite-vs-ambiguous Send recovery

- Owner: coding agent designated by `AGENTS.md` (`gpt-5.6-luna`); review/accept independently.
- Narrow files: `frontend/src/components/GenerationComposer.tsx` and its test only unless regression requires otherwise.
- RED tests: definite 422, 409 stale checkpoint, lost POST response/by-key transient 5xx, and retry after confirmed failure; assert POST count and storage identity.
- Acceptance: never double-dispatch uncertain paid work; no permanent disabled-by-identity Send after a proved definitive failure; textarea survives failures.
- Commit only after focused tests and frontend suite/typecheck/build pass.

### B2 — Provider/schema gate plus main CI

- Owner: designated coding agent; independent review.
- Narrow files: Ollama provider/generation adapter tests, smallest production fix only if tests prove necessary; add `.github/workflows/ci.yml`.
- Validate valid structured response, malformed JSON, incorrect character IDs, finish-reason truncation, quota/cap preflight, OpenRouter regression and no paid fallback.
- CI must be deterministic, fake/mocked provider only; require tests, typecheck, build, compileall and whitespace checks.
- A green CI run must be observed at the actual merged SHA; workflow text alone is not acceptance.

### B3 — Fake end-to-end chat gate

- Demo login → campaign → dialogue/action → preview → generation → validated auto-commit → reload → next turn.
- Exercise 360/390/430px, IME, Shift+Enter, background/reconnect, and error recovery; preserve previously committed transcripts.
- Attributed NPCs must be selected checkpoint characters with pinned profile versions; no invented actor ID or player-controlled actions.
- This is synthetic acceptance **only**, not narrative model quality.

### B4 — User-authorized real model trial, then long-play

- Only after B1–B3 PASS, user-provided in-app credentials/cap and explicit authorization: exercise real narrator with short safe synthetic input and inspect schema/cost/latency. Do not assume pricing or quality from mocks.
- Next product milestone: Task 5 consolidation proposals (schema/source validation → bounded explicit jobs → review UI), then Task 6 branch isolation, Task 7 import/backup, Task 8 audited isolated Caddy release.
- No VPS/network changes or automatic paid calls as part of B0–B3.

## Execution constraints and current gate

- The repository requires `gpt-5.6-sol` coordination and **`gpt-5.6-luna`** for coding; if Luna delegation is unavailable, stop **code implementation**, do not quietly substitute a different coding model.
- Preserve `playrooom` privacy, transcript/canon provenance, checkpoint/branch isolation, credential secrecy, single-owner auth, and player-persona agency.
- No source change or runnable test was performed while writing this document. **B0–B4 are PLANNED, not PASS.**
