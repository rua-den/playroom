# Playroom reconnect race checkpoint — 16 October 2026

## Verified starting state

[PR #28](https://github.com/rua-den/playroom/pull/28) merged as `6b188944e532be8b6f27883f35e60688d23bc2da`. Its exact PR head `c2deac423f6af2b50d5dfc5046ba949e1cec19f0` passed [CI #38848809382](https://github.com/rua-den/playroom/actions/runs/38848809382) on attempt 1. The exact merged-main [CI #38848924812](https://github.com/rua-den/playroom/actions/runs/38848924812) passed backend/frontend but **failed browser attempt 1** at `browser_e2e.py:205`, waiting for the stale-409 notice. This is a recorded failure; do not describe that merge SHA as clean CI PASS. The failure occurred before the import scenario.

The owner asked to continue the latest handoff. Current chat instructions require Luna medium for implementation and separate orchestrator review/verification. Existing dirty work in the old Issue #14 worktree remains preserved. Work continues in `D:\stu\worktrees\playroom-pr28-review`, branch `fix/issue20-reconnect-race`.

## Diagnosis and regression evidence

The browser's fourth-turn scenario waited for the transcript count but not composer completion. Parent projection could show the new turn while the old commit continuation still awaited its refresh. A new action typed in that interval could be erased by the old `setAction("")`; the fifth click then submitted no action, so the intercepted 409 and its notice never occurred.

The production correction must preserve edits while commit/recovery is pending, including identical text typed again. It must distinguish captured request ownership from the current scope, prevent stale recovery/poll/commit responses from changing another operation's UI, and retain already-authorized jobs and their durable recovery keys. Parent projection refresh also needs a selection/request guard. Switching campaigns must not silently cancel an upstream job.

- `095ee7f`: initial operation/scope guards, edit revision tracking, parent projection guard and failure-only synthetic diagnostics. This was not accepted as complete merely because one Chromium run passed.
- `6778d42`: independent deterministic tests in `frontend/src/components/GenerationComposer.race.test.tsx`.
- Actual independently repeated RED: `npm test -- --run src/components/GenerationComposer.race.test.tsx` — **2 passed, 1 failed**. `keeps a draft edited while recovery is waiting for the old job response` expected `User draft` after a deferred candidate commit, received an empty action. The late commit was recapturing the newer edit revision instead of carrying the original recovery owner through the pipeline.

## Final candidate and verification

The original merged-main workflow later passed on **attempt 2 at the same `6b18894` SHA**. The first failure remains recorded above. Latest upstream documentation was merged from `c0899accfc4fad78844dc730157f26c02d81cbd3` into this branch; its execution order is #20, #30 owner-local runner, #29 legacy bundle, remaining #27 ZIP/long import, then #9 live/device/deployment gates.

The correction carries the original operation epoch, storage scope, submitted action and edit revision through settings/preview/generate, recovery, polling and candidate commit. Durable updates check the captured receipt identity; stale responses do not adopt another scope's UI. Poll locks are epoch-owned, unmount immediately disables UI adoption, and committed turns clear the input only if the user has not edited it. AppShell rejects projection refreshes for an obsolete selection/request. Already-authorized server work is retained for recovery rather than silently cancelled.

Independent regressions cover identical-action edits during commit, edits before a delayed recovery GET resolves, campaign switching during recovery, edits between running-job polls, and a fresh queued Send followed by identical text retyping. The fifth case asserts exactly one generation request and one commit. `d789737` fixes only test timer typings after the full test suite passed but TypeScript rejected the mock return types.

At `d789737`, independently run checks passed: frontend **101 passed / 3 skipped**, typecheck, production build, compileall and two complete Chromium runs (seven committed turns, reconnect/409/422/refresh/IME/mobile and selected JSON import/review). Backend full-suite verification and a final obsolete-timer regression are still in progress; these are checkpoint results, not final release evidence.

Final review identified a separate timer ownership window: an old interval callback could read the new epoch after a scope render but before cleanup and then refresh its old identity. `cdd57ca` captures the epoch at interval installation; `ce51d34` also validates identity scope before installing polling, so a transitional render cannot install old state under the new epoch.

The first retained-callback test (`83218a0`) was invalid: its route substring also counted the ordinary events request, and its timer spy captured Testing Library intervals. That was a **test false positive, not accepted production RED evidence**. `9020052` fixes exact route handling, captures only the 1200ms product callback, and compares durable identities after normal recovery. Corrected test against isolated baseline `d789737`: **RED**, expected one old-job request, received three after the obsolete callback. Final `ce51d34` production plus corrected test: **GREEN, all six race tests**. The temporary baseline worktree was removed; the main worktree production file remained clean.

Full backend suite: **320 passed in 70.85 seconds**. Locked `uv sync --locked --extra test` and `npm ci` succeeded. No backend production code changes are included in this follow-up.

Final independent code review at `ce51d34` + `9020052`: no remaining production blockers found; reviewer separately ran all six race tests and typecheck. Parent full frontend verification after locked reinstall: **102 passed / 3 skipped**, typecheck and build passed. The transient new-epoch/old-state poll setup guard is inspected in review; the sixth regression exercises the retained obsolete callback directly.

## Release status

Local implementation, independent review and verification are complete; remote exact-SHA CI is the next release gate. Final Chromium at `ce51d34` + `9020052` passed the entire seven-turn and selected JSON import/review script; two earlier complete runs at `d789737` also passed. `git diff --check` and compileall passed. No follow-up PR has been merged yet. Issue #20 stays open: this fixes demonstrated draft/ownership races and adds diagnostics, while the older lost-POST first-attempt timeout has not been independently reproduced as the same defect. Record exact PR and merged-main CI URLs after release.

No real model calls, private story transmission, phone operation or VPS/Caddy changes are part of this checkpoint. ZIP/long import (#27), private legacy bundle (#29), and full live/phone/deployment acceptance (#9) remain separate unfinished work.
