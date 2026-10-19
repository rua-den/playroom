# Owner-test local product — 18 October 2026

## Intent and boundary

Owner requested a concrete product to test, after the [ZIP checkpoint](2026-10-18-chatgpt-zip.md). Starting main `9869a57`; reuse isolated `playroom-import-followup` on `feat/local-test-product-20261018`. Current chat routing: Luna medium implements, Sol reviews; root independently verifies.

This bounded checkpoint packages the existing application for Windows: `Start Playroom.cmd` builds locked dependencies and starts the persistent real loopback app with first-owner CLI setup; `Try Playroom Demo.cmd` starts the separate explicit fake-provider demo. Browser opening waits for this server to start. No registration HTTP endpoint, default real password, provider grant or fresh inference is created by live startup.

The owner chooses their real account password through hidden console input. Existing owner credentials must not be prompted for or reset. Real data remains in `.playroom-live/`, demo data in `.playroom-demo/`; both are ignored. Importing the private Legacy bundle locally does not approve its canon/checkpoint or provider data consent. Those decisions remain with the owner in the UI.

## Delivery ledger

- [x] Baseline latest main fetched; primary untracked `playroom/` and private `data/` preserved.
- [x] Primary baseline locked install/build; demo started on loopback 8001; root signed in, created a synthetic campaign and committed one explicit fake Send through the visible UI.
- [x] Initial launcher implementation by Luna at `237a72b`.
- [x] Meaningful readiness/failure lifecycle verification and independent review at `8b8c311`.
- [x] Parent full checks, exact launcher PR and merged-code CI.
- [x] Windows launcher smoke, private local pending import and owner-facing quick start.
- [x] Owner-authorized synthetic real-AI app verification using the existing GitHub Actions credential; first trial failed, separately corrected-fixture verification passed.

## Known scope

This delivers a local Windows test build. The existing real provider settings and spending controls remain; owner supplies credentials in the local app and explicitly Sends to test real narration there. After the initial scope, the owner explicitly authorized using their saved GitHub key to try real AI. Add one bounded synthetic authenticated-app trial on protected main, with existing credit-source/preflight/grant checks, at most one provider POST and no retries. Keep the credential inside Actions; do not retrieve or copy it to the local app. No private bundle transmission, physical phone, public port, VPS/Caddy/DNS or purchased-credit test is authorized. #27 durable chunk/resume and real-export compatibility remain follow-up work, not prerequisites for the already-supported local Legacy test.

See [owner quick start](../../BAT-DAU.md). Record verification and release evidence below after actual results.

## Review and local preparation

Initial Sol review through `1d2ad25` found first-owner creation was not atomic for two distinct emails, indefinite thread join was unsuitable for Ctrl+C on supported older Windows Python versions, server errors could be swallowed, and the demo CLI's changed default conflicted with existing docs. The initial readiness test only mocked delegation; later real-server tests covered readiness/occupied port but the alleged startup-failure test duplicated occupied port. These findings are being fixed before release; do not present the initial tests as proof of those cases.

Private local demo preparation used only the authenticated loopback import path, retained one idempotent imported source and preserved the synthetic sample campaign. Technical checks: review required, approval absent, provider-data consent absent, zero historical turns, pending source-derived memories, unchanged source hash and matching canonical archive hash. No private text, title or IDs were emitted to model logs or GitHub; no private campaign generation job/provider attempt exists. The temporary operational script was removed. Owner review remains pending by design.

Parent frontend at the unchanged UI: **136 passed / 3 skipped**, typecheck/build passed, locked install audit zero vulnerabilities. Root's visible UI test logged in to the separate demo, created the synthetic sample, explicitly clicked Send and observed the committed fixed narration; this is fake-provider functionality, not real model quality acceptance.

At final launcher code `8b8c311`, parent full backend **367 passed / 1 expected Windows POSIX-only skip**; full locked Chromium **PASS** for synthetic import/review/recovery and live-local assembly. Initial `252c9c1` passed the earlier full suite but had a lifecycle defect: its shutdown helper also limited normal serving to five seconds. The new real-server longevity regression actually failed there after six seconds, then passed after normal wait and bounded cleanup were separated. Do not call the earlier test pass sufficient lifecycle proof. Final real-AI harness review/checks and remote release evidence remain pending.

## Continuation — 19 October 2026

Deliver the reviewed Windows launcher independently on `feat/windows-local-test-20261019`, based on `8b8c311`, while the one-shot AI harness is repaired on `feat/local-test-product-20261018`. The initial harness at `45422ed` has only superficial offline checks and known API-contract errors; **it has not been pushed, merged or run with a real credential**. Do not trigger it until actual offline API/adapter integration and safety review pass. No live model POST has occurred in this checkpoint.

The local demo was restarted on loopback 8001 after the previous session ended. Its persistent source/campaigns remain separate from live data. Final Windows smoke, exact launcher PR/merged-code CI and release links will be recorded after verification.

## Released Windows product

[PR #40](https://github.com/rua-den/playroom/pull/40) final head `66d3344e58688bbb83e117d37060139ac58b0fbd` passed [CI #39189856947 attempt 1](https://github.com/rua-den/playroom/actions/runs/39189856947): **368 Linux backend**, **136 frontend / 3 skipped**, build/typecheck/compile and both Chromium flows. Merged code `e598e3f965c136db3966ccb538303dfc8325393e` passed the same full checks in [CI #39190075223 attempt 1](https://github.com/rua-den/playroom/actions/runs/39190075223). Parent fetched main and verified the complete merge tree equals the reviewed PR head.

Actual Windows smoke invoked the shared `scripts/Start-Playroom.ps1 -Mode Demo`: locked dependency installation, frontend build, server readiness, browser opening and sustained health all passed. An earlier shell invocation of the `.cmd` wrapper had a caller quoting error; the shared script succeeded and the six-line wrapper's quoting was independently reviewed. No new app defect is inferred from that caller error.

The owner has two verified Desktop shortcuts, **Playroom - Local Test** and **Playroom - Demo**, targeting the primary checkout's launchers. Demo is running on `http://127.0.0.1:8001`; the real launcher uses port 8000 and asks the owner for their own account password on first start. Existing primary untracked `playroom/` and private data remain preserved. This is a local Windows test build, not a phone/VPS deployment.

## One-shot AI trial preparation

The initial harness's missing preview profile, incorrect NPC attribution check, too-short live polling and superficial tests were corrected before any live credential use. Final reviewed harness `2dd51c6` (same files after merging main at `1a11b38`) has **13 focused tests PASS**, a zero-network dry run and a complete offline API/real-verifier/real-adapter flow using MockTransport, including one candidate, commit and reload. Parent full backend: **380 passed / 1 expected Windows skip**. Independent Sol review: no actionable blocker.

Controls: one shared locked completion guard across reload, exact method/URL/model, maximum 640 output tokens, one-job USD 0.01 local grant, fresh included-credit coverage and zero purchased credits immediately before dispatch, no redirects/retries, and controlled failure stage/dispatch-count diagnostics. The credential exists only in the final protected-main workflow step. Offline mock POSTs are not real provider requests.

[PR #41](https://github.com/rua-den/playroom/pull/41) final head `1a11b381d763ae97db252b51bc8b2d7a38583d15` passed [full CI #39190509173](https://github.com/rua-den/playroom/actions/runs/39190509173) and [offline trial CI #39190509233](https://github.com/rua-den/playroom/actions/runs/39190509233), attempt 1. Linux backend **381 passed**, frontend **136 passed / 3 skipped**, typecheck/build/compile and both Chromium flows; 13 focused trial tests and full offline fixture passed. Live job was correctly skipped on PR.

Merged main `0eeed40ba6e5c6cc6ae359b78e23a40e090cb157` passed [full application CI #39190693271 attempt 1](https://github.com/rua-den/playroom/actions/runs/39190693271). The explicitly triggered [real trial #39190693322 attempt 1](https://github.com/rua-den/playroom/actions/runs/39190693322) **FAILED**: `stage=provider_dispatch`, `provider_posts=1`, `failure_code=SCHEMA_INVALID`. No candidate/committed turn/reload acceptance was reached. No workflow rerun or automatic provider retry occurred. The failed run remains immutable evidence; do not call real AI acceptance passed.

The raw provider response was not retained, so its exact parse/attribution failure is unproven. Investigate the synthetic fixture's invented `profile_version_id` field against the real persisted selected version offline; do not loosen production attribution checks or infer a successful repair from offline mock responses alone.

## Corrected fixture verification preparation

The synthetic campaign's invented `profile_version_id=vy-profile-v1` was present alongside the actual persisted selected profile version in the serialized request. Remove that invented field from the fixture; it is not owner canon or production data. The offline transport now rejects the stale version literal and requires the actual selected version. This is a concrete fixture repair, not proof of the first model response's exact failure cause.

[PR #42](https://github.com/rua-den/playroom/pull/42) harness reviewed at `e8aa3679bb9a0119a9b84e8063ef09fd425ffb30`: parent and independent Sol **19 focused tests PASS**, compile/raw diff PASS, no actionable review blocker. Added diagnostics report only response-shape classifications/counts/attribution-match flags before synthetic temp DB cleanup; they do not emit response text, IDs, profile values or credentials. JSON null, non-object segments, missing/wrong attribution and fenced output have direct coverage.

The head's [full CI #39191335698](https://github.com/rua-den/playroom/actions/runs/39191335698) failed a frontend import test: the helper waited for a file-read callback invocation before the resolved conversation list reached React's UI. Backend and browser jobs passed. Luna's `988bcfe62c77f2b760f596265cc9a0aa669cb3f5` changes the helper to await the rendered conversation selector; pending-reader race tests retain their separate control. No production change, timeout increase or skipped assertion. Worker full frontend **136 passed / 3 skipped**, build/typecheck PASS; parent reviewed the one-line diff and independently ran **12 focused import tests PASS**. Fresh head CI replaces no failure history; the old run is retained.

A separately reviewed corrected-fixture verification is authorized under the owner's existing synthetic AI-testing instruction and risk ceiling. It uses a new exact commit trigger, not a rerun of the failed workflow, and retains the same one-request/640-token/USD 0.01 local-grant limits. The first request remains counted.

Final PR head `988bcfe62c77f2b760f596265cc9a0aa669cb3f5` passed [full CI #39191885455](https://github.com/rua-den/playroom/actions/runs/39191885455) and [offline CI #39191885431](https://github.com/rua-den/playroom/actions/runs/39191885431), both attempt 1: **387 Linux backend**, **136 frontend / 3 skipped**, typecheck/build/compile and both Chromium flows; **19 focused harness tests** and one mocked completion in the full offline app flow. Parent also independently reran all 19 focused harness tests. Live job was correctly skipped on PR. Merged code `aebed0805926bfd4994b9d449ca1e45339d27889` has the same complete tree as the reviewed head.

The distinct main [AI verification #39192040860 attempt 1](https://github.com/rua-den/playroom/actions/runs/39192040860) **PASSED**: authenticated app flow, one committed synthetic turn and reload persistence, with **one actual completion POST**. Combined with the first failed trial, this checkpoint made **two actual completion POSTs total**, without workflow reruns or automatic provider retries. The corrected fixture passed; the first failure's precise response defect remains unknown because its raw response was not retained. This verifies the synthetic API flow, not private-story generation or model quality. Private imported canon and provider-data consent remain pending local owner decisions.

Exact merged [full application CI #39192040946 attempt 1](https://github.com/rua-den/playroom/actions/runs/39192040946) **PASSED**: **387 Linux backend**, **136 frontend / 3 skipped**, typecheck/build/compile and both Chromium flows. This evidence applies to code `aebed0805926bfd4994b9d449ca1e45339d27889`; the final README/handoff release changes documentation only and does not claim a new app test run for its docs-only SHA.

## Owner test and next work

The Windows product and bounded synthetic real-AI API verification are delivered. Use the running loopback demo or the Desktop **Playroom - Demo** shortcut for the existing local sample/import review. Use **Playroom - Local Test** for the separate real account, then enter the owner's provider credential in Settings as described in [BAT-DAU.md](../../BAT-DAU.md). The GitHub secret is not retrievable/copied to local. Owner canon approval and provider-data consent must precede any private generation.

Next user-facing work should follow actual owner feedback on this build. Durable large-import chunk/resume (#27), real ChatGPT-export compatibility acceptance and the separate #20 gate remain follow-up scope; this checkpoint does not claim they passed, or claim phone/public deployment. Preserve the primary untracked `playroom/`, ignored source data and both local databases. Do not blindly rerun either real trial.

## Owner feedback: demo confusion and broken form layout — 19 October

The owner reported giant review checkboxes, a narrow chat input and repeated narration after configuring a model. Root confirmed the running port 8001 reports `mode=synthetic`: `create_demo_app` always injects `DemoFakeProvider`, so selecting a verified real profile there does not change its canned replies. Port 8000 was not running. This is demo/runtime confusion, not evidence of an invalid key. Never silently switch the private imported campaign to a real provider.

The bounded UI correction scopes text-input sizing away from checkbox/radio controls, keeps their labels touchable, and places composer help on a full grid row so the textarea has usable width. AppShell passes the actual demo flag to the composer and Settings; both explain canned replies, and the independent Settings note survives transient success messages. The real launcher still uses a separate account/data directory and requires owner-entered credentials and explicit Send. No private data, secret or owner approval state is migrated or reset.

Parent independently reviewed the implementation and ran **139 frontend tests PASS / 3 existing skips**, typecheck/build PASS, and both locked Chromium flows PASS. Browser assertions cover composer width/no horizontal overflow and compact checkboxes with touchable labels at 757px and 375px. These are synthetic browser checks, not physical-phone or additional real-AI tests. Exact PR/main CI evidence is recorded on the correction's PR before release.

## Owner feedback: saved-story navigation and Vietnamese headings — 19 October

Owner could not find the previous story after opening the create form and asked for a dashboard/current-story history. Safe read-only checks found **two active saved stories, six stored turns/revisions and one Legacy source/checkpoint** in the demo; the real local database had not been created. No private title, text, ID or credential was printed. Existing navigation hid the picker during creation and always picked the first listed story on reload. The source heading was valid NFC Unicode; UI headings used inconsistent serif/system font stacks.

Add **Thư viện truyện** with saved-story cards, actual update dates, **Mở truyện / Đọc tiếp**, and an always-available library button. **Đang đọc** identifies the current story. Store only the last chosen opaque story ID under an owner-specific browser key; restore only IDs present in the owner's accessible catalog and fall back to the library for stale/blocked storage. Returning to the library keeps the current composer mounted and retains unsent input. Changing story clears the previous projection before displaying the new selection. Catalog failures show an error/retry rather than an apparent empty create state; owner changes clear the previous cached catalog. Creation is called **Tạo truyện mới** and explains a separate story, context, characters and chat history. Use local Segoe UI/system heading fonts with readable spacing; no remote font request.

Parent independently reviewed the final implementation, ran **142 frontend tests PASS / 3 existing skips**, typecheck/build and both locked Chromium flows PASS, and inspected synthetic 375px/757px screenshots. The browser regression switches between two stories, preserves two actual committed fake-provider turns in the first, verifies the second has separate empty history, restores the chosen story after reload, retains an unsent action through library navigation, and asserts no additional provider dispatch from navigation/reload. Modal/background accessibility assertions remain intact. Early test-label/selector and screenshot-timing mistakes were corrected; their alleged passes are not release evidence. A later cleanup removed only an unused duplicate test string; the active verified flow is unchanged. Exact PR/main CI is recorded on the release PR before delivery.

No backend schema, source archive, consent, account or credential migration is involved. This navigation change does not invent historical chapters absent from a Legacy bundle and does not send private material or perform another real-model trial.
