# Owner-local live runtime checkpoint — 16 October 2026

## Verified base and scope

Implementation starts from main `3e9d23a711b59f379e1728e94900175102a4dad2`, the merged [PR #31](https://github.com/rua-den/playroom/pull/31). Exact PR [CI #38877304945](https://github.com/rua-den/playroom/actions/runs/38877304945) and merged-main [CI #38877460660](https://github.com/rua-den/playroom/actions/runs/38877460660) passed all backend/frontend/Chromium jobs on attempt 1. Prior PR #28 main attempt-1 failure remains recorded in the [reconnect handoff](2026-10-16-reconnect-race.md); #20 remains open for its older lost-POST failure.

[Issue #30](https://github.com/rua-den/playroom/issues/30) provides a persistent, forced-loopback runtime using the existing real provider factory. It serves the built React app and API on one origin. It does not create an owner password, provider configuration, trial grant or inference at startup. Existing authorized durable jobs retain normal recovery behavior across restart; launching a runner can resume already-queued authorized work, but does not invent a fresh Send or retry an ambiguous dispatched attempt.

The implementation plan is [owner-local live runner](../superpowers/plans/2026-10-16-owner-local-live.md). User's current chat routing requires Luna medium implementation and separate Sol review/verification, superseding historical Astra routing in repository prose.

## Windows owner setup

Run from the repository root. Build the frontend once (and rebuild after frontend updates):

```powershell
rtk proxy uv sync --locked --extra test
rtk proxy npm --prefix frontend ci
rtk proxy npm --prefix frontend run build
```

Create the owner once, replacing the example email with the login email you want. The existing CLI creates the database directory and asks for a password and confirmation through hidden input; no password belongs in the command:

```powershell
rtk proxy uv run --locked playroom-owner create-owner --database-url .playroom-live/playroom.sqlite3 --email owner@example.test
```

Start the app each time with one command:

```powershell
rtk proxy uv run --locked playroom-live-local --data-dir .playroom-live
```

Open `http://127.0.0.1:8000` and log in. `.playroom-live/` stores the SQLite database and credential files; keep it private and back it up as owner data. Stop the foreground server with Ctrl+C. Reuse the same data directory on the next start. An alternate port is available through `--port`; a public or alternate host is rejected. A missing frontend build fails clearly before serving or creating the data directory. Existing `playroom-demo` remains a separate synthetic runtime.

New roots request POSIX mode `0700`; existing directory permissions are retained, including a directory already created by owner setup. Windows ACLs are not certified by POSIX mode tests. Use a dedicated owner-controlled directory, with the credential subtree retaining the existing CredentialStore permission handling.

Use the provider settings UI to enter your own credential, verify the model metadata and select the roles/mode. Verification is a read-only metadata step; it does not generate a story. Create a synthetic Lan/Vy/Bình campaign or import a selected JSON conversation. Imported state stays locked until you separately review/approve its checkpoint. Configure a small explicit capped-paid trial grant through the existing product controls when required, then manually Send an action. The previously authorized USD 5 maximum is not a product default or a spending target, and local estimates do not enforce the provider's invoice.

No automated test sends private Henn/BANGTAN content. Import/review does not itself authorize sending private source to a provider. The owner keeps exclusive control of their player character; neither an importer nor narrator may manufacture missing historical chapters or a next action.

## Verification and release status

Implementation on `feat/issue30-live-local` is locally verified. Runtime code is in `c3638ac`, browser/persistence coverage in `99b9b03`, final containment hardening in `04144ff`, and a whitespace-only test cleanup in `f10665f`. The local router uses contained resolved file paths and explicit symlink rejection, with API 404 and SPA fallback; no shared demo or production factory defaults were changed and no runtime dependencies were added.

- First feature RED: focused test collection failed because `playroom.live_local` did not yet exist. The first browser development failures were copied/mojibake and malformed selectors; these were **test harness defects**, not production regression evidence. The browser harness was corrected and its fake provider explicitly replaces the real factory only inside the test.
- Independent review found data/credential path aliases into frontend, unsafe index symlink handling, permissive new-root modes and missing persistence coverage. Final fixes validate actual DB/credential paths, validate index on every fallback and set private modes only on newly created roots. Review at `04144ff`: no remaining blockers.
- Parent final Windows full backend: **333 passed / 1 skipped in 62.88 seconds**. The skip is the POSIX-mode-only test; symlink tests actually ran on this host. Focused runtime suite independently reviewed: **13 passed / 1 expected Windows skip**. On POSIX CI the mode test must run.
- Parent frontend: **102 passed / 3 skipped**, typecheck/build passed. Locked dependency sync, installed CLI `--help`, compileall and raw full-range `git diff --check` passed. The raw check caught and then verified cleanup of an extra EOF blank line hidden by RTK's filtered output.
- Parent Chromium at final production code: existing seven-turn reconnect/409/422/refresh/IME/mobile plus selected ChatGPT import/review **PASS**; new live-local assembly login/create/manual fake Send/commit/reload scenario **PASS** with exactly one fake dispatch.
- Existing owner/campaign/provider-settings/masked credentials persist across app recreation/restart. Fresh startup does not call the provider factory, API Host/Origin checks remain active, production secure cookies remain true, missing build fails before data creation, and public host/invalid port cannot reach Uvicorn.

### Remote release evidence

[PR #32](https://github.com/rua-den/playroom/pull/32) merged as `4f22646c3ea2a9d2efa410921c0eedfb836fbcb7`. Exact PR head `24238565377379ae597c536d8040efb39d67b7a6` passed [CI #38879140287](https://github.com/rua-den/playroom/actions/runs/38879140287) on **attempt 1**, all backend/frontend/Chromium jobs. Its Linux backend log confirms **334 passed** (the POSIX mode test ran).

Exact merged-main [CI #38879429397](https://github.com/rua-den/playroom/actions/runs/38879429397) passed on **attempt 1**, all backend/frontend/Chromium jobs, at `4f22646c3ea2a9d2efa410921c0eedfb836fbcb7`. Subsequent release-evidence documentation changes do not claim a separate code-test run at their own SHA.

Chromium acceptance uses a test-only fake provider override through the real local-runner assembly; it is not real Gemma4 acceptance. No owner credential was created by this work and no real inference, private content transmission, physical device or infrastructure change occurred.

Remaining work follows the latest handoff: #29 legacy bundle, remaining #27 ZIP/long source and #9 full authenticated live Gemma4/device/deployment acceptance. Real app inference needs the existing explicit grant/preflight discipline and synthetic content; physical phone and VPS/Caddy/DNS changes retain their separate authorization boundaries.

The private legacy bundle's full nested schema is not in this repository. The current chat requested its local path so the importer can be designed from the actual structure without publishing private content. Until that is available, do not manufacture a schema from the public top-level field list, historical turns from summaries, or an automatic next chapter.
