# Legacy owner-local acceptance follow-up — 18 October 2026

## Starting state

Fetched main `0b722e0` and read the [17 October checkpoint](2026-10-17-legacy-import.md). PR #34 already implemented Legacy import; PR #35 documented its exact CI. The unfinished 16 October worktree was preserved unchanged rather than merged over the newer implementation. Work is isolated in `D:\stu\worktrees\playroom-import-followup`, branch `feat/import-followup-20261018`.

Current chat routing requires Luna medium implementation and Sol review/independent verification. The [follow-up plan](../superpowers/plans/2026-10-18-legacy-acceptance-followup.md) preserves the released checkpoint bulk-approval and separate provider-data consent contract; it does not revive the abandoned per-item-only design.

## Changes and regression evidence

- `ee3aa9c`: Legacy importer guards file reads, preview/error results and import completion by source epoch/mount ownership; an already-authorized import is neither cancelled nor silently retried. Replacement sources cannot start a concurrent second import while it remains pending.
- `8a3a548`: review acknowledgements/provider consent reset for complete campaign/branch/checkpoint/source identity. A shared checkpoint ID no longer carries acknowledgements to another branch. Snapshot responses are identity-guarded.
- Structured review displays persona/NPC traits, roles/notes and scene fields, resolves persona and NPC IDs for presence/knowledge readers, and exposes allowlisted persisted source/resume/gap metadata from the owner-scoped archive. The full source archive is not returned through projection.
- `9a13fa4`: ID fields remain visible with name/ID labels; oversized review-gap text is explicitly truncation-marked instead of being falsely presented as absent. The complete original remains in the private source archive.
- `ba911ce`: a separate deferred-success preview regression proves file A's late preview cannot be adopted for file B; synthetic Legacy reports correctly contain zero transcript turns.
- `6c3233f`: synthetic browser failure diagnostics retain at most 100 request/state events, stale-route hit counts and click markers; no generation behavior or timeout was changed.

Initial deferred importer tests had **two actual baseline failures** before the guards: `keeps the latest file when an earlier file finishes reading later` and `does not notify the parent when an authorized import finishes after close`. The stale-preview error test passed on baseline; it is not claimed as RED evidence. Final focused importer tests **4 passed**. Independent review at `9a13fa4` found no remaining actionable correctness/security issue and ran frontend focused **16 passed**, legacy/ChatGPT backend **33 passed**, and raw diff checks. The subsequent change is test-only.

## Private local acceptance

The owner-selected local source passed the current parser. Parent then used the built React app with `playroom-live-local` assembly on loopback and an isolated temporary DB underneath the ignored owner data directory. The provider factory was replaced by a blocking guard and browser requests were restricted to that loopback origin. A fresh temporary owner was used; existing owner accounts/databases were not modified.

Actual file → preview → provisional import → review display → reload **PASS**:

- Stored source preserves the entire selected JSON object semantically, including original text; no byte-for-byte whitespace/layout claim.
- All expected canon/event/relationship memories remain pending, with source knowledge scopes/readers intact; scene/profile mappings and persona exclusion from NPC profiles match the source.
- Review displays source profiles/traits, resume metadata and gaps. Reload remains locked with every review/data-consent checkbox clear.
- Zero turns, revisions, generation jobs and provider attempts; no checkpoint approval, provider-data consent, trial grant or Send was performed.
- Zero provider dispatch/external browser requests. The temporary DB was removed and the original source hash remained unchanged. No source prose, screenshot, private DB or credentials were written into repository/fixtures/CI.

This is technical local-import/review acceptance, not owner confirmation that the canon is correct and not private-story live inference acceptance. Real owner approval and provider sharing remain deliberate owner actions.

## Verification status

Parent fresh checks: backend **355 passed / 1 expected Windows POSIX-only skip**; frontend **109 passed / 3 skipped**; typecheck, production build, compileall, locked dependency setup and raw diff check passed. The private loopback acceptance above passed.

Full synthetic Chromium **failed two parent follow-up runs** before either import scenario at `browser_e2e.py:261`, waiting for the stale-409 notice. Failure-only diagnostics showed four committed jobs, no alert, unchanged nonempty input, Send disabled and four fake provider calls. Between those failures the investigating agent reported five passing runs, including a temporary trace of the successful `preview 201 → generate 409 → by-key 404 → projection 200` path. That trace did not capture a failing run and does not establish a harness-only cause. This resembles the still-open #20 recovery gate but is not asserted to be the older lost-POST defect.

Parent then ran the exact locked browser command once with persistent trace instrumentation and once at final diagnostic commit `6c3233f`; **both passed both full scenarios**, including import/review/fake Send and real local assembly with fake override/reload. The root cause remains unresolved; no timeout increase or passing rerun is counted as a fix. The retained bounded diagnostics are for the next failure investigation, and #20 remains open. Import changes do not modify generation behavior.

No new PR has been merged for this checkpoint. Record final diagnosis, exact commit checks and PR/merged-main CI before release. Remaining order: #27 official ZIP/long/resumable source; unresolved #20 recovery cases; #9 authenticated live Gemma4, then separately authorized phone/VPS/Caddy deployment. No real provider, physical device or infrastructure work occurred here.
