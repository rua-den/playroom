# Legacy acceptance follow-up implementation plan

> **For agentic workers:** Use subagent-driven-development. The current user requires Luna medium for implementation and Sol review/independent verification. All shell commands use `rtk`; commits must be new, with explicitly owned paths.

**Goal:** Complete the next owner-local acceptance checkpoint from the 17 October handoff and fix demonstrated source/review ownership and visibility defects.

**Architecture:** Preserve merged PR #34's parser, source archive, explicit checkpoint review, imported-memory promotion and provider-data consent policy. Add asynchronous ownership guards to the existing importer and bind review acknowledgements to the complete displayed snapshot identity. Show reviewable structured source fields and knowledge readers instead of relying on description-only labels.

**Tech stack:** Existing React/TypeScript, FastAPI/SQLite, Vitest/pytest and Playwright Chromium. No new dependency or provider request.

**Spec:** `docs/handoff/2026-10-17-legacy-import.md`; Issue #29. Verified starting main: `0b722e0`. PR #34 and #35 already supersede the dirty unfinished worktree from 16 October; that worktree remains untouched.

## Rulings and boundaries

- Ruling: keep released legacy checkpoint bulk approval plus separate provider-data consent — this is the current merged contract, superseding the abandoned per-item-only draft — changing the policy here would require different acceptance and is outside this fix.
- Ruling: source selection, campaign, branch, checkpoint and source kind determine UI ownership — a shared checkpoint ID alone cannot preserve acknowledgements for another branch/source.
- Ruling: private acceptance uses an isolated temporary DB and local loopback UI with all provider dispatch blocked. Do not approve its checkpoint, grant provider-data consent, submit a story action or alter the owner's existing DB. The source stays ignored and unchanged; no private story, screenshot or database enters Git/CI.
- Ruling: metadata displayed to the authenticated owner may include original gaps/resume/provenance already held in their private archive; errors and public tests remain synthetic/redacted. UI renders it as escaped text.

## Task 1 — source operation ownership

Owner: Luna; `LegacyImport.tsx` and new `LegacyImport.test.tsx` only.

- [x] Reproduce delayed file A read replacing file B and delayed preview/error adopting after source replacement; preserve exact deferred RED evidence.
- [x] Guard file read, preview and import response adoption by source revision and mount ownership; reset confirmation for replacement, preserve the identity of an already-authorized server import, and never silently retry or cancel it.
- [x] Test unmount/close during import, stale errors and usable current source. Run focused/full frontend, typecheck/build and commit owned files.

## Task 2 — truthful snapshot review

Owner: separate Luna; `AppShell.tsx`/tests, optional `api/types.ts`, and narrowly scoped `chatgpt_import.py::import_review` metadata/tests.

- [x] RED regression: changing branch/source while checkpoint ID is shared must clear all acknowledgements/provider consent and disable approval until the new snapshot loads.
- [x] Bind ready/loading/reset state to the complete snapshot identity and reject stale asynchronous responses.
- [x] Render structured persona/NPC voice/traits/notes and scene fields. Label persona/NPC IDs in presence, entities and `known_by` proposals while retaining IDs for inspection. Do not add the persona to NPC cast or alter scope semantics.
- [x] If needed, expose bounded owner-scoped legacy resume/gap/provenance metadata from the already private archive for persistent review after reload. Preserve JSON import compatibility and avoid returning the entire archive.
- [x] Run focused frontend/backend regressions and typecheck; commit only owned paths. Sol reviews spec compliance and final diff.

## Task 3 — independent acceptance and release

Owner: parent/Sol reviewer; no implementation writes by parent.

- [x] Fetch latest main and read latest handoff/PR #34. Pure validation of the owner-selected local bundle passed with zero transcript turns and review required; only booleans were printed.
- [x] Parent runs the actual local file through authenticated loopback import into a temporary DB, inspects pending memory/scene/profile/source preservation and reload lock, and confirms zero model dispatch and no approval. Print only controlled pass/fail labels; clean the temporary data.
- [x] Independently run locked sync, backend/frontend suites, compileall, typecheck/build, synthetic Chromium and raw full-range whitespace checks. No private source in automated regression fixtures.
- [x] Push feature PR, attach it, require exact PR-head CI, merge at expected head and verify exact merged-main CI. PR #36 head `b2613f0` CI `39119446749` and merge `1a726d0` CI `39119578290` both passed attempt 1. Local first failures remain recorded separately; #20 stays open. Keep old worktrees and the primary checkout's untracked data intact.
- [x] Update handoff/README with exact evidence, remaining owner approval/live-model limits and next #27 ZIP/long-source checkpoint. Do not claim #27/#9 complete.

## Self-review

These changes repair the existing import/review flow rather than replace released architecture. Private file validation is not permission to transmit private context to a model. The follow-up remains bounded to demonstrated races and fields necessary to perform the documented review.
