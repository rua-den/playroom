# Library Trash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or executing-plans. All implementation and tests are delegated to gpt-5.6-luna medium under current human routing.

**Goal:** Add persistent, reversible story deletion to the real Library, matching the reviewed theme preview's confirmation and undo flow.

**Architecture:** Add nullable campaign `deleted_at` metadata without changing immutable story records. Default catalog and ordinary campaign/branch access exclude trashed campaigns; explicit owner-scoped trash listing and restore operate on metadata. React Library provides a confirmation modal, persistent Trash view, restore actions and an undo toast.

**Tech Stack:** Existing FastAPI, SQLite migrations, React/TypeScript, pytest, Vitest and locked Chromium gates.

**Spec:** This document's behavior and contracts below are the bounded design requested by the owner, who explicitly confirmed both real app and theme preview on 20 October 2026. Preview is already implemented separately.

## Global Constraints

- Base: `ed0757bec4354f1040f2d46e786157db1285c98c`, branch `feat/library-trash-20261020` in the existing clean worktree.
- No permanent erasure; no immutable trigger bypass; no history/profile/scene/source deletion.
- No real provider calls, private story export, credential changes, or deletion of owner stories during testing.
- Prefix shell commands with `rtk`. All test data must be synthetic.
- Preserve existing archive behavior; trash uses its own nullable metadata.
- Use existing Modal and Toast components. Do not apply an unconfirmed site-wide theme in this feature.
- Root reviews the diff, independently verifies, and requires exact PR/main CI before a release claim.

## Contracts

- `GET /api/campaigns` returns only nontrashed summaries.
- `GET /api/campaigns?trashed=true` returns only the authenticated owner's trashed summaries.
- Summary retains existing fields and adds `deleted_at: string | null` (frontend may declare optional for old fixtures).
- `DELETE /api/campaigns/{campaign_id}` atomically trashes the owned campaign and returns its updated summary. Repeated deletion is idempotent.
- `POST /api/campaigns/{campaign_id}/restore` restores the owned campaign and returns its updated summary; repeated restore is idempotent.
- Normal campaign detail and branch/story operations reject a trashed campaign. A stale preview must not enable another provider dispatch.
- Historical terminal-job status/content/events remain owner-readable for recovery; trash is reversible, not an access-revocation or erasure operation. Normal story projections and campaign job indexes reject trash. New or replayed generation must not dispatch or reserve provider work for trash.
- Trash rejects the operation if any branch of the campaign has a generation guard or outstanding nonterminal job, including a candidate awaiting commit. No automatic cancellation or loss of pending work.
- Metadata mutation and generation admission serialize through existing SQLite transactions. Restore preserves the archive flag and all story content/checkpoints.

## Task 1: Persistent owner-scoped trash API

**Files:** `backend/playroom/db.py`, additive migration if useful, `campaigns.py`, `api/campaigns.py`, `timeline.py`; synthetic tests in `backend/tests/test_campaign_trash.py` and existing test files only if required by intentionally changed contracts.

**Produces:** API contracts above. Frontend calls do not require a branch/checkpoint because this is campaign-wide catalog metadata, not a story revision.

- [x] Write failing tests for durable trash/list filtering, owner/auth/CSRF isolation, all-branch active-job rejection, no dispatch from stale previews, restart/restore identity and immutable-record preservation.
- [x] Run focused tests and record the expected missing-feature failure.
- [x] Add nullable metadata idempotently to existing databases. Implement owner-scoped metadata operations inside `BEGIN IMMEDIATE`; check active jobs/guards across every branch before updating.
- [x] Exclude trashed campaigns from ordinary detail and shared branch lookup. Audit generation admission/commit and alternate profile/memory/transfer paths for bypasses.
- [x] Run focused tests plus existing storage/auth/generation mutation suites. Report exact evidence, modified files and unresolved concerns.

## Task 2: Library confirmation, Trash and restore

**Files:** `frontend/src/components/CampaignLibrary.tsx` (focused new component if warranted), `AppShell.tsx`, `Toast.tsx`, `api/client.ts`, `api/types.ts`, `styles.css`, relevant Vitest tests, and synthetic browser coverage in `backend/tests/browser_e2e.py` or a dedicated existing-compatible browser function.

**Consumes:** Task 1's exact API contracts. **Produces:** A usable Library flow with reliable state and confirmation.

- [x] Write failing interaction tests for cancel (no request), confirmed deletion (only selected item removed), failure preservation, selected-story cleanup, last-item empty state, persistent Trash restore and toast undo. Guard duplicate requests and stale owner/selection responses.
- [x] Run focused tests and record the expected missing-feature failure.
- [x] Add labeled per-story `Xoá` actions and confirmation copy naming the story: `Truyện sẽ được chuyển vào Thùng rác. Bạn có thể khôi phục lại.` Use `Huỷ` / `Xoá truyện`; show progress and useful errors.
- [x] Extend toast success with an optional accessible action while preserving existing timeout/pause/dismiss semantics. Provide a permanent Trash view so restore never depends on catching a timer.
- [x] On deletion of the current story, return to Library, clear its remembered selection and invalidate pending projection requests; deleting another story preserves current selection/draft. Restore must not silently switch stories or call AI.
- [x] Add synthetic real-browser checks for confirm/cancel/undo/trash/reload/restore at desktop and mobile widths. Never operate on `.playroom-live` for these tests.
- [x] Run focused and complete frontend tests, typecheck/build, and report modified files and exact evidence.

## Root integration and release

- [x] Review all changes and request an independent read-only review; resolve blocking findings through Luna.
- [x] Independently run full backend/frontend suites, typecheck/build, compilation, and both locked Chromium gates against the combined source.
- [x] Update local usage and handoff documentation with actual behavior and evidence.
- [ ] Create/attach a PR, obtain green exact-head CI, merge only after review/checks and verify merged-main CI.
- [ ] Before refreshing the local runner, verify no nonterminal owner jobs; back up privately and preserve owner database/keys. Start verified code at localhost and confirm health/assets without deleting owner stories or sending their context.

## Execution record

| Check | Result |
|---|---|
| Task 1 / Task 2 shared interface | Exact list/trash/restore routes and summary shape agreed before dispatch; files are disjoint except the shared written contract. |
| Task 1 internal consistency | Trash changes catalog metadata only; restore intentionally bypasses normal deleted-story lookup while retaining owner validation. |
| Task 2 internal consistency | Confirmation and undo use the same persistent API; a durable Trash view remains after toast expiry. |
| Baseline backend | Root: 447 passed, 1 Windows platform skip in 89.17 seconds. |
| Baseline frontend | Root: 184 passed, 3 existing skips. Existing React act warnings observed before this feature. |
| Worktree | Existing clean feature worktree reused; no new checkout or primary-data copy required. |

Task 1 and Task 2 implementation and review are complete. Review fixes covered generation replay, terminal-job mutations, the cancellation event transaction gap, all recoverable job statuses, the bounded guard JOIN, async frontend state, undo failures and pending actions. Existing modal isolation and the empty-library illustration were preserved during the component extraction.

Final independent root verification: 461 backend passed / one Windows platform skip; 196 frontend passed / three existing skips; TypeScript checking and production build passed; compilation and diff checks passed. All three locked Chromium flows passed: existing synthetic chat/import/review/toast, new desktop/mobile trash, and real local assembly with a fake provider. The trash flow causes zero provider calls. Whole-branch review accepted the production changes. Remote CI and the owner-local runner update remain the release steps.

Preflight review identified additional projection ownership helpers and recoverable interrupted jobs. Backend implementation must cover those helpers and block queued, running, cancelling, interrupted and candidate jobs across every campaign branch. Restore and repeat trash use an owner-scoped metadata lookup including trash; repeated no-op requests preserve timestamps.
