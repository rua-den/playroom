# Roleplay Chat with Stable Character Attribution

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to execute this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Playroom feel like a plain roleplay chat: player text inside `**...**` is action/thought narration, ordinary text is player dialogue, and generated dialogue is stored with stable character IDs so characters do not drift between turns.

**Architecture:** Keep the current durable generation lifecycle and legacy `action_text`/`narrative_text` fields. Parse player input into ordered typed segments while retaining its exact raw text. Let the context director select only character profile IDs and versions from the checkpoint snapshot, informed by current scene presence and input; require narrator output as validated ordered segments with profile-version IDs. Persist those segments additively on each turn/revision, project them to the client, and render them in the transcript. Old turns with no structured segments remain unattributed legacy text. Keep streaming, cancellation, candidate approval, and the no-real-model-in-tests boundary.

**Tech Stack:** Python, FastAPI, SQLite, JSON Schema, React, TypeScript, Vitest, pytest.

## Scope and invariants

- One freeform composer; remove quick-insert category buttons and extra always-visible authoring controls. Show a short `**...**` hint.
- `**...**` spans parse as player action/thought. Plain spans parse as player dialogue. Preserve original `action_text` verbatim. Malformed/unclosed delimiters remain plain dialogue rather than losing text.
- The director may select only characters from pinned `profile_versions` in the current checkpoint. Keep their stable character key/ID and exact profile version; scene presence and knowledge scope remain distinct.
- The narrator emits ordered text segments with `kind`, text, and optional character ID/profile-version ID. Dialogue owned by an NPC must name a selected character. Neutral narration may be unattributed. Never accept invented IDs or silently guess speakers.
- Persist structured input and output segments alongside legacy fields. Existing data is not rewritten or backfilled with guessed attribution.
- Preserve generation status/CAS, usage ledger, streaming, cancellation, edit-draft, and candidate commit semantics. Invalid structured output cannot be committed or billed as a successful result.
- Automated tests use fake providers only.

## Task 1: Define and test roleplay segment parsing and validation

**Files:** `backend/playroom/roleplay_segments.py` (new), `backend/tests/test_roleplay_segments.py` (new).

- [ ] Add RED tests for plain dialogue, one and multiple `**...**` action spans, mixed ordered segments, multiline text, empty spans, and unclosed delimiters.
- [ ] Add RED tests for validation of narrator segments: known selected character IDs and versions accepted; invented, unselected, mismatched, missing NPC dialogue attribution, malformed kinds, and blank output rejected.
- [ ] Implement a small pure parser/validator. Keep original input separately; do not normalize or alter legacy action text.
- [ ] Run the focused tests and confirm RED before implementation, then GREEN.

## Task 2: Add checkpoint-scoped character selection and structured generation output

**Files:** `backend/playroom/context.py`, `backend/playroom/context_director.py`, `backend/playroom/generation.py`, relevant `backend/tests/test_generation*.py` and selection/context tests.

- [ ] Add fake-provider RED tests proving the director wire contains stable character IDs, exact profile-version IDs, and current scene presence; accepts only checkpoint characters; and exposes its selected cast to narration.
- [ ] Extend the director schema and validator with bounded selected character IDs/reasons while retaining existing memory and scene selection fields.
- [ ] Add a structured narrator schema and validate output against selected cast and pinned profile versions before exposing a committable candidate.
- [ ] Preserve text streaming by parsing/assembling structured output into user-visible draft text without leaking JSON/schema markup. Keep existing retry/cancel/idempotency behavior.
- [ ] Verify usage accounting is tied to actual provider output and rejected/invalid results never become committable or mutate campaign context.

## Task 3: Persist additive segment data and project it

**Files:** `backend/playroom/db.py`, new `backend/playroom/migrations/002_roleplay_segments.sql` only if supported by the existing migration approach, `backend/playroom/timeline.py`, `backend/playroom/projections.py`, context builders, and relevant storage/projection tests.

- [ ] Add migration coverage from an existing 001-only database and confirm legacy rows remain readable and unchanged.
- [ ] Store parsed player input segments on `turns` and generated segments on `turn_revisions` using additive nullable/defaulted JSON columns (or an equivalent additive table if that better fits established schema conventions).
- [ ] Pass segment payloads through the existing transaction that commits a generation candidate; keep raw input and narrative fields intact.
- [ ] Return segments in transcript projections. For missing legacy segments, return an empty/null compatibility value without inferring speaker attribution.
- [ ] Include structured segments in recent context so later turns can preserve who said what.

## Task 4: Simplify composer and render attributed dialogue

**Files:** `frontend/src/components/GenerationComposer.tsx`, `frontend/src/components/GenerationComposer.test.tsx`, `frontend/src/api/types.ts`, `frontend/src/components/AppShell.tsx`, `frontend/src/components/AppShell.test.tsx`, `frontend/src/styles.css`.

- [ ] Add RED tests that the composer has one plain textarea, no starter/action-category buttons, and explains `**...**` syntax.
- [ ] Add RED tests that structured transcript renders attributed speaker labels while legacy transcript still renders exactly as before.
- [ ] Implement the minimal composer and readable chat bubbles/role labels; keep cancel/retry/commit and streaming controls available only when relevant.
- [ ] Check narrow viewport behavior and keep canon/profile editing outside the primary chat surface.

## Task 5: Review and verification

- [ ] Sol independently reviews the full diff for identity/version correctness, legacy compatibility, transaction boundaries, and accidental scope expansion.
- [ ] Run focused backend tests, full backend tests, focused frontend tests, frontend typecheck/build, and `rtk git diff --check`.
- [ ] Confirm existing persisted demo history was not rewritten, no paid provider/model was called, no deploy/push occurred, and no unrelated user changes were discarded.
- [ ] Report precise RED and GREEN outputs and list remaining limitations (including that narrative quality needs a manual real-provider trial after review/configuration).
