# Historical Task3B final scoped review

Reviewed range: 30c84e1..e6a6c04. The newer c2803d6/260eb2e/a35a2a6 changes partially address this report but have not passed an integrated review. Use [current handoff](../../handoff/2026-10-13-state.md) for current work; this is evidence/history, not a fresh acceptance verdict.

### Spec Compliance

- ❌ **Issues found.** Fix round 5 closes the lazy-stream ordering bug, final omission/dependency packing, honest cost provenance, default-budget/profile-binding regressions, and the stale test-count report. It does not close the director lifecycle for a narrator-packing failure, the economy old-writer atomicity boundary, or the complete mandatory local HTTP/runtime matrix.
- ⚠️ **Scoped boundary.** This review re-read only the named C1/C2/C4/I5 contracts and the six carried fix4 findings. Earlier resolved C3/C5/I1/I2/I3/I4/competing-guard findings were not reopened. The packaged diff was read once; narrow reads of changed functions/tests were used where the package display was cut off mid-function.

### Named Finding Resolution

1. **Critical — atomic director completion: NOT ADDRESSED.** The normal quality success path now puts usage, `ContextRun`, attempt completion, and `context_completed` in one transaction (`backend/playroom/generation.py:646-659`), and the new success assertions prove completed context/narration rows and no capacity leak (`backend/tests/test_generation_durable.py:79-110`). However, `_narrator_request` runs at line 637 before that transaction. A required final narrator-wire overflow raises at lines 476-479 after the director has already been physically called at lines 580-630. `run()` then calls `_fail`, which interrupts only `queued`/`claimed` attempts, not the still-`dispatched` director (`backend/playroom/generation.py:337-345,968-978`). This leaves false attempt accounting and consumes persistent global capacity. Preflight the exact required narrator base before director inference, or otherwise ensure every post-result failure durably completes/interrupts the director without weakening the required-overflow-zero-calls rule; add that regression.
2. **Critical — lazy physical gate: ADDRESSED.** The registry checks the durable gate immediately before every explicit `next(iterator)` (`backend/playroom/attempt_runtime.py:107-125`), and the regression makes the third gate fail after iterator creation while proving the pre-yield side effect never runs (`backend/tests/test_generation_fix4.py:90-112`). The OpenRouter cancellation boundary is separately covered before mocked client stream opening (`backend/tests/test_generation_fix4.py:115-146`).
3. **Critical — omission fitting/shared actor dependencies: ADDRESSED.** Director trials now count the evolving omission list and re-trim until the final wire fits (`backend/playroom/generation.py:401-432`). Selected memories collect every actor dependency in `required_by_memory_ids`, and narrator fitting retains a shared profile while any referenced memory remains (`backend/playroom/generation.py:728-751,483-523`). The focused regressions exercise both the shared-actor drop case and omission-heavy final director wire (`backend/tests/test_generation_fix4.py:149-205`).
4. **Important — cost provenance: ADDRESSED for implementation.** Provider-reported billing, locally calculated price-times-usage, reservation estimates, and unknown usage now occupy separate fields; `actual_cost_usd` is populated only from provider billing and aggregate actual remains unknown unless every stage reports it (`backend/playroom/generation.py:918-959`; `backend/playroom/wire_cost.py:121-175`). Tests cover calculated-only stages, provider-reported director billing, unknown narrator usage, distinct role pricing, retained estimates, and remaining allowance (`backend/tests/test_generation_fix4.py:208-322`). The mandatory threshold evidence remains incomplete under C2 below.
5. **Important — local runtime/HTTP matrix: NOT ADDRESSED.** The new loopback tests materially improve coverage: lost initial response is parameterized across economy/quality with exact stage counts (`backend/tests/test_generation_durable.py:289-330`), and active SSE disconnect, Unicode resume, and live session revocation are exercised (`backend/tests/test_generation_durable.py:834-1007`). The active disconnect and revoke cases are economy-only, so there is still no quality disconnect during director, after director completion, and during narration with exact non-replay counts. The only zero-row test monkeypatches a direct `GenerationService` claim rather than exercising the required real-app cancellation race (`backend/tests/test_generation_durable.py:631-640`). The repository still has one competing-guard commit assertion rather than a full queued/running inventory of effective story mutations (`backend/tests/test_generation_durable.py:543-550`). These are explicitly mandatory mocked/local cases (`task-3b-fix4-integration-brief.md:12`; `task-3b-brief.md:21`), not live-provider work.
6. **Important — reported test evidence: ADDRESSED.** The report now says eight fix4 tests, 31 durable tests, five selected loopback cases, one binding regression, and 125 full-suite tests (`task-3b-report.md:201-221`), matching the reviewed test definitions and the controller's independent `125 passed in 22.36s`, compile success, and clean whitespace check.

### Carried Contract Status

- **C1 — NOT ADDRESSED.** Final selection packing and source/omission metadata are substantially repaired, but required narrator overflow is discovered only after the quality director call (`backend/playroom/generation.py:580-637`). This violates the specified zero-inference required-overflow boundary (`task-3b-wire-cost-next-brief.md:9,18`) and triggers the leaked-dispatch defect above. The current wire test only checks that persisted narrator message arrays are nonempty (`backend/tests/test_generation_fix4.py:252-254`); it does not compare the exact adapter-emitted payload/hash/count to `ContextRun`.
- **C2 — NOT ADDRESSED as an acceptance gate; implementation substantially addressed.** Defaults, role-specific accounting, aggregate/remaining checks, and provenance are present (`backend/playroom/wire_cost.py:18-72,117-175`; `backend/playroom/generation.py:666-702,918-959,1075-1084`). The required regressions still do not test a fractional aggregate cap rejection before call one, an expensive known director exhausting remaining narrator allowance, or unknown director usage retaining the reservation. Both added paid flows use cap `1` and succeed (`backend/tests/test_generation_fix4.py:239-251,299-322`), while the brief explicitly mandates these threshold cases (`task-3b-wire-cost-next-brief.md:20`).
- **C4 — NOT ADDRESSED.** The post-slot/lazy invocation boundary is fixed, but economy `_save_context_run` is still outside a transaction (`backend/playroom/generation.py:661-664`). SQLite is autocommit (`backend/playroom/db.py:31-40`), so `_save_context_run` commits its `context_runs` insert before checking the guarded `generation_jobs` update (`backend/playroom/generation.py:779-798`). If recovery/cancel changes the epoch between those statements, the CAS fails but the stale old worker has already persisted a `ContextRun`; quality avoids this only because it wraps the same helper in the transaction at lines 652-659. Put the insert/update under one transaction/CAS boundary for economy and add a recovery/cancel race proving no stale context row survives.
- **I5 — NOT ADDRESSED.** See named finding 5: the added five loopback cases cover useful slices, not the mandated both-mode/each-phase disconnect, real-app zero-row, and full mutation inventory matrix.

### Additional Configuration Checks

- **Default 12,000 preview budget: ADDRESSED.** `normalized_budget` uses the 12,000 configured-input default even when the verified context window is larger (`backend/playroom/wire_cost.py:18-21,53-69`), and the owned-preview regressions assert 12,000 (`backend/tests/test_context_selection.py:204-233,236-270`).
- **Narrator-only economy preview: ADDRESSED.** Economy explicitly resolves the narrator binding while quality may resolve context (`backend/playroom/api/context.py:32-45`), with an HTTP regression at `backend/tests/test_context_selection.py:236-270`.
- **Budget-only update preserves profile v1: ADDRESSED.** Omitted role IDs retain the prior immutable version while explicit IDs select latest (`backend/playroom/api/configuration.py:87-124`); the v1/v2 HTTP regression verifies the exact v1 id/version/hash is preserved (`backend/tests/test_model_switch.py:91-141`).

### Strengths

- The explicit `next(iterator)` loop places the durable decision at the true lazy network boundary and is backed by a regression that would fail under the old `for` ordering (`backend/playroom/attempt_runtime.py:107-125`; `backend/tests/test_generation_fix4.py:90-112`).
- Cost fields no longer call locally calculated usage billing “actual,” and conservative estimates remain available when provider usage is absent (`backend/playroom/generation.py:926-959`; `backend/tests/test_generation_fix4.py:257-322`).
- The loopback Uvicorn tests exercise real HTTP socket loss, incremental SSE framing, cursor resume, Unicode/astral content, and active session revocation without upstream calls (`backend/tests/test_generation_durable.py:289-330,834-1007`).

### Issues

#### Critical (Must Fix)

1. **Complete or avoid the director before narrator required-wire failure.** `backend/playroom/generation.py:580-659,968-978` can leave a successful director `dispatched` forever when `_narrator_request` raises. Validate the exact required narrator wire before stage one and add a zero-provider-call overflow test; retain an atomic completion fallback for any other post-director packing error.
2. **Make economy `ContextRun` plus final-context CAS atomic.** `backend/playroom/generation.py:661-664,779-798` autocommits the insert before its epoch/status CAS. Wrap both writes in one transaction and prove restart/cancel cannot leave an old-writer context row.

#### Important (Should Fix)

1. **Finish the mandatory local HTTP/runtime matrix.** Add quality active disconnects at director, after completed director, and during narration; a real-app zero-row cancellation race; and a queued/running inventory test for every effective story mutation (`task-3b-fix4-integration-brief.md:12`; current partial cases at `backend/tests/test_generation_durable.py:289-330,631-640,895-1007`).
2. **Add the required C1/C2 boundary proofs.** Compare emitted adapter wire/hash/count to the persisted `ContextRun`, prove required overflow causes zero calls, and test fractional aggregate rejection, remaining-cap rejection after known director cost, and unknown director usage reservation (`task-3b-wire-cost-next-brief.md:15-21`; current success-only paid tests at `backend/tests/test_generation_fix4.py:208-322`).

#### Minor (Nice to Have)

None.

### Checks

- Did not rerun the full or focused suites. The controller independently verified `125 passed in 22.36s`, compile success, and exact-range whitespace clean at `e6a6c04`.
- No implementation edit, subagent, provider/network call, key, paid/free inference, VPS action, or git command was used. The only written file is this required review report.

### Assessment

**Task quality:** Needs fixes

**Reasoning:** The fix resolves several difficult happy-path contracts and adds meaningful local HTTP coverage. The remaining post-director failure leak and non-atomic economy context write are durable correctness defects, and the explicitly mandated HTTP and wire/cost boundary matrix is still incomplete.
