# Playroom Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development or executing-plans task-by-task. Follow AGENTS.md: Sol coordinates/reviews, gpt-5.6-luna medium writes implementation. Each task below has its own gate. Do not claim the whole plan complete after one task.

**Goal:** Close backend runtime acceptance, deliver a playable authenticated local browser app, then add long-story operations without losing provenance or replaying AI calls.
**Architecture:** Keep current FastAPI/SQLite backend and shared wire/physical-attempt modules. Build a React/TypeScript/Vite client against owned, versioned API projections. Explicit development demo uses synthetic inference; production profiles remain verified and server-owned.
**Tech Stack:** Python 3.12+, locked uv dependencies, FastAPI/Uvicorn/SQLite; React/TypeScript/Vite with locked npm dependencies; pytest, frontend interaction tests, real loopback HTTP and browser validation.
**Spec:** [product](../specs/2026-10-12-personal-playroom-design.md), [runtime](../specs/2026-10-12-runtime-ai-context-policy.md), [full eight-task plan](2026-10-12-personal-playroom-implementation-plan.md).
**Resume state:** [authoritative handoff](../../handoff/2026-10-13-state.md), code snapshot a35a2a6.

## Global Constraints

- One coding agent at a time; model gpt-5.6-luna, medium unless a specific task explicitly needs another effort. No self-spawned reviewers/helpers. If unavailable, stop implementation and report it.
- Use the existing worktree/feature branch. Inspect status before edits; preserve existing changes. No reset/clean, main merge, or worktree recreation.
- On this Windows host read C:\Users\huy.nguyen\.codex\RTK.md; shell commands begin with rtk.
- No live model calls, real keys, SSH, DNS or Caddy changes in the local phase. Local fake/mocked tests are authorized.
- No implicit production fake provider, paid/model/provider fallback, mode switch, retry or truncated candidate commit.
- Input 12,000 / total completion 4,000 including reasoning / wrapper 512; effective input min(configured input, verified context window minus completion and wrapper). Budget each role and aggregate USD parent.
- Maximum two physical attempts, default timeout300s; hold slots until the actual thread stops. Short transactions; never SQLite transaction across provider IO.
- All story/context/export/job APIs require owner authentication. Canon/presence/knowledge/agency/style/provenance and checkpoint-selected raw/summary coverage remain intact.
- Reconnect reads the same job/key/event cursor. UTF-16 code-unit offsets; never resubmit inference to recover.
- Reports are evidence, not authority. A green test with wrong setup does not satisfy a requirement.
- Scratch/DB/secrets/exports/APK/assets stay out of Git. Write reports in ignored .superpowers/sdd workspace; stage exact app/test/doc paths.
- VPS uses existing Caddy; domain play.nhkhuy.run.place. Live rollout remains deferred by the user.

## How Luna must execute

Only the assigned task is in scope. Read its file list and consumes/produces contracts; do not implement several subsystems to “finish faster”.

For each task:

1. Inspect the named code and existing tests.
2. Write the specific failing regression before behavior changes. Run only that regression and record the real failure.
3. Make the smallest fix. Do not rewrite generation.py or replace storage/auth/profile modules.
4. Run named covering tests; inspect every failure. Update the report with commands, counts, code SHA, requirement-to-test map and unresolved issues.
5. Run exact `rtk proxy git diff --check BASE HEAD` after commit. Filtered `rtk git diff --check` is insufficient.
6. Sol reviews the entire task range and runs relevant independent verification. Do not start the next task until its gate passes.
7. If scope is too large, report NEEDS_CONTEXT with preserved changes. Do not report DONE while deferring a required case. Do not manufacture RED/GREEN output or use blanket “all edge cases covered”.

A task gate means implementation + valid test setup + diff review. Running the backend suite is not the full Task3 gate.

## Backend acceptance — first

### B1: Guard every director usage/result write

**Files:** modify backend/playroom/generation.py; test backend/tests/test_generation_fix4.py.
**Consumes:** GenerationService._execute, _record_usage, _require_active, _finish_attempt; transaction(connection); persisted job/attempt epoch and cancel status.
**Produces:** no director ledger/output/event/context write survives an old epoch or cancelled claim; valid director usage/output remains visible if later packing fails.

- [x] Add separate-connection regressions for recovery epoch change and cancel AFTER the valid director result has passed _require_active, at entry to post-result _pack_selected or _narrator_request. A barrier before provider return only retests the earlier gate and misses this defect.
- [x] Capture reserved_cost_json, context_runs, generation_events, final_context_json and attempt output/usage before releasing the old writer. Assert no new stale result/ledger/context/success event afterward. Current-epoch cancellation cleanup may emit terminal control events; it must not write provider result bytes, success or billing evidence.
- [x] Retain the existing post-director packing failure test: valid current result retains usage/output, no dispatched rows or branch guard leak, narrator0 calls.
- [x] Remove the unconditional _record_usage before the completion transaction and guard both packing-error paths. Perform validation and writes inside one BEGIN IMMEDIATE boundary with epoch/status/cancel CAS; do not hold it across inference.
- [x] Check narrator success/event boundary touched by the same invariant; change it only if a focused test proves a late-write defect.
- [x] B6 follow-up: status-only transition after a valid director result rejects packing-error usage/result writes; the test is RED when the job-status predicate is disabled.
- [x] B6 follow-up: narration delta output/draft/event writes share a short transaction with active epoch/status/cancel CAS; separate-connection cancel and recovery races are RED before the fix.
- [x] Run:

```powershell
rtk proxy uv run --locked --extra test pytest backend/tests/test_generation_fix4.py -q
rtk proxy uv run --locked --extra test pytest backend/tests/test_generation_durable.py -k "restart or cancel or epoch" -q
```

**Regression shape:** use the existing _story fixture and a synthetic provider. A barrier in the post-result packing method hands control to another DB connection AFTER the initial active check; it commits cancel/new epoch, then packing throws or returns. The writer then tries the currently unguarded usage path. Test this shape, not just an always-false monkeypatch:

```python
@pytest.mark.parametrize("transition", ["recover", "cancel"])
@pytest.mark.parametrize("packing_error", [False, True])
def test_old_director_result_cannot_write_after_transition(
    tmp_path, monkeypatch, transition, packing_error
):
    from playroom.context import build_candidate_pool

    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(
        db, campaign.id, campaign.initial_branch_id, "Look",
        checkpoint_id=head.checkpoint_id, owner_id=owner.id,
    )
    selection = {
        "checkpoint_id": head.checkpoint_id,
        "action_hash": pool["action_hash"],
        "selected_memory_ids": [],
        "reasons": {}, "reason_sources": {},
        "scene_ids": pool["scene_ids"], "conflict_flags": [],
    }
    provider = FakeProvider([json.dumps(selection), "must not narrate"])
    service = GenerationService(db, provider)
    job = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Look",
        idempotency_key="old-writer", expected_checkpoint_id=head.checkpoint_id,
        mode="quality", execute=False,
    )
    entered = threading.Event()
    release = threading.Event()
    original = service._pack_selected

    def held_pack(*args, **kwargs):
        entered.set()  # AFTER valid result and the earlier _require_active.
        assert release.wait(5), "post-result test barrier timed out"
        if packing_error:
            raise RuntimeError("synthetic packing failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_pack_selected", held_pack)
    worker = threading.Thread(target=lambda: service.run(job["id"]), daemon=True)
    other = connect(db.execute("PRAGMA database_list").fetchone()["file"])
    try:
        worker.start()
        assert entered.wait(3)
        competing = GenerationService(other, FakeProvider([]))
        if transition == "recover":
            competing.recover_after_restart()
        else:
            competing.cancel(owner.id, job["id"])
        before = db.execute(
            "SELECT reserved_cost_json FROM generation_jobs WHERE id=?",
            (job["id"],),
        ).fetchone()[0]
        attempt_before = tuple(db.execute(
            "SELECT output_text, usage_json FROM provider_attempts "
            "WHERE generation_job_id=? AND stage='context'", (job["id"],),
        ).fetchone())
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert db.execute(
            "SELECT reserved_cost_json FROM generation_jobs WHERE id=?",
            (job["id"],),
        ).fetchone()[0] == before
        assert tuple(db.execute(
            "SELECT output_text, usage_json FROM provider_attempts "
            "WHERE generation_job_id=? AND stage='context'", (job["id"],),
        ).fetchone()) == attempt_before
        assert db.execute(
            "SELECT COUNT(*) FROM context_runs WHERE generation_job_id=?",
            (job["id"],),
        ).fetchone()[0] == 0
        assert provider.stage_counts.get("narration", 0) == 0
    finally:
        release.set()
        worker.join(3)
        other.close()
```

**Gate:** both competing cases pass with genuine ordering; valid-current failure still retains evidence; no public API change. Stop after B1 for its review.

**B1 accepted 2026-10-13:** implementation commit `e929bc363ff714e7ab6af5d3e6ec115516409882`; review assertion fix `d5d358e`. RED: director race regression `4 failed, 14 deselected`; narrator completion race `1 failed, 18 deselected`. GREEN after review fix: director race `4 passed, 15 deselected`; `test_generation_fix4.py` `19 passed`; durable `-k "restart or cancel or epoch"` `8 passed, 33 deselected`. The P2 assertion now checks event type and payload phase. Sol independently reran the covering commands and checked the committed range. B2 remains unstarted.

### B2: Replace the misleading quality SSE phase tests

**Files:** backend/tests/test_generation_durable.py only; application code changes require a proved failure and explicit scoped follow-up.
**Consumes:** _start_local_http(app), _stop_local_http(server, thread), _http_request(connection,...), http.client; current SSE/status/by-key routes.
**Produces:** independent socket disconnect in each actual quality phase, exact one director/one narrator, no replay.

- [x] Replace the three newly preserved TestClient stream tests. Do not use TestClient for an active SSE disconnect.
- [x] Parameterize director/after_director/narration. Provider barriers must hold the exact phase; each test reads persisted attempt status before disconnect.
- [x] Director: provider has entered structured generation but has not returned.
- [x] After director: DB context attempt is completed, narrator calls still0; hold worker before physical narrator invocation.
- [x] Narration: context completed; narrator has emitted a delta and is held before terminal result.
- [x] Open the authenticated SSE stream through a separate http.client.HTTPConnection, read a complete SSE frame, then close response/socket before releasing the provider barrier.
- [x] Reconnect through status/by-key/events; assert same job ID, exact stage counts, complete candidate, one ContextRun. Do not POST generation again.
- [x] Every barrier has bounded failure timeout; use finally to release it and stop the server. Do not let a 5-second auto-release masquerade as the intended phase.
- [x] Run only `-k "quality_sse_disconnect"`; record phase DB evidence and counts.

```python
server, thread, port = _start_local_http(app)
stream_connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
try:
    # Login and reserve with a different connection, then hold the exact phase.
    stream_connection.request(
        "GET", f"/api/generation/jobs/{job_id}/events/stream",
        headers={"Host": "127.0.0.1", "Cookie": cookie},
    )
    response = stream_connection.getresponse()
    assert response.status == 200
    assert response.fp.readline()  # Read a full frame in the actual test.
    response.close()
    stream_connection.close()
    phase_release.set()
    # Poll GET status/by-key until candidate; assert calls == (1,1).
finally:
    phase_release.set()
    stream_connection.close()
    _stop_local_http(server, thread)
```

**Gate:** closing the socket happens while the chosen phase is held; test succeeds before barrier timeout. Source review must see that ordering.

**B2 accepted 2026-10-13:** test commit `8996379` replaces all three TestClient disconnect cases with authenticated loopback sockets. DB phase evidence: director `dispatched` while provider is held; after-director context `completed`, narration `claimed`, provider calls0; narration context `completed`, narration `dispatched` with persisted delta. Each case reads a complete SSE frame, closes the socket before releasing its barrier, then reconnects with GET status/by-key/events and verifies the same candidate/job, one call per stage and one ContextRun. Focused command: `pytest backend/tests/test_generation_durable.py -k "quality_sse_disconnect" -q` — 3 passed, 38 deselected. B3 remains unstarted.

### B3: Real HTTP cancel wins the claim race

**Files:** backend/tests/test_generation_durable.py; generation.py only if the test exposes a defect.
**Consumes:** local Uvicorn helper, HTTP generate/cancel/status, shared registry final invocation gate.
**Produces:** HTTP cancellation before claim CAS causes zero provider invocation and no stranded guard.

- [x] Keep or rename the old always-false claim test as a smoke test; it is not the required race.
- [x] Hold worker at a narrow hook immediately before claim/invocation CAS.
- [x] POST cancel over another authenticated loopback socket, confirm terminal/cancel flag persisted, then release worker.
- [x] Assert provider calls0, no physically dispatched_at, no candidate/ContextRun, no guard. GET recovery must not add attempts.
- [x] Consider queue waiting after physical slot release: the existing registry-level `test_waiting_attempt_can_cancel_before_a_slot_and_never_invokes` covers the slot-wait cancellation path; B3 adds separate HTTP proof for the DB invocation CAS after claim.
- [x] Focused command: `pytest backend/tests/test_generation_durable.py -k "zero_row or claim_race" -q` via rtk/uv.

**Gate:** no lambda-false shortcut replacing cancellation and no blanket stage-count assertion hiding dispatch timestamps.

**B3 accepted 2026-10-13:** test commits `072a829` and `515226d`. The real authenticated HTTP race cancels while the context attempt is `claimed` and paused at `_invocation_gate`; cancellation is persisted as terminal before release. After release: provider calls0, attempt `interrupted`, `dispatched_at IS NULL`, no ContextRun/guard/candidate, and status/by-key GET returns the same job without another attempt. Focused command: `pytest backend/tests/test_generation_durable.py -k "zero_row or claim_race" -q` — 3 passed, 39 deselected. No production defect found. B4 remains unstarted.

### B4: Inventory every existing story mutation guard

**Files:** create backend/tests/test_generation_mutation_guards.py; optionally small test helper extraction only if needed. No production refactor unless a test fails.
**Consumes:** valid campaign with actor, approved and pending memories, branch checkpoint; queued/running generation; current service/API signatures.
**Produces:** every mutation row below refuses while protected and leaves all persisted state unchanged.

| Case | Existing operation |
|---|---|
| world/persona/style/actor edit | campaigns.update_profile |
| actor add/remove | campaigns.add_character/remove_profile |
| rename/archive | campaigns.rename_campaign/archive_campaign |
| memory create approved/pending | memory.append_memory_version |
| memory edit/pin | memory.update_memory |
| approve/reject/delete | memory.approve_memory/reject_memory/delete_memory |
| scene/retrieval | memory.update_scene/set_retrieval_policy |
| public checkpoint/revision | timeline.create_state_checkpoint/create_committed_revision |

- [x] One fresh fixture per mutation x queued/running. All arguments valid; unused removable actor has no scene/memory reference.
- [x] Prepare approved/pending memory before reservation; use its current state version.
- [x] Expect StateConflict from services; malformed-payload ValidationError cannot satisfy the test.
- [x] Compare head checkpoint/state version, counts for profile_versions, memory_versions, scene_versions, state_checkpoints, turn_revisions, and persisted profile/memory/scene/checkpoint/campaign rows.
- [x] No silent partial archive/title/pin changes; valid unguarded success controls cover all 19 operations and assert persisted state changes.
- [ ] Future consolidation/fork/transfer mutations add their own guard regressions when implemented.
- [x] Run only this file then relevant campaign/memory tests.

**B4 accepted 2026-10-13:** commit `262503250cd6ce9d375d38d25e06634dd9a21f04`. The test matrix expands the table into 19 operation rows x queued/running (38 guard cases), each with its own fixture, and adds 19 valid unguarded success controls. Guard cases assert `StateConflict` and compare branch head/state version, required table counts, campaign fields, current checkpoint snapshot, and persisted profile/memory/scene rows. Approved and pending memory fixtures are created before reservation; removable actor has no scene/memory references. Sol independently ran `rtk uv run --extra test pytest backend/tests/test_generation_mutation_guards.py` — 57 passed, and `rtk uv run --extra test pytest backend/tests/test_campaign_storage.py backend/tests/test_memory_versions.py` — 20 passed. `rtk git diff --check` clean. No production defect found. B5 remains next; this does not accept Task3.

### B5: Prove real adapter wire and role-version identity

**Files:** test_provider_contract.py/test_generation_fix4.py/test_context_selection.py/test_model_switch.py; touch relevant runtime/resolver only on proved failure.
**Consumes:** OpenRouterAdapter, default_provider_factory with mocked client, provider_wire/canonical_json/wire_hash/declared_count, saved role versions, ContextRun.
**Produces:** JSON captured at client.stream equals persisted/countable provider payload for both stages; profile role identity does not collapse distinct versions.

- [x] Mock client.stream to capture its json argument and emit valid incremental SSE. Use dummy credential only.
- [x] Capture director response_format schema and narrator messages/model/provider.only/output allowance. Compare full JSON, not nonempty messages.
- [x] Recompute wire_hash(captured) and declared_count(canonical_json(captured)); compare attempt payload_hash and ContextRun role metadata.
- [x] Test same persisted profile id with context v1/narrator v2 in economy and quality, then switch the opposite role. Generation uses the pinned matching role/version/hash.
- [x] Retain and review the fractional aggregate/known-director remaining/unknown-director reservation proofs without rewriting them.
- [x] Test persisted settings update after queue leaves the captured payload/profile on the queued revision; a revoked pinned CredentialStore version opens zero HTTP streams.
- [x] Run named test files; no live metadata verification or inference.

**B5 accepted 2026-10-13:** test commit `78909fb8671077ac350789ec589fbe9f586a4069`. Mocked OpenRouter SSE captures both quality stage JSON payloads; exact emitted JSON equals the persisted ContextRun wire, recomputed hash equals provider attempt/context payload hash, and canonical declared count equals the persisted budget. Captured director schema, narrator wire, model, provider-only and output allowance are asserted. Same-ID v1/v2 roles are persisted and bound through owner settings for economy, quality, and swapped quality; provider factory and ContextRun snapshots retain each role's ID/version/hash. A queued job retains v1 profile/settings revision and output allowance after a real persisted v2/budget update; a revoked CredentialStore version opens zero mocked HTTP streams. Existing fractional cap and known/unknown director remaining-allowance tests were reviewed and left intact. Sol independently ran `rtk uv run --locked --extra test pytest backend/tests/test_provider_contract.py backend/tests/test_generation_fix4.py backend/tests/test_context_selection.py backend/tests/test_model_switch.py -q` — 68 passed; `rtk git diff --check` clean. No production changes. B6 integrated Task3 review is next; this does not accept Task3.

### B6: Integrated Task3 review and local backend gate

**Files:** docs/handoff status and relevant test fixes only through scoped implementation follow-ups.
**Consumes:** B1–B5 and full diff 949068a..accepted HEAD.
**Produces:** accepted backend boundary for UI.

- [x] Sol reviews the full Task3 range with product/runtime specs, exact proofs and source; both compliance and code-quality verdicts required.
- [x] Independently run full backend suite, compile, runtime-only startup/shutdown and exact committed-range whitespace check.
- [x] Confirm default startup has no implicit synthetic provider or usable fabricated real profile; tests/demo explicit.
- [x] Audit saved secrets/validation errors/ContextRun/profile settings and all old writer result/event paths. No provider IO inside DB transaction.
- [x] Fix reviewed findings in bounded tasks; retain all unresolved acceptance items explicitly. No unresolved B6-scope findings; later task debt remains in the handoff.
- [x] Update handoff counts/status only after proof. Do not infer storytelling quality from synthetic tests.
- [x] Gate B6 before U1. No live provider trial is necessary to create the local synthetic UI.

**B6 accepted 2026-10-13:** code/test commit `94e894ef6ca6daedff9be1a5349c9df38082cce9`. Integrated compliance and code-quality review of `949068a..HEAD` found two writer gaps: `_require_active` did not require job status `running`, and narration `_append_output` wrote attempt output, job draft and delta event after a check but outside a transaction. Added status-only post-director packing-error regression (RED when the status predicate is disabled, then GREEN) and cancel/recovery post-gate narration-delta regressions (2 RED, then 2 GREEN). The fix repeats the active check inside `BEGIN IMMEDIATE`, CAS-updates attempt and job by epoch/status/cancel, and writes the delta event in that transaction; no provider I/O is in the transaction. Sol independently ran the full backend suite — 208 passed; `test_generation_fix4.py` — 28 passed; `test_generation_durable.py -k "restart or cancel or epoch"` — 9 passed, 33 deselected; compileall — exit 0; isolated runtime-only default app startup/shutdown — success with no injected provider; `git diff --check 949068a..HEAD` — clean. No live credentials/inference, frontend or deploy. This accepts the backend boundary for UI; it does not establish story quality or finish the product. U1 is next after review.

## Local UI — split into independently reviewable tasks

The full requirements of original Task4 remain binding. Use actual current APIs; do not invent frontend response fields or recreate a parallel backend.

### U1: Locked frontend, typed API and login

**Files:** frontend/package.json, npm lock, tsconfig/Vite config; src/api/client.ts/types.ts; features/auth; app shell and tests.
**Consumes:** current /api/auth/login/me/logout shapes read from api/auth.py.
**Produces:** same-origin typed client, owner login/logout/401 handling, cleared private cache, buildable Vietnamese shell.

- [x] Lock dependencies after checking compatible Node/Vite versions; Node on this host24.18 supports current chosen baseline.
- [x] Client uses credentials same-origin, JSON errors mapped with status/code; it never embeds key/model caps.
- [x] Login requires no AI call. Logout clears story/jobs/drafts/private pending-key caches; session expiry shows re-login.
- [x] RED interaction tests for login failure, logout clearing, session expiry and auth-generation races; then typecheck/tests/build.
- [x] UI modular; no all-in-one App.tsx. No fake enabled play button.

**U1 accepted:** real behavioral RED/GREEN included logout/auth-generation races; frontend interaction suite 7 passed, typecheck and Vite production build passed, independent review found no actionable findings. Sol inspected the login screen at 390px. This is the login shell only; protected campaign reads, full shell browser smoke and playable demo remain U2–U7.

### U2: Owned head/transcript/recovery reads

**Files:** backend/api/campaigns.py plus owned projection service; typed frontend campaign/job API; focused ownership tests.
**Consumes:** load_state_checkpoint and selected_revision_ids in stored order.
**Produces:** authenticated current branch head/profiles/ordered chosen transcript, bounded owned active/recent-job lookup.

- [x] No raw DB/latest-version read. Validate campaign/branch ownership on every projection.
- [x] Preserve inherited selected order; duplicate local sequence must not reorder it.
- [x] Re-login can discover active/candidate job even after explicit logout cleared its client key; keep this recoverable index ahead of bounded recent terminal rows.
- [x] Non-owner/foreign IDs404 or auth failure; job projection is allowlisted and filters generation operations.
- [x] Review exact output types before consuming them in U3/U6.

**U2 accepted:** focused projection suite 8 passed; full backend suite 216 passed; compileall, frontend tests (7), typecheck, build, and independent review passed. Behavioral RED exposed transcript/head mismatch and recovery-job eviction before fixes. Projection binds branch metadata to the observed checkpoint, preserves checkpoint-selected order across 500-ID query chunks, and returns at most 20 owner-scoped generation jobs with recoverable statuses prioritized.

### U3: Reader layout and campaign creation

**Files:** features/campaigns/story layout, shared drawer/sheet components and tests.
**Consumes:** U1/U2 projections.
**Produces:** one-column phone reader, desktop left-nav/story/right-memory layout, new campaign from readable forms.

- [x] World/persona name and description; characters UUID + name + aliases array.
- [x] Markdown renderer disables raw HTML; comfortable Vietnamese paragraphs.
- [x] 360/390/430 widths without horizontal overflow, touch targets44px, reachable close controls/safe-area.
- [x] IME composition must not trigger submit. Streaming scroll behavior remains in U6.
- [x] Test campaign creation failure retains form; switching campaign clears previous view/job scope.

**U3 accepted 2026-10-13:** Campaign creation, reader layout, drawer/sheet interactions, and safe Markdown rendering are covered by `frontend/src/components/CampaignHome.test.tsx`; the suite records meaningful RED/GREEN regressions for IME submit cancellation, required character input, drawer focus restoration, selection `aria-pressed`, and shell load errors. Sol independently ran the fresh frontend suite — 14 tests passed — plus `npm run typecheck`, `npm run build`, and `git diff --check`; final independent review found no actionable findings. Browser validation at 360px, 390px, 430px, and 1024px found no horizontal overflow; desktop renders three columns, visible controls meet the 44px target, and drawer close/focus restoration and `aria-pressed` state work. No live provider/model call or deployment was used. U4 is the next review checkpoint.

### U4: Editable world/cast/style/scene/memory

**Files:** features/memory/campaign/profile/style forms, typed mutation API and tests.
**Consumes:** current expected_state_version; current profiles/memory/scene.
**Produces:** usable manual memory control with provenance, review and conflict preservation.

- [x] Defaults: vi, medium length, low headings/emojis, third_person; player agency forbids invented speech/thought/choices.
- [x] Preserve unknown profile dictionary keys when updating existing profile state.
- [x] Character aliases are arrays; knowledge_scope public/known_by/narrator_only, known_by actor UUIDs; association is not presence.
- [x] GET scene returns map; PUT sends list + focus_scene_id/present_ids with valid IDs.
- [x] Canon/event/lore/summary add/edit/pin/hide/history; pending proposals separate from approved facts; approve/reject explicit.
- [x] Retrieval auto/important_only/disabled. Summary exact source interval required; no JSON-only normal editor.
- [x] Successful mutation refreshes state;409 keeps the draft and refreshes authoritative version.
- [x] Test pending label, preserved extra fields, scene edit invalidation and conflict draft retention.

**U4 accepted 2026-10-13:** accepted at `fa18cbb7e90ee21ccd24ed1c029f14681944a0b5`. Behavioral RED/GREEN covered controlled memory edits, 409 draft retention and authoritative retry versions, scene conflict drafts, exact non-contiguous provenance, explicit structured-field null clearing, and rejection of self-supersession while preserving valid two-memory supersession. Sol independently verified backend campaign-storage/memory-version/projection coverage — 31 tests — frontend — 28 tests — plus typecheck, Vite build, and `git diff --check`; final independent review found no actionable findings. U5 is the next review checkpoint. The browser campaign→preview→fake stream→commit→reload smoke, real provider/model quality, hosting, and deployment remain open; this does not claim Task3 complete.
### U5: Masked OpenRouter/settings controls

**Files:** features/settings, typed provider API, interaction tests.
**Consumes:** provider credentials/profiles/verify/settings current API; immutable id/version/profile_hash bindings.
**Produces:** explicit provider/mode/policy/role/budget choices with capability/quota/cost status.

- [ ] API key remains server-side/masked. Native schema capability required for director/consolidation.
- [ ] Default economy/free_only unconfigured; paid mode requires explicit positive USD cap.
- [ ] Budget-only update preserves pinned role versions. Explicit model switch changes future jobs, never queued payload/story/style.
- [ ] Show provider billing vs calculated/estimated/unknown honestly, phase/operation counts separately.
- [ ] Quota/unsupported schema keeps player draft; explicit economy retry only. Never paid fallback.
- [ ] Use fake/mocked metadata routes in tests, no real key/API inference.

### U6: Send/stream/cancel/commit/reconnect

**Files:** features/story generation state machine, generation API, browser storage adapter and interaction tests.
**Consumes:** preview, generate, by-key/job/status/content/events/cancel/draft/commit APIs.
**Produces:** exactly one inference job per action identity, retained drafts and recoverable candidate.

- [ ] Persist branch/action/checkpoint/preview/idempotency identity BEFORE POST. Ambiguous response recovers GET by-key; never new-key auto retry.
- [ ] Automatic preview→send; optional context inspector shows source/omission/budget labels.
- [ ] Distinguish director phase from narrator completion. UTF-16 offsets: deduplicate deltas and fetch authoritative content if a gap occurs.
- [ ] Reload/foreground/network restore reads existing job; reconnect does not cancel/replay provider.
- [ ] Complete/current candidate only may commit. Next action first commits displayed complete candidate, refreshes head, then previews the next action.
- [ ] Incomplete/refused/truncated/stale candidates cannot auto-commit. Failure retains action/draft; incomplete draft editing follows the existing /draft contract; complete/committed candidates are immutable through that endpoint.
- [ ] Manual reading scroll/focus stays stable, composer does not cover last text;44px controls and IME safe.
- [ ] Tests count generation POST/provider attempts across lost response, reload, logout/re-login and stream completion; mock EOF is not completion.

### U7: Explicit local demo, PWA and browser acceptance

**Files:** backend/playroom/demo.py, project CLI entry, app static frontend wiring, frontend manifest/code-native icons, local startup docs/scripts and browser tests.
**Consumes:** accepted backend/U1–U6.
**Produces:** reproducible authenticated synthetic play loop on loopback with preserved demo data.

- [ ] Dedicated ignored DB/secrets directory; user-supplied or generated first-install owner password, no fixed shared password.
- [ ] Existing demo data survives restart. Bind127.0.0.1 by default; explicit demo can use HTTP secure_cookies=False.
- [ ] Normal production factory/secure cookies stay intact; fake mode is clearly labeled in CLI/UI.
- [ ] Serve built SPA/API same origin. Missing production configuration gives setup error, never synthetic narrative.
- [ ] PWA manifest/icons/standalone metadata; no private API caching or offline inference promise.
- [ ] Actual browser create campaign→preview→fake stream→commit→reload; counts and persisted transcript checked.
- [ ] Screenshot/layout evidence360/390/430 and desktop; real-phone install/keyboard trial recorded separately if unavailable.
- [ ] Sol runs frontend tests/typecheck/build, relevant backend suite and independent browser smoke. Keep usable local server/URL for the user.

## Long-play features after playable local gate

These tasks retain original Tasks5–8 contracts; do not fold them into a frontend scaffold task.

| Batch | Files / deliverable | Mandatory gate |
|---|---|---|
| L1 proposal schema/storage | consolidation.py, memory API, test_consolidation.py | Fabricated IDs rejected; typed source-grounded pending proposals; no approved mutation; refusal/incomplete not repaired |
| L2 bounded consolidation jobs | consolidation runtime, wire/cost/registry integration | Explicit action, role-specific budgets, shared slots/branch guard, queued vs dispatched recovery, exact source chunks, no hidden per-turn call |
| L3 review UI | memory proposal UI/tests | Correct/reject/approve old/new facts, promise supersession, exact summary coverage,75% suggestion without auto-call |
| L4 forks/reroll backend | timeline/context/memory/generation, branch tests | Same-turn checkpoint cutoffs; no abandoned future; global profile version collisions fixed; inherited order; uncommitted reroll vs committed fork |
| L5 branch UI | story navigation/candidate UI/tests | Visible branch/shared turn, historical snapshots unchanged,120-pair dual-outcome source assertions |
| L6 versioned JSON transfers | transfers.py/API/tests | schema1,20MiB pre-read bound, references validated before writes, transactional remap, secret exclusion, restorable export limit |
| L7 raw transcript import | transfers/consolidation/UI | Speaker/order preview, preserve original/partial history, chunk caps, manual playable checkpoint, no invented initial playrooom history |
| L8 SQLite backup/restore | transfers/startup/test_backup_restore.py | Backup API under open connection; validated new file; fresh epoch, revoked sessions, every restored job disabled including queued |
| L9 local packaging/CI | start.ps1/deploy templates/CI/docs | Reproducible local start, preserved DB, no visible helper consoles, locked Linux-compatible build; deploy workflow disabled |
| External hosted gate | Caddy/systemd/DNS and real phone/provider trial | Only after new user authorization/access; audit current VPS, separate wedding state, HTTPS/private session/20-turn quality/persistence checks |

For each future batch, extract its exact original task requirements into a small brief before delegation. Provide concrete test names/fixtures before coding; do not hand Luna this entire table as one implementation request.

## Handoff and reporting rule

Update [state](../../handoff/2026-10-13-state.md) after each accepted task with SHA, reviewed range, actual test output, explicit open findings and next task. Old “DONE” reports are not proof. Read original specifications for semantics; this continuation plan changes sequencing, not product requirements.

Current state: **B1–B6 accepted**. The user has now authorized continuing through the local playable product and integrated review. Execute U1–U7 in order, reviewing each accepted slice before consuming it in the next. Do not call a real model or deploy; the local explicit synthetic demo is the product gate in this worktree. Keep hosting, real-provider quality trials, and long-play acceptance open until separately authorized and actually tested.
