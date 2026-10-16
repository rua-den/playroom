# Playroom import review gate — 16 October 2026

This checkpoint supersedes the missing-review-gate blocker in the earlier [16 October handoff](2026-10-16-codex-astra-transfer.md). It covers the selected ChatGPT JSON slice in [PR #28](https://github.com/rua-den/playroom/pull/28), not completion of [Issue #27](https://github.com/rua-den/playroom/issues/27).

## Starting state and implementation

- Fetched `main`: `2ceb4ace47eb17f1ad7f9b989917f740142d92c3`.
- Existing PR head: `ce081f1d90ea60a972dcb3e4dd72f256ed3bab5b`.
- Last implementation commit before this documentation: `9f37e27f89bb6be32b4ca89439a07951ffbaf8c6`.
- Worktree: `D:\stu\worktrees\playroom-pr28-review`; branch `feat/issue27-import-review-gate`. Existing dirty Issue #14 worktree was preserved. Latest main was merged without resetting or force-pushing prior work.
- The current chat's owner instructions required Luna medium for implementation. Coding was delegated accordingly; the orchestrator independently inspected the diff, ran verification, and obtained a separate Sol review. No remaining review findings at the implementation SHA above.

Import now creates a durable, owner-scoped review requirement. Import confirmation does not approve the playable checkpoint. The separate screen displays the actual persona, NPC profiles, scene/presence, approved memories and knowledge scopes, source ID, paired turns, omitted-message count and warnings. Failed snapshot loading blocks approval. Checkpoint changes reset acknowledgements; stale/unmounted requests and React StrictMode cannot unlock the wrong campaign or suppress a valid refresh.

Approval requires four exact boolean acknowledgements and the current owner/branch/checkpoint. Unknown fields, coercible strings/numbers, incomplete acknowledgements, another owner and stale checkpoints are rejected. The saved approved checkpoint remains the baseline for subsequent descendant turns.

The server checks approval inside the generation reservation transaction, again when recovering a queued job, and inside the transaction immediately before provider dispatch. Unreviewed Send creates no new jobs, provider attempts, branch guards or trial reservations. Jobs queued by older code cannot bypass review after migration/restart. Migrations backfill the review requirement; old source rows with unavailable omission counts explicitly show unknown, never zero. No public fork operation exists yet; the approved checkpoint is retained for the future archive/fork boundary.

Main files: `backend/playroom/chatgpt_import.py`, `generation.py`, `api/transfers.py`, `projections.py`, migrations `004`/`005`, `frontend/src/components/AppShell.tsx`, API contracts, and backend/frontend/Chromium regressions.

## Observed RED and GREEN evidence

- Actual backend RED against disposable baseline `8749715`: `uv run --locked --extra test pytest backend/tests/test_recovery_gate_red.py -q` failed with `assert 'candidate' == 'failed'`: a legacy unreviewed queued job reached the fake provider. This was fixed by the recovery and final dispatch checks.
- First independent Chromium run failed because its old mobile assertion expected Send immediately after import; the new review lock correctly hid it. A subsequent run reached approval but failed its new Send because the test retained another campaign's fixed NPC narrator. Restoring the generic synthetic narrator fixed that fixture contamination. These failures are recorded, not relabelled as initial green runs or as proof of Issue #20.
- Final independent backend command: `uv run --locked --extra test pytest backend/tests -q` — **320 passed in 55.31 seconds**; `python -m compileall -q backend/playroom` passed.
- Final independent frontend: `npm test` — **94 passed, 3 skipped**; `npm run typecheck` and `npm run build` passed.
- Final independent Chromium: `uv run --locked --with playwright==1.56.0 python backend/tests/browser_e2e.py` — **exit 0**. Covers seven-turn gameplay/reconnect plus selected JSON import, crafted pre-review Send rejection, reload lock, separate approval, post-approval fake Send and persisted approval.
- `git diff --check` passed. No remote inference, private story transmission, physical phone or deployment was performed.

Local results do not substitute for GitHub CI. Before merging, inspect the exact current [PR #28 checks](https://github.com/rua-den/playroom/pull/28/checks); after merging, require the verification workflow on that exact merged `main` SHA. The final PR description records the remote run URLs. Always fetch remote state before resuming.

## Remaining work

1. Keep #27 open: official ZIP handling, full long-history provenance/chunking/resume and an owner-provided sanitized real-export compatibility test remain. This slice accepts selected official JSON, not ZIP or a full app backup.
2. Implement the separate legacy story-bundle mode in #29 using synthetic structural fixtures. The private bundle is not a complete verbatim transcript; never fabricate missing history.
3. Diagnose #20's intermittent lost-POST Chromium race separately. Passing this run does not close that issue.
4. #9 remains incomplete: live authenticated whole-app model E2E, long quality trial, actual phone and production deployment are unverified. Existing financial/data/device/VPS approval boundaries remain in force.
