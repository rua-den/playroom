# Playroom — Ollama Free starter model gap and B4 test contract

Reviewed: 2026-10-14. Source before this review: `881e91a8707ada6c970bf206ad7de79db8ab0aa2`.  
Implementation: [Issue #14](https://github.com/rua-den/playroom/issues/14). Owner-authorized live acceptance: [Issue #9](https://github.com/rua-den/playroom/issues/9).  
Status: **source review and implementation contract; no production code or live inference executed.**

## Verified Ollama billing rules

- [Official pricing](https://ollama.com/pricing): Free includes monthly starter usage credits for a subset of cloud models, measured in tokens, not a fixed number of Sends. Free allows **one concurrent request**, not one monthly request.
- [Ollama's official download instructions](https://ollama.com/download) explicitly recommend **gemma4:cloud** on the Free plan, and say most other Cloud models require a paid plan or purchased credits.
- Account credits from the Free plan are consumed **before purchased credits**. Once included credits are exhausted, a Free user with purchased balance may still draw from that balance. Starter eligibility therefore does **not** guarantee a zero-cost inference or absence of a paid-credit debit.
- As checked on 2026-10-14, the [published gemma4 rate](https://ollama.com/pricing) is USD 0.14 per million input tokens, USD 0.05 per million cached input, and USD 0.40 per million output; this is the token price used to measure included credits too.
- Existing authenticated [OLLAMA_API_KEY GitHub Actions preflight](https://github.com/rua-den/playroom/actions/runs/38556240502) successfully checked /v1/models and found gpt-oss:120b. **It did not check gemma4**, remaining included credits, purchased-credit balance or any real completion.

## Current Playroom blocker: Free UI but no Free Cloud model

| Code | Verified source | Consequence |
| --- | --- | --- |
| backend/playroom/model_profiles.py | OLLAMA_CLOUD_MODEL = gpt-oss:120b-cloud; only exact label permitted; resulting credential_tier = paid | Cannot create a real Free-eligible Ollama narrator profile |
| backend/playroom/api/configuration.py | Overrides submitted Ollama label with hardcoded gpt-oss constant | Simply editing dropdown cannot enable a Free starter |
| frontend/src/components/SettingsPanel.tsx | Always submits gpt-oss:120b-cloud for Ollama verification | No actual starter-model choice |
| backend/playroom/model_profiles.py::validate_dispatch | free_only requires profile credential_tier == free | Correctly denies all existing Ollama profiles; keep this fail-closed boundary |
| backend/playroom/provider.py | Ollama narrator-only SSE adapter, no strict native structured output | Retain JSON prompt + independent cast/version validation |
| .github/workflows/ollama-secret-preflight.yml | Protected-main GET /v1/models with secret, boolean gpt-oss presence only | Narrow read-only gemma4 ID check can be added by approved coding agent |

## Definitions the UI and verifier must not conflate

1. Model catalog presence: a model ID appears for the key; not an authorization for plan credits.
2. Starter-model eligibility: provider-public model-list policy identifies the model as Free starter, date/source recorded. **Not a live balance.**
3. Included credits remaining: per-account balance, **unknown** until a verified source returns it.
4. Purchased-credit exposure: even a starter model can consume separately purchased credits when included credits run out. Backend free_only blocks model upgrades but cannot ensure vendor charges never occur.
5. Per-token price: positive even for requests covered by included plan credits.
6. Narrator attribution: valid segments JSON is structurally enforced after generation; it is not proof of semantic player agency.

## RED-first coding checkpoint (Issue #14)

1. Read AGENTS.md and current main; use Luna coding route. Branch, do not write untested production code directly on main.
2. Unit tests for a narrow allowlist accepting gemma4:cloud (wire API model expected gemma4, confirm via actual /v1/models), with source/date and verified pricing. Preserve gpt-oss paid profile. Reject arbitrary endpoint, nonexistent or spoofed model and unsupported role/schema.
3. Verifier must record eligibility and provenance **separately** from model presence and account remaining-credit balance. Do not set tier free solely because an ID was returned. Record uncertainty honestly where live account credit evidence is unavailable.
4. Backend regression: correctly verified starter profile with free_only is dispatchable only when startup model/profile checks PASS; gpt-oss and unknown-tier profiles remain blocked. No free_only → capped_paid fallback on quota/errors/reconnect.
5. Frontend regression: user can select Gemma4 Starter explicitly vs gpt-oss Paid. Free mode shows no fictitious USD cap/Send quota. Paid mode shows informed opt-in and retains Issue #10 grant.
6. Mocked Ollama SSE/JSON narrator tests: validate existing NPC ID/version, finish_reason, missing terminal, truncated output, no Henn actions or leaked narrator-private facts; no auto-paid retries.
7. Run backend tests/compile, frontend tests/typecheck/build and synthetic Chromium E2E. Review exact PR diff and require **GREEN on exact PR SHA and merged-main SHA** before accepting feature.
8. Optional, only after merge and on protected main: modify the existing **metadata-only** GitHub Actions workflow to print the boolean presence of gemma4 in /v1/models. Do not log raw catalog/key, invoke chat/completions, or print private transcript.

## Separate user-cost and data gate (Issue #9)

Before any real completion, approve a small trial using invented bookshop characters Lan/Vy/Bình (not Henn/BANGTAN). Obtain a positive spending-risk bound **or** proof that purchased credits cannot be debited, and verify relevant model and authorized content. Even on a Free account, an Ollama starter completion consumes token-based credits and may draw purchased balance. A catalog GET does **not** establish which credit bucket will be used.

No physical phone, VPS/Caddy, real-model quality score, token invoice, or usage balance were tested in this research. Real device and deployment are separate explicit gates.

## Routing

Current AGENTS.md requires Luna for code changes; past single-issue direct-coding exceptions (#2/#4/#6/#10/#12) do not cover Issue #14. This session does not have a Luna dispatcher. This plan is documentation-only, not a silent coding exception.

## Codex Astra ownership update (2026-10-15)

The owner has now explicitly selected **Codex Astra** to implement Playroom from the latest GitHub `main`. This 2026-10-15 owner direction **supersedes** the older Luna-only route written at the end of this 2026-10-14 planning document. Refer to [the active Codex handoff](../handoff/2026-10-15-codex-astra.md) and topmost `AGENTS.md` owner override. All verification, privacy, budget and live-provider approval gates above remain unchanged. This is authorization for code implementation and tests by Astra, not for unbounded purchased-credit API calls or VPS deployment.
