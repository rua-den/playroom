# Codex / Astra execution handoff — Playroom

**Date:** 2026-10-15 (Asia/Ho_Chi_Minh)  
**Repository:** https://github.com/rua-den/playroom  
**Initial verified `main`:** `99b2596c11257175586895a58ea26f195d350d9b` (documentation HEAD before this handoff; always fetch latest `origin/main` first)  
**Active coding model:** **Astra in Codex**, explicitly selected by the owner, superseding prior Luna-only model routing for Codex work.  
**Mode:** Resume implementation autonomously from GitHub; not a request to do more planning.

## Mission

1. **Implement [Issue #14](https://github.com/rua-den/playroom/issues/14) — Ollama Free starter narrator via `gemma4:cloud`**, with an accurate verified provider profile, secure/free-first UI and regression-first tests. The [full technical acceptance contract](../plans/2026-10-14-ollama-free-starter-gap.md) and provider [spec](../superpowers/specs/2026-10-13-ollama-cloud-provider-design.md) are committed.
2. After #14 is green on exact PR and merge HEAD, continue the **non-chargeable/read-only** parts of [Issue #9](https://github.com/rua-den/playroom/issues/9) (B4 real Ollama, mobile, and release readiness). Stop at the **explicit approval boundary** before paid-credit-exposed inference, any private story transmission, actual phone access or VPS/Caddy deployment.
3. Keep all changes and updated status/handoff documents on **GitHub `main`** after reviewed and tested PR merges. Do not rely on the user's local machine as source of truth; do not force-push main.

## What is already done — do NOT reimplement

- B0/B1 Send/recovery: [PR #3](https://github.com/rua-den/playroom/pull/3) PASS.
- B2 mocked Ollama JSON narrator, character ID/version attribution: [PR #5](https://github.com/rua-den/playroom/pull/5) PASS.
- B3 real Chromium synthetic seven-turn/mobile viewport/reconnect test: [PR #7](https://github.com/rua-den/playroom/pull/7) and [PR #8](https://github.com/rua-den/playroom/pull/8) PASS.
- Cumulative paid-trial budget guard, transaction-safe holds and explicit owner consent: [PR #11](https://github.com/rua-den/playroom/pull/11) PASS.
- Free-first Settings UI: [PR #13](https://github.com/rua-den/playroom/pull/13) PASS; does not pretend Ollama Free grants 50 fixed Sends.
- **Last code commit tested:** `2220a63f4d24cf61a67493ab41b4909fd3dffeee`, [exact merged-main CI #38556240140](https://github.com/rua-den/playroom/actions/runs/38556240140): **293 backend PASS**, **83 frontend PASS/3 skipped**, typecheck/build/compile and real Chromium synthetic E2E PASS. Later commits to `main` are documentation-only; do not claim those earlier CI runs tested future code.
- The owner added repository secret `OLLAMA_API_KEY`. [Read-only preflight #38556240502](https://github.com/rua-den/playroom/actions/runs/38556240502) authenticated `GET https://ollama.com/v1/models` and saw `gpt-oss:120b` in catalog; **zero inference calls**. Availability does not imply free-credit eligibility or an observable balance.
- Remaining open checkpoint issues at transfer: **[#14](https://github.com/rua-den/playroom/issues/14) implementation**, then **[#9](https://github.com/rua-den/playroom/issues/9) live/phone acceptance**. No open PR was found on initial verification.

## Read order

1. `AGENTS.md` (new Codex Astra owner override takes precedence over older Luna-only paragraph).
2. `README.md` and **this file**.
3. `docs/plans/2026-10-14-ollama-free-starter-gap.md`.
4. `docs/handoff/2026-10-14-next-execution.md` (historical decisions and prior exact SHAs).
5. `docs/superpowers/specs/2026-10-12-personal-playroom-design.md`, `docs/superpowers/specs/2026-10-12-runtime-ai-context-policy.md`, `docs/references/playrooom-style-and-evaluation.md`.
6. Production and tests: `backend/playroom/model_profiles.py`, `backend/playroom/api/configuration.py`, `backend/playroom/provider.py`, `backend/playroom/generation.py`, `frontend/src/components/SettingsPanel.tsx`, `backend/tests/test_ollama_cloud.py`, other relevant regression suites.

## Issue #14 — implementation contract

**Observed blocker:** Ollama verifier/API/Settings are currently hardpinned to `gpt-oss:120b-cloud` (wire `gpt-oss:120b`), with `credential_tier="paid"`. Backend `free_only` correctly rejects this profile. Need a **verified Free starter option**, not merely a prettier Free screen.

1. Verify official Ollama pricing/setup sources as of execution. Ollama has described `gemma4:cloud` as a Free starter candidate, but **confirm the live model ID and alias with authenticated read-only catalog metadata** (do not blindly assume wire ID). Preserve existing paid gpt-oss behavior.
2. Build a narrow allowlist and immutable provenance: catalog availability **separate from** published starter eligibility **separate from** unknown account credit balance; record metadata source/date, pricing/capabilities. A model's presence in `/v1/models` alone is **not** evidence that an invocation is free.
3. Implement the server-side verification, API model selection and frontend dropdown for Free starter vs paid, with **no fabricated request counts or remaining credits**, no automatic switch to `capped_paid`, and preserved hard spending guard for paid profile. If price or eligibility unknown, show `unknown` and fail closed.
4. Preserve narrator-only Ollama role, no unsupported native strict JSON schema, structured `segments` parsing, speaker/profile_version validation, no unrequested player actions, absent NPCs or narrator-private knowledge leaks. User exclusively controls Henn; use **invented synthetic fixtures**, not private transcript/canon.
5. RED-first tests before each production fix: valid Free candidate mapping; unsupported model/endpoint; gpt-oss still paid; account catalog visibility alone cannot mark Free; UI free vs paid opt-in; schema/429/refusal/truncated stream; no duplicate provider dispatch on retries/reconnect.
6. Use feature branch (e.g. `codex/issue-14-ollama-free-starter`) and incremental commits. PR review on the exact diff. Full CI must pass on exact PR SHA **and** merged-main SHA before issue closure.

## Required verification commands (on the Codex runner)

```bash
uv sync --locked --extra test
uv run --locked --extra test pytest backend/tests -q
uv run --locked python -m compileall -q backend/playroom
cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

Also run the repo's real Chromium synthetic E2E path from `.github/workflows/frontend-ci.yml` and check `git diff --check`. On a Windows host, inspect `C:\Users\huy.nguyen\.codex\RTK.md` and follow its `rtk` wrapper requirements if that file exists; never assume CI/Linux has this path.

## Live Ollama / Free billing boundary

- The user explicitly approved use of the **GitHub Actions repository secret** for testing; do **not** print/echo it or paste it into docs, code, PR descriptions, traces or issues. `GET /v1/models` on protected main is already authorized and verified.
- **No real completion has been run** and **no purchased-credit spending authorization has been provided**. Free plan may have included monthly token credits, but if depleted Ollama may draw separately purchased credits; no verified available-balance endpoint currently protects against this. Use mocked provider tests while implementing #14. Metadata-only catalog checks are allowed; **do not dispatch `/chat/completions` automatically** until the owner has approved the trial data and financial risk or a provider-enforced no-purchased-credit mechanism is proven.
- B4 semantic trial later uses synthetic fictional bookshop Lan/Vy/Bình from `docs/acceptance/2026-10-14-b4-live-trial-readiness.md`, never Henn/BANGTAN material by default. Score JSON, agency, presence/knowledge, cost and reconnect.
- Separate approval required before physical-phone trial, Internet publication, Caddy/systemd edits, production credential configuration or VPS deployment.

## Progress and report requirements

Follow the owner forward-progress rule: failures/tool timeouts/ambiguous results are **not** terminal; perform bounded diagnosis, narrower tests, fix, retry. Stop only after verified PASS, truly external blocker, or owner approval gate.

Every finished checkpoint must report exact starting/main/code SHA, changed files, RED and GREEN test results, PR URL, merged SHA, precise command/run statuses, remaining risks, and update this handoff and `README.md`. Do not say B4 PASS because mocked tests or metadata-only catalog lookup passed.

## Short Codex starting instruction

> Work on GitHub repository `rua-den/playroom` using **Astra as coding model**. Fetch and verify latest `origin/main`, then read `AGENTS.md` and `docs/handoff/2026-10-15-codex-astra.md` before other code. Implement GitHub Issue #14 test-first on a branch. Maintain immutable model/profile contracts, Free-only fail-closed rules, paid budget guards, narrator/character agency and existing B1–B3 regression behavior. Run full backend/frontend/browser CI and independently review the diff; squash-merge only on green exact-SHA CI and update the handoff. Continue non-chargeable Issue #9 readiness next, but **do not run real inference, send private story content, change VPS or spend purchased credits without the owner's separate approval**. Keep moving autonomously on the current checkpoint; provide precise test/commit status.

## 2026-10-15 — Issue #14 now PASS; resume B4 Issue #9

Historical steps above referring to Issue #14 as the *next* task are superseded by [PR #16](https://github.com/rua-den/playroom/pull/16), code SHA `e81533f4597f2c35d46f28d0a7b026a9d9679439` and [exact merged-main CI #38678014735](https://github.com/rua-den/playroom/actions/runs/38678014735) **PASS** (303 backend / 84 frontend PASS, 3 skipped, typecheck/build/compile/Chromium E2E). This was completed directly in ChatGPT after the owner reported exhausting Codex tokens and requested continuing; no real paid Ollama inference was executed.

Authenticated read-only catalog [#38675986601](https://github.com/rua-den/playroom/actions/runs/38675986601) confirmed the real API ID `gemma4:31b`; the Free starter dropdown displays `gemma4:31b-cloud`. Paid `gpt-oss:120b` is unchanged. UI explicitly warns that **Free starter eligibility does not prove remaining included credits or prevent spending previously purchased credits**.

**Now open:** [Issue #9](https://github.com/rua-den/playroom/issues/9) real Ollama/physical phone B4 acceptance. Metadata-only test + mocked E2E are completed; real completion and any billable credit draw have not been approved with explicit positive spend ceiling. Continue read-only and safe work autonomously, **stop before API inference or VPS/physical-device changes without their separate owner gate**. Do not repeat #14 implementation.

## 2026-10-15 — Independent B4 pre-dispatch review: free-credit billing blocker

Latest audited documentation `main` before this addition: `86596dbff994942c010c124bd393d75b21e96ebd`; latest accepted production SHA is still `e81533f4597f2c35d46f28d0a7b026a9d9679439` with [exact merge-head CI PASS](https://github.com/rua-den/playroom/actions/runs/38678014735). This is a **read-only code + vendor policy audit**, not new implementation or test execution.

**NEW BLOCKER:** [Issue #17 — Free starter may draw purchased Ollama credits without trial authorization](https://github.com/rua-den/playroom/issues/17). Official [Ollama pricing FAQ](https://ollama.com/pricing) confirms plan credits are used first and purchased credits afterward. `gemma4:31b` is starter-eligible but `model_profiles.py` explicitly records unknown free balance/purchased-credit exposure and still labels it `credential_tier="free"`. `validate_dispatch(..., "free_only", ...)` ignores unknown balance, while `generation.py` requires cumulative trial grants only for `credential_tier="paid"`. **Therefore both the Free-only non-purchased-credit promise and opting into capped-paid for the starter profile need code corrections before any charge-exposed inference.** No actual purchased-credit debit has been observed.

**Next implementation owner:** **Codex Astra**, per top-level `AGENTS.md` owner instruction. Implement [#17](https://github.com/rua-den/playroom/issues/17) regression-first with provider-source evidence, fail closed when credit-source protection is unknown, and make a consciously charge-exposed starter request require owner-approved persisted cumulative+per-send grant before dispatch. Preserve Gemma4 wire IDs, gpt-oss billing, immutable profile binding and no auto paid retries. Full backend/frontend/real-browser CI on exact PR and merge SHAs before PASS. Agent cannot invent a protected account credit-balance API or claim a provider bill is hard-limited by app estimates.

**Remaining authorization:** [#9](https://github.com/rua-den/playroom/issues/9) remains OPEN. Do **not** execute `/chat/completions`, send personal Henn/BANGTAN data, test a physical device, or deploy/change VPS/Caddy without independent owner approval of content, spend risk and target environment. Existing protected-main read-only `GET /v1/models` checks are allowed but do not prove a no-charge request.


## B4 2026-10-15 — credit-source protection PASS and official balance preflight

- Implemented/closed [Issue #17](https://github.com/rua-den/playroom/issues/17) in [PR #18](https://github.com/rua-den/playroom/pull/18), code SHA `dc5f23c8bcf9c4d5761511d91974b77bd7273799`. Regression-first; [exact PR CI #38694560407](https://github.com/rua-den/playroom/actions/runs/38694560407) and [main CI #38694713531](https://github.com/rua-den/playroom/actions/runs/38694713531) PASS: backend **309**, frontend **85 pass/3 skipped**, typecheck/build/compile/Chromium E2E. `free_only` blocks Ollama when purchased-credit lockout isn't provider-verifiable. `capped_paid` requires persisted grant for Gemma4 too, not just paid-labelled profiles; revoke/reconnect/legacy job dispatch guards verified.
- Discovered newly documented official [Ollama Balance API](https://docs.ollama.com/api/balance): authenticated `GET https://ollama.com/api/balance` returns distinct included and purchased credit buckets. It does **not** enforce a purchased-credit lockout. [PR #19](https://github.com/rua-den/playroom/pull/19) merged as `3b30c041b46a71c4782cef980a6357cdc81a3337`, adding *read-only* secret-safe GitHub Actions check on protected main. [Actual run #38695103573](https://github.com/rua-den/playroom/actions/runs/38695103573) PASS: `gemma4:31b` catalog presence true; included credits POSITIVE; purchased credits ZERO at observation time; no raw amounts/token/private content logged; **zero chat completions**.
- PR #19 [exact main CI #38695103532](https://github.com/rua-den/playroom/actions/runs/38695103532): backend/frontend PASS; Chromium E2E timed out counting turn 3 on **first attempt**, but **PASS on failed-job rerun (run attempt 2)** at same code SHA. Treat as observed flakiness, not an unqualified clean first-run PASS. Monitor separately if repeated; no code changes to gameplay in PR #19.
- **Next checkpoint** [B4 Issue #9](https://github.com/rua-den/playroom/issues/9) real synthetic narrator and actual phone. It still requires explicit *positive spending-risk ceiling / content consent* before a POST completion. A positive included-credit balance and purchased ZERO do not guarantee future charge-source behavior (shared balance and possible billing changes). No Henn private campaign, phone, VPS/Caddy or deployment changes authorized or performed.


## 2026-10-15 — successful synthetic live Gemma4 single- and three-turn adapter tests

- User approved limited synthetic testing using their Ollama Free account on 2026-10-15. Initial one-turn real Ollama adapter run [#38720371467](https://github.com/rua-den/playroom/actions/runs/38720371467) streamed valid JSON and Vy version, 360/227 tokens, estimated USD 0.00014120; CI marked failure from an overbroad heuristic that misread repetition of Lan's submitted box-opening as a newly invented action.
- Subsequent three-turn **real provider run [#38721810244](https://github.com/rua-den/playroom/actions/runs/38721810244) PASS at main code SHA `cc992c81c0e24839e2aabeff4fe37d8cd56830d1`**: 3 POSTs only, all streams finished normally and returned valid `segments` and correct Vy ID/version; no actor, absent Bình, agency or secret-knowledge heuristic issues. Input 344+687+1011=2042 / output 185+168+160=513 tokens, calculated USD **0.00049108** (NOT vendor invoice).
- Preflight for each POST confirmed included balance adequate for a conservative allowance and purchased balance ZERO at that moment; no numeric account balance/credential/private Henn data logged. Local risk was capped at 0.0015 USD/turn ×3 = 0.0045 USD reserved, within owner's earlier approved 0.01 USD risk ceiling. No model retry on the successful run.
- [Exact code-head CI #38721810166](https://github.com/rua-den/playroom/actions/runs/38721810166) PASS backend, frontend, Chromium; PR browser E2E needed reruns due known nondeterministic turn count, tracked [Issue #25](https://github.com/rua-den/playroom/issues/20).
- Detailed source-backed report: [2026-10-15-b4-gemma4-live-results.md](../acceptance/2026-10-15-b4-gemma4-live-results.md). **Issue #9 STILL OPEN:** these runs use the real adapter and separate synthetic prompt harness; NOT full authenticated web app + SQLite generation/reconnect, physical phone, production deployment or vendor invoice validation. Do not claim B4 PASS. Next meaningful work is live, authenticated, isolated staging end-to-end run under explicit credential/credit limits; actual phone/VPS requires independent approval.
