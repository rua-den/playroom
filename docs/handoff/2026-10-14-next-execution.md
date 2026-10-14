# Playroom — next coding execution checkpoint (14/10/2026)

> This file is an implementation handoff, **not** evidence that code/tests have passed.

## Baseline and source of truth

- Latest verified GitHub `main` before writing this handoff: `f7b6f4b8ed6d75db1d1836ea38fe84acbe9b7382`.
- Read `AGENTS.md`, `README.md`, [14/10 review](../reviews/2026-10-14-main-stabilization-review.md), and [GitHub Issue #2](https://github.com/rua-den/playroom/issues/2) first.
- Ignore stale statements that PR #1 is still open: it was merged on 13/10.
- GitHub has no CI workflows or observed checks at the verified baseline.
- Code review confirms a definite error after `GenerationComposer.startGeneration()` persisted an identity can leave `identity.idempotencyKey && !job` true, so a later `submit()` refuses to send. The 503 test checks button appearance, not successful next-click recovery.

## B0 — establish a runnable baseline, **not yet PASS**

1. Verify current `origin/main` and local worktree status; keep every existing edit, do not reset/clean.
2. On the designated Windows host read `C:\Users\huy.nguyen\.codex\RTK.md` and use `rtk` for shell commands as required. Do not assume that file exists in other environments.
3. Backend commands from root:
   - `uv sync --locked --extra test`
   - `uv run --locked --extra test pytest backend/tests -q`
   - `uv run --locked python -m compileall -q backend/playroom`
4. Frontend commands from `frontend`:
   - `npm ci`
   - `npm test`
   - `npm run typecheck`
   - `npm run build`
5. Record actual pass/fail/count, not historical totals. For a failed command, narrow/reproduce/fix locally rather than assuming it is an external blocker.

A read-only GitHub review environment here could fetch source but did not provide the mandated Luna coding agent; an attempted public clone in an isolated shell failed because `github.com` could not resolve. **No runnable baseline tests were executed in that environment**.

## B1 — first implementation task (Issue #2)

Only this coding task is unlocked. Follow `AGENTS.md`: `gpt-5.6-luna` writes code at medium effort, orchestrator independently reviews and tests. If required Luna is unavailable, stop code editing and report the blocking capability. Do not silently replace the coding model.

**Scope:** `frontend/src/components/GenerationComposer.tsx`, `frontend/src/components/GenerationComposer.test.tsx`; broaden only if a failing test proves a dependency.

### RED cases before production edit

- A valid preview followed by a definitive `422` generation POST response: input remains, stale identity is not a permanent barrier; **the next deliberate Send** creates a fresh preview/key/generation. Assert POST bodies/count and `localStorage`, not just enabled button.
- Generation POST returns `409` (stale checkpoint/settings): don't lose typed input; refresh authoritative campaign state before allowing a newly explicit send. No replay with stale identity.
- Network reset, `5xx` or uncertain POST response: preserve existing idempotency identity. A temporary by-key lookup failure or lone 404 is insufficient to authorize a new generate POST. Never auto-dispatch a possibly duplicate paid request.
- Candidate recovery, auto-commit, quota/economy explicit retry, and IME/Shift+Enter remain functional.

### Implementation boundary

- Split **definitive rejection before job reservation** from ambiguous transport/server failures.
- Reuse existing `GenerationIdentity` storage and backend idempotency lookup; don't create a new parallel persistence mechanism.
- Only clear durable identity for a server response guaranteed to mean no job was reserved, and only after matching the current submission identity to avoid cross-branch or newer-request clobbering.
- Keep one visible gameplay Send action and preserve player draft.
- API return contracts, billing caps, persisted transcript/canon, and checkpoint rules do not change.

### GREEN/review gate

Run focused Vitest, entire frontend Vitest, typecheck, build, and `git diff --check`. Observe the new regression RED **before** editing, then GREEN after fix. Check current Git HEAD, review exact diff, push reviewed commit to `main` only after successful verification and confirm new remote HEAD; update this handoff with actual outputs and any remaining problem. If policy or environment prevents validated push, report the candidate diff and precise blocker, do not claim implementation complete.

## Following gates, **not unlocked**

- B2: verify Ollama Cloud's structured narrator segment contract with mocked valid/malformed/truncated/incorrect-character responses, protect against paid retry, and add deterministic GitHub Actions CI.
- B3: local fake-provider end-to-end chat, mobile/IME/reconnect/error smoke.
- B4: live narrator trial only after owner configures provider credential and authorizes a positive cap.
- Task 5 consolidation, Task 6 fork/reroll, Task 7 import/backup, and isolated Task 8 Caddy/VPS after the earlier gates.

No live provider inference or VPS changes are authorized by this handoff.


## Execution update — 14/10/2026 (after PR #3)

**B0/B1: PASS for the reviewed implementation and deterministic CI.**

- Source fix: [PR #3](https://github.com/rua-den/playroom/pull/3), squash merged into `main` at `ead34fbbb56cbe11378b47c9a83a80c54df117e7`. GitHub Issue #2 is closed.
- Reviewed diff: `GenerationComposer.tsx`, its regression tests and `.github/workflows/frontend-ci.yml`. No backend production files were changed by this PR.
- Exact merge-head [Actions run #38503392817](https://github.com/rua-den/playroom/actions/runs/38503392817) is green:
  - Backend `uv run --locked --extra test pytest backend/tests -q`: **265 passed** (as in verified PR job #38503269593); `compileall` PASS.
  - Frontend `npm test`: **79 passed, 3 skipped** (three pre-existing obsolete composer drafts); `npm run typecheck` PASS; `npm run build` PASS.
- Runtime tests are fake/mocked provider tests; **not** a real Ollama Cloud model quality validation, production VPS acceptance or phone-browser smoke.
- B1 repair preserves input on confirmed pre-reservation rejection (e.g. 422), avoids duplicate generation after ambiguous 5xx, checks conflicting 409 key before adoption, and keeps recovery identity when committed transcript cannot be refreshed.
- B1 RED before production edit was **not observed** in the CI environment; green acceptance regressions were observed at the PR and merge HEAD. Do not retrospectively claim a witnessed RED stage.
- **Next:** [Issue #4: verify Ollama narrator segment contract](https://github.com/rua-den/playroom/issues/4) (B2). The scoped direct-implementation fallback recorded in `AGENTS.md` applies only to Issue #2; normal agent routing still applies to new B2 code.
