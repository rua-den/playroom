# Task 3B report — durable generation worker

Status: implementation complete for the local/fake-provider runtime slice. The service reserves an immutable generation parent and branch guard in SQLite before provider work, keeps provider I/O outside transactions, and exposes the same state machine to the inline API and a process worker facade (`DurableGenerationWorker`).

Requirement map:

- Economy performs one narrator attempt; quality performs one native structured director attempt followed by one narrator attempt. `SelectionPlan` is schema validated and then checked against checkpoint, action hash, branch, approval, source IDs, scene IDs and reason citations. Director failure never calls narrator.
- Parent/settings/profile/credential snapshots and request hash are persisted. Same key returns the existing job; changed submitted payload/checkpoint/settings identity conflicts. Model/settings changes therefore do not rewrite an old job.
- `provider_attempts` persist queued/dispatched/completed/failed/interrupted status, profile/request/payload snapshots, usage, output and Unicode code point offsets. `generation_events` provides ordered phase/delta/failure/commit events. Content, event and owner/key lookup routes support reconnect without resubmission.
- Context runs persist final payload source IDs, omissions, budget and payload hash after quality selection. Actor dependencies and knowledge metadata are carried in the final message blocks. Deterministic preview remains provider-call free.
- Provider output requires a normal terminal `stop` result and nonempty text. Refusal, truncation, cancellation, missing terminal and schema errors retain drafts and never create history. Cancellation and restart recovery mark attempts interrupted and release the branch guard; stale candidates remain readable and cannot commit.
- Generation owns the branch guard through candidate commit. Effective profile, scene, memory, retrieval, checkpoint and transcript mutations now fail with `StateConflict` while the guard exists. Commit uses the timeline in-transaction helper and job status/guard removal in one transaction, so it is exactly once.
- Persistent execution epoch exists for Task 7 restore invalidation. Queued work is only runnable in the current epoch; dispatched work is never replayed by recovery. SQLite counts dispatched attempts against the global two-attempt limit.

Focused verification (GREEN):

```
rtk uv run --with pytest pytest -q backend/tests/test_generation.py backend/tests/test_generation_durable.py backend/tests/test_provider_contract.py
21 passed
rtk uv run --with pytest pytest -q
82 passed
```

Stable backend interfaces for frontend: `POST /api/campaigns/{campaign_id}/generate` (idempotent request), `GET /api/generation/jobs/{job_id}`, `GET /api/generation/jobs/{job_id}/content`, `GET /api/generation/jobs/{job_id}/events?after=N`, `GET /api/generation/jobs/by-key?branch_id=...&idempotency_key=...`, `POST /api/generation/jobs/{job_id}/cancel`, and `POST /api/generation/jobs/{job_id}/commit`. Job status, attempt details, snapshots, failures, draft and events are owner scoped.

The HTTP path reserves first and a shared `GenerationRuntime` owns a daemon worker connection; app lifespan starts/reaps it, while the direct service API remains synchronous for local tests. The runtime currently processes one queued job at a time (within the global two-attempt ceiling). Hard cancellation of a provider call whose Python generator is physically blocked needs an adapter-owned cancellation handle; the persisted timeout/guard state is ready, but no live network provider is used in tests. Authenticated SSE framing and session interval checks remain Task 4/8 work. Consolidation, import/export epoch invalidation and real provider trial remain later tasks.
