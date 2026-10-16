# Owner-local Live Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Give the owner one command to run the built Playroom frontend and real provider runtime locally with persistent data.

**Architecture:** A dedicated `playroom.live_local` assembly calls the existing real `create_app` factory, then serves the built frontend through a contained static/SPA router. The CLI forces `127.0.0.1`; only this assembly uses HTTP cookies. Existing demo, production defaults, provider verification, budget grants, import review and runtime recovery remain intact.

**Tech Stack:** Python 3.12+, FastAPI/Starlette FileResponse with a contained path resolver, Uvicorn, SQLite, existing React build, pytest and Playwright Chromium. No new runtime dependency.

**Spec:** [Issue #30](https://github.com/rua-den/playroom/issues/30), authorized continuation order in `docs/handoff/2026-10-16-codex-astra-transfer.md`.

## Global constraints

- User's current routing: Luna medium writes implementation/tests; Sol reviews and independently verifies. All shell commands use `rtk`.
- Bind `127.0.0.1` only; reject other `--host` values before starting or creating data. Explicit allowed Hosts override environment configuration.
- No startup probe, synthetic profile installation, automatic owner/password creation or printed secret. Existing explicitly authorized queued jobs retain the normal recovery contract; startup must not invent a new Send.
- No provider calls from import/review; verification remains existing read-only metadata. Real inference remains owner Send plus persisted grant.
- Automated acceptance uses synthetic Lan/Vy/Bình and fake provider overrides only. No private story, paid inference, public bind, phone, VPS or Caddy changes.
- USD 5 is an external maximum authorization, never a default grant or spending target. Default app budget remains unchanged.

## Task 1: Real local assembly, CLI and integration coverage

**Files:** Create `backend/playroom/live_local.py` and `backend/tests/test_live_local.py`; modify `pyproject.toml`, `uv.lock` only if lock metadata requires it, and `.gitignore` for `.playroom-live/`.

**Interface:** `create_live_local_app(data_dir: str | Path, *, frontend_dist: str | Path | None = None)` returns a FastAPI app. Default dist is repository `frontend/dist`; root contains `playroom.sqlite3` and `secrets/`. `main()` parses `--data-dir` (default `.playroom-live`), `--frontend-dist`, `--host` (default and only accepted value `127.0.0.1`), `--port` (default 8000). Entrypoint: `playroom-live-local = "playroom.live_local:main"`.

- [x] Add failing tests before creating the module, including this first contract:

```python
def test_missing_frontend_fails_before_creating_data(tmp_path):
    with pytest.raises(ValueError, match="frontend"):
        create_live_local_app(tmp_path / "data", frontend_dist=tmp_path / "missing")
    assert not (tmp_path / "data").exists()
```

- [x] Run `rtk proxy uv run --locked --extra test pytest backend/tests/test_live_local.py -q` and record actual RED.
- [x] Implement the minimal assembly: resolve/validate built index first, create persistent root, call existing `create_app` with DB/root, explicit `allowed_hosts={"127.0.0.1", "localhost"}` and `secure_cookies=False`. Omit provider/factory overrides so production's real default applies. Keep real create_app defaults untouched.
- [x] Serve assets safely using contained resolved paths and explicit symlink rejection (the final implementation uses FileResponse rather than StaticFiles). Unknown `/api` paths remain JSON 404; existing API/health routes take precedence. Valid client routes get index; traversal, absolute/encoded/backslash escapes and files outside dist never return outside contents. Missing build fails clearly before the worker starts.
- [x] Test CLI rejects alternate/public host and invalid port without Uvicorn; accepted call receives `host="127.0.0.1"`. Test real factory identity by default, no new provider invocation on a fresh startup, auth cookie on local HTTP, Host/Origin protection, API 404, safe static fallback, login/campaign/settings/credential persistence across restart and masked credentials. Reuse existing auth, credential and runtime tests/patterns rather than altering policy.
- [x] Run focused suite, full backend suite and compileall, then commit only owned files. Preserve any concurrent browser/docs work.

## Task 2: Chromium through the local-runner assembly

**Files:** Modify `backend/tests/browser_e2e.py` only. Consume the factory signature from Task 1; preserve existing seven-turn and import/review scenario.

- [x] Add a distinct browser scenario that calls the local factory, injects fake provider state strictly inside the test before lifespan, creates a synthetic owner/profile using existing helpers, and starts its real Uvicorn server. Task 1 captured the actual missing-module RED; browser development failures were selectors, as recorded honestly in the handoff.
- [x] In actual Chromium: load served React, authenticate, manually create a synthetic campaign, enter one action and Send through API/runtime, wait for one committed projected turn, reload and assert it persists. Assert one physical fake narration dispatch and no new automatic dispatch from reload/startup. Verify the real factory is the assembly default before test-only override.
- [x] Call this scenario from the existing script entrypoint so exact-SHA CI executes it automatically. No real credentials or provider network requests.
- [x] Run `rtk proxy uv run --locked --with playwright==1.56.0 python backend/tests/browser_e2e.py`, commit browser changes, and report first RED/final result. The final test commit also contains runtime test additions after a shared-checkout amend; final tree was independently reviewed with no lost code.

## Task 3: Owner instructions, independent review and release

**Files:** Parent owns README and `docs/handoff/2026-10-16-owner-local-live.md`, plus previous checkpoint evidence updates.

- [x] Document Windows setup: build frontend with locked dependencies, create `.playroom-live` once, use existing `playroom-owner create-owner --database-url .playroom-live/playroom.sqlite3 --email <owner email>` (getpass, no password argument), then `rtk proxy uv run --locked playroom-live-local --data-dir .playroom-live` and open `http://127.0.0.1:8000`. Explain provider setup, review approval, explicit small capped grant and manual Send.
- [x] State startup recovery may resume an already-authorized durable queued job; this is not a new automatic inference/probe. Keep live authenticated Gemma4 acceptance and private data approval separately tracked under #9.
- [x] Independent Sol review checks containment, runtime/default-provider wiring, loopback-only cookies/Host/Origin, persistence and test validity. Parent inspects diff and independently runs locked sync, full backend/frontend, typecheck/build, compileall, browser and whitespace checks.
- [x] Push feature branch, create and attach PR, require full CI on exact PR head, merge with expected head and verify exact merged-main CI. PR #32 head `2423856` and merged main `4f22646` both passed on attempt 1; exact URLs are in the runtime handoff. Preserve old dirty worktrees and user data.

## Self-review

All Issue #30 local-runtime requirements map to Tasks 1–3. Real Gemma4 inference is deliberately a subsequent #9 acceptance gate after code CI, with explicit persisted grant/preflight and no automatic retry. Existing account creation supplies the one-time setup path; the runtime itself stays one command. The plan does not add registration, a fake production fallback, deployment or any private-history import.
