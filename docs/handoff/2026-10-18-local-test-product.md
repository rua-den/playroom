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
- [ ] Parent full checks, exact PR and merged-code CI.
- [ ] Windows launcher smoke, private local pending import and owner-facing handoff.
- [ ] Owner-authorized one-shot synthetic real-AI app trial using the existing GitHub Actions credential.

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
