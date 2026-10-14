# Playroom — atomic cumulative paid-trial budget (Issue #10)

Status: **design / not implemented**  
Review date: 2026-10-14  
Source inspected: main `88b9753e326add94e92ec37ce09b1676ca5de74a`  
Related: [B4 trial readiness](../acceptance/2026-10-14-b4-live-trial-readiness.md), [Issue #9](https://github.com/rua-den/playroom/issues/9), [Issue #10](https://github.com/rua-den/playroom/issues/10)

## 1. Verified gap and desired invariant

Today `GenerationService.generate()` creates one immutable job inside `transaction(self.connection)`, calling `_reservation()` to reserve **the per-job estimated USD cap** before inserting `generation_jobs` and `provider_attempts`. `_check_dispatch()` recomputes the current request's stage allowance. Neither operation subtracts previously authorized jobs from a whole-trial limit. Consequently three jobs individually under USD 0.01 may consume more than USD 0.01 in aggregate.

**Invariant:** when the owner explicitly enters an authorized paid-trial mode, no *new paid provider attempt* may begin without a unique job-level reservation held atomically within the same trial's owner-approved cumulative remaining budget. The existing per-job cap remains a second, independent restriction.

A local reservation/cap cannot guarantee a vendor's final invoice when metering, tier pricing, or overage differs. UI must label internal amounts as *reservation/estimate*, provider-reported, calculated, or unknown. The provider dashboard is the external source of billing truth.

## Additional confirmed input-trust boundary: request-side policy and cap overrides

`backend/playroom/api/generation.py::GenerateRequest` accepts `mode`, `policy`, and `cap` from the POST body. Its route chooses submitted values over persisted owner settings. In `GenerationService.generate()` at the reservation lock, `submitted_identity` explicitly preserves non-null submitted values and overlays them on the persisted settings snapshot **before** `_reservation()`. As a result, a posted larger `cap` is currently checked against **itself**, not limited by the separately configured `confirmed_usd_cap`; a submitted `policy=capped_paid` can also override a stored `free_only` value. This does not imply any call already occurred: it is a **missing server-side authorization invariant**. The caller is session-authenticated, but client-side UI state does not constitute a durable trial spending grant.

**Mandatory first RED case:** owner setting `free_only` + paid Ollama narrator; valid authenticated client submits `policy=capped_paid`, `cap=100`; server must reject unless a distinct, active, owner-approved grant permits this exact model/scope and amount. Similarly, persisted per-send USD 0.01 + posted USD 100 must not authorize a job with a larger cap. A stale client from a previously approved trial must not use cached cap after the grant expires/is revoked. Do not conflate an explicit request field with independent spend consent.

Resolution belongs at the **server-side authoritative policy/budget authorization boundary**, not by hiding UI fields. Either prohibit overrides of persisted policy/cap entirely, or permit them only via a pinned, server-validated authorization and `min(server_per_send_cap, submitted_requested_cap, trial_remaining)`. Preserve idempotency hashing and fail closed on any cap/profile/settings mismatch. Re-run B1's definitive 409/422 recovery cases so new validation errors do not poison the Send key.

## 2. Owner decisions required by the feature

A trial authorization records **owner ID**, immutable trial ID, provider and pinned model/profile version, optional campaign scope, total approved USD, per-generation cap USD, maximum **new** jobs, UTC expiry, and explicit approval timestamp. Approval does **not** authorize direct live calls on its own; sending a turn must still be a deliberate user action. No automatic retries on uncertain completion.

- Positive total USD and per-send cap, finite decimal strings; reject floats/NaN/negative/empty, use `Decimal` or integer micro-USD (rounded conservatively upward, never down).
- `free_only` never binds a paid authorization or silently calls Ollama. Trial dispatch is explicitly `capped_paid`.
- A fresh grant gets a **new** trial ID; do not mutate old historical amounts or silently reset them on settings refresh, browser reload, branch switch or server restart.
- Expiration, pause, and revocation **block new reservations/dispatch**. They do not cause silent retry, delete a pending job, refund a dispatched attempt, or remove billing evidence.
- Pending or unknown provider attempts retain their reservation until a separately verified final bill or documented operator reconciliation. A failed call after dispatch may still incur charges.
- If a settled or externally discovered charge exceeds reserved cost, mark trial `overrun/suspended`, show the discrepancy, and reject new jobs. Do not pretend the local limit guaranteed vendor spend.

## 3. Proposed persistent model (additive migration only)

Use a **new forward-only** SQLite migration/versioned schema; never rewrite committed checkpoints, `owner_settings_versions` or `model_profile_versions`.

`paid_trial_authorizations`: `id PRIMARY KEY`, `owner_id REFERENCES owners`, scope/campaign ID if applicable, immutable provider/model/profile selector, `total_cap_usd TEXT`, `per_send_cap_usd TEXT`, `max_jobs INTEGER`, `approved_at TEXT`, `expires_at TEXT`, `state TEXT`, `revision INTEGER`, and optional parent grant ID for an explicitly new approval. Do not keep provider secrets here.

`paid_trial_reservations`: `job_id PRIMARY KEY REFERENCES generation_jobs`, `authorization_id REFERENCES paid_trial_authorizations`, `reserved_usd TEXT`, `provider_reported_usd TEXT NULL`, `settlement_status TEXT` (`reserved`, `reported`, `reconciled`, `unknown`), `created_at TEXT`, `settled_at TEXT NULL`. Unique job IDs ensure recover/replay cannot charge the trial twice.

Retain the original job ledger (`reserved_cost_json`): the trial ledger **references** its job rather than replacing stage records. Provider usage/cost may arrive late. Add indexes on `authorization_id`, `owner_id`, `created_at` and ensure all reads are owner scoped.

**Accounting:** reserve the conservative cost of all planned stages; reduce reservation only when a verified final amount is available, never merely because a job has status `failed` or a client disconnected. If the server cannot prove an attempt was **never dispatched**, do not release its held budget automatically. An item may become `reconciled` only with explicit evidence and auditable reason.

## 4. Reservation flow and transaction boundary

1. Authenticate owner, check current campaign/branch/checkpoint, immutable model role and `policy=capped_paid`. Resolve an **active** trial authorization from a server-side binding, not from a client-controlled total or arbitrary authorization ID.
2. Before any provider invocation, inside the **same** existing SQLite `BEGIN IMMEDIATE` transaction in `GenerationService.generate()`:
   - Query existing `(owner_id, branch_id, operation, idempotency_key)` first. An identical retry returns the **same** job and reservation; a mismatched request conflicts.
   - Recheck authorization state/expiry/model/campaign scope and number of reserved **distinct** jobs.
   - Call existing `_reservation()` using immutable pricing/profile/budgets and compute conservative required USD; check **both** per-send and remaining cumulative USD.
   - Remaining = approved total minus sum of held reservations and verified settled amounts for this trial. Sum exact decimal strings; never use `REAL` floating-point accumulation.
   - Insert one job, planned stage attempts, branch guard and matching `paid_trial_reservations` row. Commit all together, otherwise roll back **all**.
3. At `_check_dispatch()`, verify a real matching trial reservation and permission to dispatch, after any context/size adjustments. If the final wire exceeds the authorized amount, do not expand without a new atomic reservation decision and ceiling recheck.
4. Record reported cost/usage and uncertain failure in the same durable database, preserving the original idempotency key. No refund on `5xx`, network reset, worker restart or `MISSING_TERMINAL` after dispatch.
5. A fresh explicit Send requires its own reservation. Reconnect, polling, candidate commit, reloaded browser and by-key lookup **must not** create or debit a second reservation.
6. If the application sees the exact provider-side final billed cost, settle conservatively; otherwise retain the reserved estimate and label reported/calculated/unknown distinctly. Any manual release has immutable audit metadata.

Multiple branches and workers must use `BEGIN IMMEDIATE` and the same owner/trial ledger so concurrency cannot double-spend. Do not use only localStorage, an in-process lock, frontend arithmetic, or a separate non-atomic write after `generation_jobs` insertion.

## 5. Runtime/UI contract

In `SettingsPanel`, show separately:

- **Maximum per generation** (existing `confirmed_usd_cap`).
- **Approved total for this trial** (new authorization).
- **Already reserved/settled, remaining, job count and trial expiry**; a clear status for unknown charges.

Use clear Vietnamese warnings: `Giới hạn này là dự toán nội bộ, không bảo đảm hóa đơn của nhà cung cấp.` Require a deliberate owner confirmation to create/expand a paid grant; adding a credential or switching model is *not* consent to paid dispatch.

Expose read-only trial usage for the owner; authorization changes must be authenticated and protected by the application's existing same-origin guard. No billing secret, complete prompt, private canon or raw provider token in issues, logs, reports or telemetry.

For B4 manual trial, restrict trial to the user's approved count of **explicit** Sends with a synthetic campaign. An owner-explicit gate is still mandatory even after the feature passes CI.

## 6. RED-first acceptance tests (no paid provider calls)

| Test | Expected result |
| --- | --- |
| Three jobs each individually under per-turn cap, cumulative third would exceed total | Reject third **before** provider dispatch and persist no third job/branch guard |
| Two different branches reserve concurrently and together exceed balance | Exactly one job reserved; other rejected atomically; no double debit |
| Same idempotency key/payload submitted after lost POST response | Same job ID and **one** `paid_trial_reservations` row; one upstream invocation |
| Same key with changed action/checkpoint | 409; no additional debit |
| Provider timeout/503/unknown status after dispatch, then reconnect/restart | Held budget remains; no new paid retry |
| Cancel before provider dispatch, with reliable DB proof of no dispatch | Eligible for audited reservation release; otherwise hold until reconciliation |
| Missing or malformed USD cap, no trial, expired/revoked grant, wrong model/campaign/owner | Fail closed before reservation/provider call |
| Profile reverify/change, settings update, page reload | No reset of consumed trial allowance and no impersonation or silent extension |
| Reported USD exceeds estimate / final unknown | Suspend new sends on overrun; keep unknown reserved |
| Free-only policy + paid Ollama profile | Reject before dispatch; no paid fallback |
| Full B1/B2/B3 regressions | No change to replay/JSON attribution/Chromium synthetic test behavior |

Run focused budget tests and backend full suite, frontend tests/typecheck/build, browser synthetic suite and GitHub CI at **exact PR SHA**, followed by green merge-head CI. Record observed RED before writing production code; never infer it from test names.

## 7. Implementation gate and rollout

1. **Luna coding route:** `AGENTS.md` still requires `gpt-5.6-luna` for Issue #10; prior direct-coding exceptions were issue-specific. No code edit is authorized by this planning document.
2. Use new feature branch, isolated migration and explicit API/UI changes. Review diff independently, verify all tests, then merge; never directly write unverified billing code to `main`.
3. If old paid settings exist, do not silently attach them to an unlimited trial. Clearly distinguish non-trial legacy operation from opt-in guarded trial and fail closed when B4 marks a guarded trial required.
4. Do not run live Ollama completion, verify a real credential, copy the user's private Henn canon, or edit VPS/Caddy under this design task. Actual B4 live acceptance remains [Issue #9](https://github.com/rua-den/playroom/issues/9) and requires separate owner-supplied limits and authorization.

## Current evidence and status

Read-only source audit of `backend/playroom/generation.py`, `wire_cost.py`, `model_profiles.py`, `db.py`, and `001_initial.sql` confirms the missing cross-job reservation. Existing fake/real-Chromium CI verifies earlier B1–B3 functionality, **not** this new aggregate accounting contract.

**Design review ready; implementation/test/merge not started; B4 NOT PASS.**
