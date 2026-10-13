# Task3 implementation snapshot — acceptance open

Current authoritative status: [handoff](../../handoff/2026-10-13-state.md). Next work: [resume plan](2026-10-13-playroom-resume-plan.md), B1 only.

At code snapshot a35a2a6, independent backend verification returned 135 passed in 69.53s; compile and exact-range whitespace checks passed. This does not establish full Task3 compliance. Some new TestClient disconnect tests do not prove their named phase, the real cancellation race/guard inventory remain open, and post-director usage writes need atomicity verification. Frontend/demo/live inference/VPS are absent.

## Current interfaces

- Auth: POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me.
- Provider: POST/GET /api/provider/credentials (masked read), GET /api/provider/profiles, POST /api/provider/profiles/verify, GET/PUT /api/provider/settings.
- Context: POST /api/campaigns/{campaign_id}/context/previews; GET /api/context/previews/{preview_id}.
- Generate: POST /api/campaigns/{campaign_id}/generate with branch_id, action, idempotency_key, checkpoint_id, optional preview_id/mode/policy/cap.
- Read/recover: GET /api/generation/jobs/by-key?branch_id=...&idempotency_key=...; GET /api/generation/jobs/{job_id}; /content; /events?after=...; /events/stream?after=....
- Actions: POST /api/generation/jobs/{job_id}/cancel; PUT .../draft for incomplete drafts; POST .../commit for complete current candidates. Complete/committed candidates are not editable through the draft endpoint.
- Server contracts live in API source; read actual response types before writing a frontend client.

Settings save immutable roles {id,version,profile_hash}, settings_revision/hash, mode economy/quality, policy free_only/capped_paid, confirmed_usd_cap and per-role budgets {input_limit,requested_output,wrapper_buffer}. Explicit model switches choose a newer verified version; budget-only changes retain bindings. Context preview can use narrator-only economy.

Job metadata includes attempt_counts/by_stage/details, settings/profile snapshots, draft/failure, cost_ledger and remaining_cost_usd. Cost entries separate provider_reported_cost_usd, calculated_cost_usd, estimated_cost_usd and unknown status. ContextRun persists exact prepared wire/request/hash/counter metadata; real adapter equality still needs the independent proof in B5. Events/content use UTF-16 code-unit offsets.

## Internal modules

provider.py contains ProviderAdapter/FakeProvider/OpenRouterAdapter/default_provider_factory. attempt_runtime.py owns shared physical slots/deadline/cancel/lazy invocation gates. wire_cost.py builds/counts canonical provider payloads and costs. generation.py handles persisted jobs, attempts, context and commit. No additional providers directory is currently required.

## Evidence and limitations

Storage/context and scoped provider/profile stages were reviewed. The [historical final Stage3B review](../reviews/2026-10-13-runtime-open-findings.md) explains defects found before the newer Task3C commits. The current handoff distinguishes repaired paths, unreviewed changes and invalid/incomplete proof setups.

No actual provider key or upstream inference was used. Model availability/pricing references are candidates, not selected defaults or live quality results. Full Task3 acceptance requires B1–B6; no report in ignored scratch can waive them.
