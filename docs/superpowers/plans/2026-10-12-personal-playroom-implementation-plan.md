# Personal Playroom Mobile Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Follow the user's model routing: implementation must be delegated to `gpt-5.6-luna` with `medium` reasoning; the orchestrator reviews the diff and runs verification. Do not substitute an unsupported model silently.

**Goal:** Build a private mobile-first roleplay web app accessible anywhere, with inspectable context and branch-correct memory for long Vietnamese stories.

**Architecture:** A hosted Python API owns persistent SQLite, transcript revisions, memory and context composition behind owner authentication and HTTPS. A responsive browser frontend displays the story and memory controls; an isolated provider adapter streams narrative responses and proposes memory updates. Context snapshots retain provenance, and reconnect retrieves existing jobs instead of sending another AI request.

**Tech Stack:** React, TypeScript, Vite/PWA manifest; Python 3.12+, FastAPI, Uvicorn, Pydantic, sqlite3; existing Caddy, separate systemd service and persistent shared directory on the user's VPS; verify documented Oracle ARM64 before packaging; pytest, frontend interaction tests and mobile browser checks.

**Spec:** [Personal Playroom design](../specs/2026-10-12-personal-playroom-design.md).

## Global Constraints

- Mobile first, accessible anywhere via private HTTPS link; local development at `127.0.0.1`, production UI/API under the same origin with owner login.
- One production app instance/worker; SQLite uses persistent disk, not ephemeral serverless storage. Player PC uptime is not required.
- The user already owns a VPS and explicitly confirms Caddy is the current proxy. Wedding's Nginx/Certbot documentation is historical and cannot override that correction. Verify current OS/architecture/resources, systemd/Python, Caddy version/config/storage, workloads, ports and actual domain before deployment. Exact RAM/domain/Docker availability is not inferred from template values.
- Reuse the existing Caddy instance and add a separate Playroom Uvicorn/systemd service; do not install a second proxy or replace wedding's process manager. Keep app root, shared state, service identity, upstream and credentials separate. Build/package dependencies for the audited Linux ARM64/Python runtime when ARM64 is confirmed.
- No public registration; all story/context/config/stream/export endpoints require the owner session. Browser disconnect does not automatically cancel a generation job.
- Repository: `rua-den/playroom`, created by the user; current local checkout `D:\stu\repo\playroom`. All implementation file paths are relative to its root.
- Python 3.12+; Node 22.12+ on branch 22 or a later version supported by the locked Vite release.
- Input cap defaults to 12.000 tokens; output reservation 4.000; wrapper reservation 512. Effective limits must respect model config.
- Suggest memory review when required/selected input reaches 75% of its effective cap or a scene ends; keep the most recent committed turn verbatim. Do not wait for a fixed five-turn cadence.
- Maximum two provider jobs concurrently across narrative/consolidation; one narrative generation per branch; default per-attempt overall timeout 300 seconds. Persist an attempt before dispatch, disable automatic provider retries, and never replay ambiguous in-flight work after restart.
- Never silently truncate required canon/current action or use unapproved memory as fact.
- All stored/retrieved context is scoped to campaign, branch ancestry, selected revisions and effective turn.
- No provider secrets in frontend reads, exports, context snapshots or logs.
- No real paid calls in automated tests; fake provider is the default test dependency.
- All writes/refactors to implementation code use the user-required Luna coding agent. If dispatch is unavailable, stop implementation and report the limitation.
- New dependencies are locked at project creation; no floating `latest` in the delivered lockfiles.

## Execution status

This repository contains the reviewed design, plan, review report and reference analysis. Application implementation has not started. Execute against this repo after reading its AGENTS.md; the earlier APK-analysis workspace is reference material, not the application checkout. Provider/model selection is a defined Task 3 configuration step, not assumed from the existing chat account.

Required coding model `gpt-5.6-luna` is not present in the currently advertised spawn-model list. This does not block document review or design, but dispatch availability must be confirmed when implementation is requested. If unavailable, report the routing blocker and do not write implementation code or silently use another model.

## Delivery checkpoints

| Checkpoint | Tasks | Evidence |
|---|---|---|
| Context works without paid AI | 1–2 | 120-turn fixture with approved summary coverage; relevant source IDs and budget checks |
| First playable phone link | 3–4 plus essential deployment steps of 8 | Owner login, manual canon/scene/summary, real provider trial and reconnect; no claim of finished MVP |
| Long-play MVP | 5–7 plus remaining release/backup automation in 8 | Reviewed consolidation, exact fork state, long import, restore and user quality trial |

Task 8 essential staging steps (live inventory, isolated app root/service, private Caddy site, auth/HTTPS/persistence/reconnect checks) can run after Task 4. Advanced transfer tests, release automation and final acceptance wait for Tasks 5–7. This gives the user a useful phone trial before investing in all branch/import controls.

## Implementation file map

| Path | Responsibility |
|---|---|
| `backend/playroom/app.py` | App wiring, session/origin/host checks, API mount, static frontend |
| `backend/playroom/auth.py`, `api/auth.py` | Owner setup, password hashing, login/session/logout and rate limiting |
| `backend/playroom/settings.py` | Server config, model limits, job limits and masked provider settings |
| `backend/playroom/db.py`, `migrations/001_initial.sql` | Connections, transactions, migrations |
| `backend/playroom/domain.py` | Validated records and error contracts |
| `backend/playroom/campaigns.py`, `api/campaigns.py` | World, cast, persona and campaign operations |
| `backend/playroom/timeline.py` | Turns, revisions, branch ancestry and fork |
| `backend/playroom/memory.py`, `api/memory.py` | Memory versions, approval, conflict presentation |
| `backend/playroom/context.py`, `token_budget.py`, `api/context.py` | Selection, budget and immutable previews |
| `backend/playroom/providers/base.py`, `fake.py`, `http_chat.py` | Provider contract, deterministic fake, configured HTTP adapter |
| `backend/playroom/generation.py`, `api/generation.py` | Idempotent generation, stream persistence, commit and cancel |
| `backend/playroom/consolidation.py` | Durable proposal/summarization jobs |
| `backend/playroom/transfers.py`, `api/transfers.py` | Backup, export/import and transcript preview |
| `frontend/src/features/campaigns/` | Campaign creation, cast/persona editing |
| `frontend/src/features/story/` | Reader, composer, response candidates and branching |
| `frontend/src/features/memory/` | Scene, canon, memory proposals and context viewer |
| `frontend/src/features/settings/` | Provider/model config with masked key |
| `frontend/src/features/auth/` | Owner login, session expiry and logout |
| `frontend/public/manifest.webmanifest`, `icons/` | Mobile home-screen identity and standalone display |
| `frontend/src/api/` | Typed client contracts from the API schema |
| `frontend/package.json`, `backend/pyproject.toml`, runtime/dependency lockfiles | Reproducible dev/build/test dependencies |
| `backend/tests/`, `frontend/src/**/__tests__/` | Data/context regressions and user interaction tests |
| `fixtures/context-campaign.json`, `fixtures/context-expectations.json` | 120-turn replay fixture and expected context source IDs |
| `scripts/start.ps1`, `README.md`, `.gitignore` | One-command local startup and operating instructions |
| `deploy/playroom.service`, `deploy/playroom.caddyfile`, `deploy/release.sh`, `deploy/README.md` | Compatible service/release, existing Caddy site, separate shared data and restore |
| `.github/workflows/ci.yml`, `.github/workflows/deploy-production.yml` | Build/quality gates and deliberately enabled release deployment |

Keep each module focused; API handlers call domain services rather than implementing memory selection inside routes. Do not add the APK bundle or third-party Whif source to the future repository.

## Shared records and contracts

- IDs are UUID strings; turn sequence is an integer local to the logical branch timeline.
- `Turn` is one player-action/narrative-response pair; response candidates are revisions of that pair. Job drafts retain the action/partial output before commit. A fixture of 120 turns therefore has 120 pairs, not 120 individual chat bubbles.
- `StateCursor` contains committed turn/revision IDs and a monotonic branch state version. Every effective mutation creates an immutable `StateCheckpoint` enumerating selected revision/profile/memory/scene/summary version IDs.
- `BranchHead` contains campaign ID, branch ID, committed turn/revision head, state version and checkpoint ID. Readers consume that exact checkpoint, not the latest mutable values.
- `MemoryVersion` contains memory ID/version, kind, text, entity IDs, origin, approval state, source turn/revision IDs, branch and effective StateCursor. Typed facts can add subject ID, predicate, value/object ID and supersedes ID; these define single-valued-slot conflicts.
- `SummaryVersion` additionally contains the exact ordered source revision IDs for its covered interval.
- `ContextPreview` contains preview ID, expected branch head/state version, prompt messages, selected source IDs, omission reasons, token-count mode, input estimate/count, model config hash and payload hash.
- `GenerationRequest` contains preview ID, user action and idempotency key. Action must match the preview payload.
- `GenerationEvent` is one of `started`, `delta`, `completed`, `cancelled`, `failed`, `interrupted`; it includes job ID and monotonic event offset. `completed` carries candidate revision ID and actual usage when supplied by provider.
- `GenerationJob` records owner/branch/operation, idempotency key, payload hash, expected state version, attempt state and partial content. Lookup by idempotency key is authenticated; reusing a key with another payload is 409.
- `MemoryProposal` contains proposed changes, sources and conflicts; it cannot mutate approved memory before approval.
- HTTP failures: validation 422; unknown resource 404; stale preview/concurrent generation 409; oversized required context 422 with block sizes; provider/config failures have a stable app error code and retain player drafts.

## Task 1: Campaign storage and explicit memory

**Files:** `db.py`, `domain.py`, `migrations/001_initial.sql`, `campaigns.py`, `timeline.py`, `memory.py`, `api/campaigns.py`, `api/memory.py`, `auth.py`, `api/auth.py`, `app.py`, project dependency files; `backend/tests/test_campaign_storage.py`, `test_memory_versions.py`, `test_auth.py`.

**Consumes:** no prior app code.

**Produces:** campaign/profile CRUD, `get_branch_head`, `get_effective_profile`, `list_effective_memory`, `append_memory_version`. All readers take campaign, branch and effective position. The initial branch is created with the campaign.

Also produce `create_state_checkpoint` and `load_state_checkpoint`; imported transcript initially has a single reviewed playable checkpoint, while app exports can carry exact historical checkpoints.

- [x] Establish the repository checkout, copy reviewed docs and record required model routing in AGENTS.md.
- [ ] Verify clean/current repository state, applicable instructions, coding-model dispatch and runtime paths before scaffolding.
- [ ] Add owner/session schema, an administrative owner-creation command, Argon2id password hashing and server-managed sessions. Production cookies require HttpOnly, Secure and SameSite; no public owner registration route.
- [ ] Write auth regressions: absent/revoked sessions cannot read story/context/export or start a stream; wrong passwords create no session; repeated failures hit a rate limit; cross-origin mutation is rejected. A stream already open closes within one 15-second session-check interval after revoke; the generation job remains private and may complete. Apply the guard to every feature router and test its endpoint inventory.
- [ ] Define schema for campaigns, character/profile versions, branches, turns, turn revisions, selected revisions, memory versions, scene versions, summaries, state checkpoints, context runs and jobs. Add FK constraints, uniqueness for owner/branch/operation/idempotency key, and migration version. Every effective state mutation must check expected state version and create a new checkpoint atomically.
- [ ] Write regressions: two campaigns with the same character name cannot see each other's memory; pending memory is absent from approved results; a profile edit affects new requests but leaves an earlier profile version unchanged.
- [ ] Add single-valued-slot conflict and ambiguous-alias tests. Two different values for the same effective slot require review/supersession; two NPC IDs sharing a normalized alias must never be merged automatically. Free-text semantic detection is advisory, not a guaranteed validator.
- [ ] Run the focused tests and confirm failure due to missing behavior; implement minimal persistence and domain validation.
- [ ] Implement profile/canon/scene editing and memory approval/rejection with revision history. AI origin cannot directly create approved records.
- [ ] Run focused tests against an on-disk temporary DB, close/reopen it, and verify campaign/profile/memory state persists.
- [ ] Orchestrator reviews schema/query scoping and runs `rtk proxy python -m pytest backend/tests/test_campaign_storage.py backend/tests/test_memory_versions.py backend/tests/test_auth.py -q`, verifies no default password or raw session token appears in DB/log output, then commits the reviewed deliverable in the new repository.

**Acceptance:** An authenticated owner can store/reopen world, cast, persona, scene and canon; unauthenticated requests cannot read private state.

## Task 2: Context preview with provenance and budget

**Files:** `context.py`, `token_budget.py`, `api/context.py`; `backend/tests/test_context_selection.py`, `test_context_budget.py`; fixture files.

**Consumes:** effective profiles/memory, branch head and committed transcript from Task 1.

**Produces:** `build_context_preview(campaign_id, branch_id, action, model_config)` and `load_context_preview(preview_id)`. No provider call occurs during preview.

- [ ] Define a 120-turn fixture with Henn and distinct NPCs, approved interval summaries, aliases, location changes, a milk-promise event far back, and a character mentioned without entering the scene. Mark facts as synthetic test data. Coverage checks must show older turns replaced by valid summaries while the latest committed turn remains verbatim.
- [ ] Add expected source IDs: scene cast, pinned Henn agency rule, old unresolved promise and relevant lore. Add excluded IDs for another campaign, pending facts and irrelevant side lore.
- [ ] Write failing tests for relevance, alias match, deterministic ordering, provenance and exclusion. Add one exact-counter fake and one estimated-counter fake to verify labeling.
- [ ] Implement mandatory/optional blocks, normalized keyword/alias matching and stable ranking; show omission reasons and source links.
- [ ] Implement the budget formula from the spec; record every block cost. Required overflow returns a structured failure before network use. Unsupported model limits cannot fall back to guessed values.
- [ ] Ensure recent unsummarized committed turns remain required; only approved, nonstale summaries can replace covered turns. Request memory review when mandatory recent turns no longer fit.
- [ ] Implement the 75%-budget/scene-end review hint; test with one very long chapter that five-turn scheduling would miss. Do not discard an unsummarized turn to make the test pass. Add manual user-authored approved summary creation so the first playable checkpoint does not depend on Task 5 extraction.
- [ ] Save immutable preview and payload/config hashes; add stale-state detection for changed profile, memory or branch head.
- [ ] Orchestrator runs focused context tests and checks that preview source IDs can be traced back to real DB rows; commit reviewed deliverable.

**Acceptance:** Without AI, an engineer can inspect exactly which data the next turn would use, why, and whether the budget fits.

## Task 3: Real narrative loop through an isolated provider

**Files:** provider modules, `settings.py`, `generation.py`, `api/generation.py`; `backend/tests/test_generation.py`, `test_provider_contract.py`.

**Consumes:** immutable preview and expected branch head from Task 2.

**Produces:** a streamed candidate revision plus generation status/usage; `commit_candidate` accepts the selected candidate exactly once.

- [ ] Define provider capabilities: configured endpoint/model, context/output limits, streaming, usage reporting and token-count mode. Make a deterministic fake that can stop, fail, emit malformed frames and complete.
- [ ] Write tests: a complete stream creates one candidate; cancellation/failure does not commit a narrative turn; duplicate idempotency keys return the existing job; the same key with a different payload returns 409; a stale preview returns 409; two concurrent requests on one branch cannot both advance it. Reserve the job in a transaction before dispatch to the provider.
- [ ] Implement provider contract and generation/job states. Persist useful partial output as a draft, never approved history or memory.
- [ ] Run provider execution independently of browser stream lifetime. Add an authenticated job-state/content endpoint for reconnect; never auto-resubmit AI work when the tab resumes. Server restart marks in-flight jobs interrupted while retaining their drafts.
- [ ] Write disconnect/resume tests: one generation request continues on the backend, reconnect returns the same job/candidate, and the fake provider call count stays at one. An expired session cannot fetch the job.
- [ ] Add the lost-initial-response test: simulate connection loss before receiving job ID, recover via the UI-persisted idempotency key, and verify one upstream call. Delta offsets make repeated stream frames safe. Disable implicit HTTP/SDK retries; ambiguous dispatched jobs become interrupted, while never-dispatched queued jobs can resume.
- [ ] Implement explicit candidate commit and per-branch concurrency guard plus global two-provider-job semaphore/queue and 300-second default timeout. Validate head/checkpoint/state version at preview, start and commit. Active generation blocks effective canon/scene/memory mutations with 409; editing drafts stays possible. A complete stale candidate remains readable but cannot commit to another state.
- [ ] Add backend-only provider configuration with masked reads. Never expose raw key in error responses, logs or context preview.
- [ ] Implement one configured chat HTTP adapter; validate its request/stream format using mocked provider frames and official documentation of the endpoint selected at execution time. Providers lacking that exact contract must be rejected as unsupported rather than treated as compatible by name.
- [ ] Record two candidate models available to the user, compare context/output support and quoted pricing from their official docs, and let the user configure the chosen endpoint. Run a paid trial only via an explicit user action.
- [ ] Orchestrator runs generation/contract tests, reviews secret handling and failure paths, then commits reviewed deliverable.

**Acceptance:** The player can generate and choose a response; errors preserve drafts and do not poison the story or memory.

## Task 4: Reader and editable memory UI

**Files:** frontend campaign/story/memory/settings features, typed API client; story and memory interaction tests; static frontend wiring in `app.py`.

**Consumes:** Task 1 CRUD, Task 2 preview and Task 3 streaming/commit endpoints.

**Produces:** an authenticated mobile-first browser play loop, usable against the development or hosted backend.

- [ ] Build a one-column phone reader/composer with campaign drawer and memory sheet; expand to three panels on desktop. Keep labels in Vietnamese; render Markdown with raw HTML disabled.
- [ ] Add login/session-expiry/logout UX; remove private in-memory API state on logout. Re-login can retrieve the existing backend job without starting another request.
- [ ] Add world/cast/persona forms, scene and canon editing, masked provider setup and connection status.
- [ ] Add story input, automatic preview-then-send, streaming, cancel, candidate selection and “Dùng lượt này”. Keep “Xem context” optional during normal play. Sending the next action first commits the displayed complete candidate with expected state version, then creates a fresh preview; an incomplete/stale candidate cannot auto-commit.
- [ ] Add context inspection with selected source, omission reasons and exact/estimated token labels. Use user-readable wording; keep raw payload in an optional details view.
- [ ] Write interaction tests: a network failure preserves typed input; a required-budget failure opens context details; editing scene invalidates old preview; an unapproved fact is labeled and absent from approved memory.
- [ ] Use keyboard controls without submitting while IME composition is active. Keep focus and reader scroll stable during streaming; preserve manually scrolled reading position.
- [ ] Check 360/390/430 CSS px widths, 44px touch targets, safe-area and virtual keyboard. Ensure composer stays visible without covering the latest text, no horizontal overflow, and drawer/sheet close controls remain reachable.
- [ ] Add reconnect on foreground/network recovery: retrieve job status by ID or persisted idempotency key, resume content by offset, distinguish completed/interrupted/failed jobs, retain the player draft, and never auto-retry generation. Keep a pending-action key across reload until job state is resolved; clear private cached state on logout.
- [ ] Add the PWA manifest/icons/standalone mode. Do not cache private API responses or promise offline generation. Verify available install paths in the target browser.
- [ ] Build frontend, serve it through backend and smoke-test campaign creation → preview → fake stream → commit → reload.
- [ ] Orchestrator reviews diff, runs frontend interaction tests/build and a browser smoke check before committing.

**Acceptance:** The owner can play on a narrow mobile viewport, inspect/edit memory, and recover after reconnect without generating a duplicate turn.

## Task 5: Proposed summaries and memory with conflict review

**Files:** `consolidation.py`, memory API/UI changes; `backend/tests/test_consolidation.py`, frontend proposal-review tests.

**Consumes:** committed turn/revision IDs, approved canon/scene and generation job mechanism.

**Produces:** durable pending scene/fact/summary proposals and explicit approve/reject operations.

- [ ] Define extraction output schema with typed slots where applicable, kinds, source IDs and candidate changes; validate source references against the selected checkpoint's transcript. Valid references do not prove semantic truth. Freeform conflict detection is advisory; an output cannot directly become approved memory.
- [ ] Write tests: fabricated source ID is rejected; contradictory canon is a pending conflict; extraction failure does not undo a completed story turn; restarting recovers a queued job without duplicating proposals.
- [ ] Implement consolidation as an explicit “Cập nhật bộ nhớ” action and a suggestion at scene end or 75% of effective input cap. Do not make undisclosed extra paid calls per turn. Show the bounded input/output plan before starting; use the global job quota/timeout.
- [ ] Chunk long source intervals to fit the consolidation model budget at turn/paragraph boundaries; retain exact revision coverage and progress. Combine validated leaf summaries only if another bounded job is needed, keeping source mappings. Reject over-budget attempts before dispatch. Test restart of queued jobs versus interrupted dispatched jobs separately; the latter require an explicit new attempt.
- [ ] Group proposals for quick review; allow text correction before approval. Display old/new facts side by side when a replacement is proposed.
- [ ] Approve summaries only for exact committed revision intervals; record coverage, and detect overlap/staleness before using them in context.
- [ ] Test the unsummarized-history overflow path: prompt play pauses with a memory-review action rather than dropping old turns silently.
- [ ] Orchestrator runs focused tests and simulates a model returning valid JSON with an incorrect fact to ensure correction/rejection works; commit reviewed deliverable.

**Acceptance:** Memory improves through visible, reversible review; the AI cannot silently rewrite a character or established event.

## Task 6: Reroll and branch-correct snapshots

**Files:** timeline/context/memory/generation changes; story branch UI; `backend/tests/test_branch_isolation.py`, `test_revision_selection.py`.

**Consumes:** selected revisions, versioned profile/memory/scene, summary source intervals and context snapshots.

**Produces:** `fork_branch(campaign_id, source_branch_id, checkpoint_id, expected_state_version)` plus uncommitted reroll candidates; immutable historical context views. The checkpoint must belong to the playable source lineage and identify state before the turn being replaced.

- [ ] Write tests with branches A/B: A wins a match and B loses it; each branch context contains only its own outcome. A fork before the match includes neither future outcome.
- [ ] Add tests that a later profile edit and summary do not alter the snapshot of an earlier turn. Selecting an uncommitted reroll cannot keep memory sourced from a discarded candidate.
- [ ] Add the same-turn-version test: approve two memory/profile changes at the same turn, fork from the first checkpoint, and exclude the second mutation even if it cites an old source turn. Imported archive turns lacking a playable state checkpoint cannot be fork targets.
- [ ] Implement branch ancestry and checkpoint/version cutoffs for inherited transcript/profile/memory/scene/summary. Every retrieval path applies the selected checkpoint before ranking; source timestamp alone cannot determine visibility.
- [ ] Implement reroll on uncommitted candidates in the same branch. Reroll of any committed turn, including the last one, forks from its preceding checkpoint and leaves old memory/history intact in the old branch.
- [ ] Add the “Tạo nhánh từ đây” UI with visible branch name and last shared turn. Generation and memory jobs stay branch-scoped.
- [ ] Run the full 120-turn replay on both branches and check exact expected/excluded context source IDs.
- [ ] Orchestrator reviews ancestry queries and transaction boundaries, runs regression suite, then commits reviewed deliverable.

**Acceptance:** The player can try a different outcome without memories from the abandoned future returning later.

## Task 7: Existing-story import, backup and development startup

**Files:** transfers module/API/UI, scripts, README, `.gitignore`; `backend/tests/test_transfers.py`, `test_backup_restore.py`.

**Consumes:** complete versioned campaign schema and snapshot formats.

**Produces:** versioned JSON transfer, transcript import preview and documented single-command local operation.

- [ ] Define export schema version 1 with turns/revisions, branch ancestry, state checkpoints, memory/profile/scene versions, summary sources and context-run metadata. Reject unsupported versions/invalid source references before writes. File limit is 20 MiB; enforce it before reading the complete body.
- [ ] Write round-trip tests: export/import reconstructs context source text and branch outcomes; secrets are excluded; invalid references reject the entire import with no partially created campaign.
- [ ] Preflight export against the configured transfer limit so the app never claims to create a restorable export it will reject on import. Test the oversized-campaign path: explain changing the limit after resource checks or using administrative DB backup, without truncation. Fresh campaign imports remap entity/version/reference IDs consistently instead of colliding with an existing campaign; compare normalized context/source text, not remapped UUID equality.
- [ ] Implement JSON transcript import and TXT/Markdown preview with explicit user correction of speaker/order; retain original text and identify partial imports.
- [ ] Split raw historical imports into bounded consolidation chunks, provide progress and review the initial playable canon/scene/summary checkpoint. Mark missing history unknown. Historical raw transcript stays searchable but cannot be forked before a verified state checkpoint; full app-export imports preserve their historical checkpoints. Test an import exceeding 12.000 tokens without sending one oversized model request.
- [ ] Prepare a `playrooom` import worksheet with persona, cast, canon, current scene and unresolved events. Fill only verified facts from available material; ask the player to complete missing initial history instead of inventing it.
- [ ] Implement SQLite backup using the DB backup API and restore into a new validated file before replacing the active DB. Test backup while the app has an open connection.
- [ ] Implement PowerShell startup without visible helper consoles, bind only localhost, serve built frontend, and preserve existing DB across launches. Startup must stop cleanly with an actionable port/runtime error instead of deleting data.
- [ ] Document install/build/start, key setup, memory review, branch behavior, export/restore and where local data lives. Ignore DBs, local provider config/secrets, caches and generated exports.
- [ ] Orchestrator runs backend suite, frontend tests/build, export/restore check and final browser smoke from a fresh launch. Review all changes against spec, then commit reviewed deliverable.

**Acceptance:** A developer can start locally; the owner can import a reviewed story, keep playing after restart and restore an exported campaign. Hosting is verified separately in Task 8.

## Task 8: Private mobile web deployment

**Files:** `deploy/playroom.service`, `deploy/playroom.caddyfile`, `deploy/release.sh`, `deploy/README.md`, `.github/workflows/ci.yml`, `.github/workflows/deploy-production.yml`; app production settings; `backend/tests/test_production_settings.py`; mobile deployment smoke notes.

**Consumes:** owner auth, built responsive frontend, durable generation jobs, SQLite backup/export and environment configuration from Tasks 1–7.

Essential private staging can consume Tasks 1–4; retain the release/transfer/restore completion gates until Tasks 5–7 are integrated.

**Produces:** a deployable single-instance app with persistent storage, HTTPS and an authenticated private URL. No service is purchased or published during planning.

- [ ] Treat the user's latest Caddy correction as authoritative; read wedding docs only for reusable release/persistence rules. Inventory the live host read-only: OS/architecture, RAM/disk, systemd/Python, listeners, installed Caddy version/active config mechanism/certificate storage, sites and wedding health. Do not infer actual domain/app-root from example config or print secret values.
- [ ] Package frontend build plus Python app/locked dependencies for the audited Linux ARM64/Python runtime. Use compatible ARM64 wheels; do not copy a Windows/x64 virtualenv or alter wedding's Node runtime.
- [ ] Create Playroom's own release/shared layout: releases by commit, current symlink, shared config/secrets, shared/data/playroom.sqlite3 and shared/backups. Deploy code cannot replace shared data. Create a per-release Python environment with the compatible locked wheel bundle.
- [ ] Run one Uvicorn worker under its own systemd service, binding only loopback on a confirmed free port. Proposed port 3100 must be checked rather than assumed free. Existing Caddy handles Internet traffic; do not expose the app port or launch another proxy.
- [ ] Prepare a Playroom site block for the active Caddy configuration mechanism, proxying to the private upstream. Keep existing site blocks/certificate storage unchanged. Trust proxy headers only from the audited loopback proxy, never arbitrary clients.
- [ ] Backend streams SSE with `Content-Type: text/event-stream`; check immediate chunks through existing Caddy HTTPS using its installed version. Avoid copying Nginx buffering directives or adding version-specific Caddy options without need. Verify reload/network disconnect recovery through the actual proxy.
- [ ] Validate production settings: explicit allowed origin/hosts, Secure cookie, masked secrets and no development bypass. Configuration cannot silently start a public deployment without auth.
- [ ] Add service/release restart verification: create/commit a campaign, restart service and activate another compatible release using the same shared data, then compare campaign/branch/context hashes. Export must exclude owner credentials/sessions as well as provider keys.
- [ ] Add migration rollback preparation: backup with SQLite API before a schema upgrade; restrict administrative DB backups, document restoring a validated backup to a new data directory and revoke old sessions on server restore. A release deployment must never delete/reinitialize an existing DB. Code rollback must respect DB schema compatibility and cannot silently restore runtime data.
- [ ] Mirror the wedding deployment discipline in Playroom's own CI: tests and artifact checks precede activation, SSH uses trusted host-key checking, pre/post activation verifies persistent paths/SQLite integrity and health, and automatic deploy remains disabled until deliberately enabled after a successful manual rollout. No wedding secrets/workflow/CD gate is changed as a side effect.
- [ ] Select a domain/subdomain controlled by the user for this app and confirm DNS. No new VPS purchase is part of this plan; separately record any actual domain/AI costs and obtain missing access through the appropriate secure setup flow.
- [ ] Configure DNS/domain using existing Caddy HTTPS. Save current full config, validate/adapt using the deployed adapter/environment when supported, then reload the running instance within user-authorized deployment scope. Account for modules whose validation contends with the running process; never replace validation failures with a forced restart. A failed reload must preserve the active configuration.
- [ ] Verify login/logout including open-stream revocation, blocked unauthenticated story/context/export, SSE, lost-response idempotency recovery and resume through the real HTTPS origin. Check all existing site health before/after. On activation failure restore only Playroom's changed app/config; do not auto-restore DB or modify wedding data/releases/secrets.
- [ ] Test a 20-turn play loop on the user's phone/browser, including keyboard opening, app background/resume and one network disconnect; check another mobile engine when available. Document which checks used a real device and which used emulation.
- [ ] Orchestrator reviews deployment diff, runs production/auth tests, verifies shared-directory persistence and restore, and records the real URL only after successful deployment.

**Acceptance:** The private URL works on the phone without the player's PC running; story state survives service/release restart, reconnect produces no duplicate paid request, and wedding-online health/persistent state is preserved.

## Final quality trial and completion gate

- [ ] Record deterministic replay results separately from live model quality. Passing fake-provider tests says nothing about storytelling quality.
- [ ] With the chosen model and user-controlled API calls, play at least 20 additional turns around the 120-turn fixture or a reviewed imported campaign.
- [ ] Grade: Henn agency, NPC identity/voice, scene continuity, old promise retrieval, branch outcome, cost/latency visibility and ability to correct errors.
- [ ] Include mobile keyboard/readability, owner login, foreground resume and hosted persistence in user acceptance. PWA home-screen installation is tested only through browser-supported flows.
- [ ] If failures come from missing/wrong retrieval, fix retrieval before increasing context or changing model. If retrieval is correct but narrative ignores it, revise prompt/model configuration and repeat only the affected trials.
- [ ] User accepts play quality; orchestrator reports test evidence, remaining model limitations and actual file/project locations.

Do not mark the MVP done merely after scaffolding, mock UI, an API smoke call or a frontend build. No elapsed-time estimate is committed before a real provider and initial trial are selected.
