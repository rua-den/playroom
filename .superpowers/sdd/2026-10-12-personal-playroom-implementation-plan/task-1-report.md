# Task 1 implementation report

## Result

Implemented private owner authentication, campaign/profile storage, immutable checkpointed state, memory proposal/review/tombstone storage, scene versions, retrieval policy, and owner-scoped API foundations. Runtime code lives under `backend/playroom`; the initial migration is packaged with the application. No external provider, deployment, or push operation was performed.

## TDD evidence

- RED: `rtk proxy uv run --locked --extra test pytest backend/tests/test_campaign_storage.py backend/tests/test_memory_versions.py backend/tests/test_auth.py -q` failed collection because the required production modules did not exist.
- RED: `rtk proxy uv run --locked --extra test pytest backend/tests/test_auth.py::test_competing_profile_writes_serialize_and_leave_one_checkpoint -q` exposed shared-connection transaction overlap (`cannot start a transaction within a transaction`).
- GREEN after per-request connections: the concurrency regression passed; competing clients result in one committed update and one stale-state conflict.
- Final GREEN: `rtk proxy uv run --locked --extra test pytest backend/tests -q` — **17 passed**.

## Runtime and interfaces

- Python 3.14.3, uv 0.8.15; `requires-python = ">=3.12"`; `uv.lock` pins a verified Python 3.14-compatible dependency set.
- Run through an application factory: `uv run uvicorn --factory playroom.app:create_app`. The app has no module-global instance or import-time DB creation.
- Provision the first owner out-of-band with `uv run playroom-owner create-owner --database-url <sqlite-url> --email <email>`; password is entered through `getpass`, and the CLI creates no default credentials.
- Storage functions expose campaign/profile versioning, branch heads/checkpoints, committed revisions and selected lineage, append/list/review/tombstone memory, dedicated scene state, and retrieval policy. Route dependencies use a new SQLite connection per request; in-memory app tests use a shared-cache URI with a keeper connection.
- Pending memory proposals have their own immutable checkpoint membership map. An AI replacement does not replace the approved effective version until a human approves it; rejection preserves the current approved version. Each version records its own effective checkpoint cursor, while reads return a separate requested cursor.
- Origins/hosts are normalized and rejected for malformed values. Authentication sessions are stored by hash, revocable, HTTP-only and same-site cookies; auth routes use uniform login rejection and configurable throttling. Current route inventory tests cover mounted routes only.

## Review notes

- Checkpoint membership is immutable and source revisions are validated against committed selected revisions on the branch lineage. Campaign reads/mutations are owner-scoped at API boundaries; storage APIs consistently take campaign/branch identity.
- The migration includes schema foundations for later generation and provider work, but no context, streaming, or export feature routes were stubbed.
- Please review API error mapping and migration shape before downstream routers depend on these interfaces. SQLite remains a single-instance store; transactional writes are serialized by SQLite `BEGIN IMMEDIATE` and independently connected per request.
