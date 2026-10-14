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

## B2 Ollama Cloud research checkpoint (2026-10-14)

- Source and official-provider-doc contract audit is complete: [Ollama B2 contract review](../reviews/2026-10-14-ollama-b2-contract-review.md); [Issue #4](https://github.com/rua-den/playroom/issues/4) contains the expanded acceptance matrix.
- Material design decision: Ollama Cloud supports OpenAI-compatible **JSON mode**, but official docs say Cloud **does not support strict structured outputs**. Narrator nevertheless needs attributed JSON segments for Playroom; its prompt should demand them **unconditionally** for production narrator profiles, with post-parse speaker/version validation retained.
- Official prices checked on 2026-10-14: gpt-oss:120b USD $0.15/1M input, $0.60/1M output; cached input $0.014/1M. Verified against vendor pages, not a live account/endpoint request. Model quality is still unmeasured.
- **B2 code/tests not started**: AGENTS.md delegates coding to Luna except for the limited Issue #2 fallback. No Luna dispatch tool is available in this session; B2 is explicitly **NOT PASS**. The independent review itself is a docs-only commit and requires no app test re-run.


## B2 mocked narrator contract — implementation acceptance

- **PASS for deterministic/mock-provider contract**. [PR #5](https://github.com/rua-den/playroom/pull/5) merged into `main` as `4d22e451e1881f09e476f0ab1173aae2cac72a50` (Issue #4 closed).
- RED baseline observed at [CI #38510735756](https://github.com/rua-den/playroom/actions/runs/38510735756): new unconditional JSON narrator-prompt assertion failed. That initial run also exposed a pre-existing race in the test that asserted released slots too soon.
- GREEN on exact PR SHA `3510ca348896c4ee065231631926453fbfd972e1`: [CI #38511020183](https://github.com/rua-den/playroom/actions/runs/38511020183) passed backend **279/279**, frontend **79 passed, 3 skipped**, typecheck, build and compileall.
- GREEN again on exact merge SHA `4d22e45`: [main CI #38511140177](https://github.com/rua-den/playroom/actions/runs/38511140177) passed both backend and frontend jobs, full test/typecheck/build/compile.
- Production change: narrator system prompt unconditionally asks production narrator profiles for one JSON `segments` object and exact selected speaker/version pairing; explicitly disallows fences and new player-agency actions. Native strict-schema capability stays **disabled** for Ollama Cloud, and no automatic paid retry is introduced.
- New deterministic integration tests: streaming Ollama OpenAI-compatible mock transport with UTF-8 SSE frames; JSON attribution/candidate/commit and exact-once idempotency; malformed JSON/prose/fences/unselected speaker/wrong version/kind mismatch/length/refusal/missing terminal; paid-only pre-dispatch and missing strict quality capability; usage cost ledger.
- Concurrent test reliability fix was test-only: wait bounded for the physical-slot finalizer rather than asserting immediately after provider's `finished` event.
- **NOT validated:** real Ollama Cloud API/schema adherence, persona agency in unconstrained model prose, browser/mobile E2E, account-specific pricing/cap, VPS Caddy or deployment. Do not conflate mocked B2 PASS with live-model acceptance.
- **Next unlocked planning target:** [Issue #6 — three-turn synthetic mobile/reconnect E2E](https://github.com/rua-den/playroom/issues/6) (B3). The owner-directed coding exception in AGENTS only covers Issue #4; follow normal coding-agent routing for Issue #6 unless the owner explicitly broadens it.


## B3 real Chromium gameplay — accepted on 2026-10-14

- **PASS for synthetic/browser scope**. [PR #7](https://github.com/rua-den/playroom/pull/7) merged at `baa0f1bc463a19c156a9a58aaff71b6df2dec678`; [PR #8](https://github.com/rua-den/playroom/pull/8) merged at `2652a453a037666b6020374dc1d0fc62f7afc8ec`. Issue #6 can be closed after confirming exact-merge CI. No production code or production deployment was changed by either PR.
- B3 deterministic **real Chromium browser** gate `backend/tests/browser_e2e.py` tests the built React/Vite SPA served on loopback FastAPI by `create_demo_app`, with a synthetic-only fake narrator and throwaway SQLite. It explicitly checks that the browser opens no non-loopback network URLs.
- Seven persisted turns through the actual UI, with `**action**`/dialogue segmentation, Vietnamese and astral Unicode, exact-once fake-provider calls, reload and same-job recovery after lost generate POST response.
- Confirmed pre-reservation 422 and conflicting 409 recovery, after-commit projection refresh failure and explicit retry of the **existing** candidate without creating another generation job, IME composition/Shift+Enter, and 360/390/430px viewport widths without horizontal overflow; mobile campaign select and context dialog are usable.
- Final seventh turn uses a seeded present Yuna NPC and deterministic structured fake narrator; Chromium renders `Yuna:` dialogue and persisted `output_segments` retain the exact selected character ID and profile version. Reload adds no provider attempts.
- Initial [Chromium run #38513580101](https://github.com/rua-den/playroom/actions/runs/38513580101) exposed an incorrect test selector for a deliberately hidden legacy campaign drawer; corrected to the accessible topbar campaign dropdown. [Green six-turn PR run #38513914075](https://github.com/rua-den/playroom/actions/runs/38513914075) preceded PR #7 merge. [Green seven-turn PR run #38514220581](https://github.com/rua-den/playroom/actions/runs/38514220581) preceded PR #8 merge.
- [Exact final merge-main run #38514327407](https://github.com/rua-den/playroom/actions/runs/38514327407) **PASS** backend `279 passed`, frontend `79 passed, 3 pre-existing skipped`, typecheck/build/compileall, and real browser synthetic seven-turn acceptance. This validates code HEAD `2652a453a037666b6020374dc1d0fc62f7afc8ec`.
- **Excluded / not tested:** actual handheld phone/keyboard/suspend-resume, real Ollama Cloud structured JSON adherence or semantic style/agency consistency, user-account paid cap and model cost, physical VPS/Caddy/TLS, and live story import. Browser viewport emulation is **not** a physical phone test.
- **Next:** [Issue #9 — owner-authorized live narrator + physical phone acceptance](https://github.com/rua-den/playroom/issues/9). No owner approval for paid model requests or production deployment has been supplied, so do not run live trials or change VPS based on this B3 acceptance. AGENTS direct coding fallback was scoped only to Issue #6; future coding defaults to Luna delegation.
