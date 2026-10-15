# Playroom B4 — live Ollama + physical phone readiness (no-cost preflight)

Date: 2026-10-14  
Inspected `main`: `4fa03cdbb8cca6fb3cfd9ef3861f5ee102797646`  
Status: **BUDGET GUARD VERIFIED; LIVE APPROVAL/PHONE STILL NOT B4 PASS**

## Evidence already obtained (do not repeat as a live-model claim)

- B1 (Send recovery) merged as [PR #3](https://github.com/rua-den/playroom/pull/3).
- B2 (mocked Ollama narrator/attribution) merged as [PR #5](https://github.com/rua-den/playroom/pull/5).
- B3 (real Chromium browser, fake provider, seven synthetic turns) merged as [PR #7](https://github.com/rua-den/playroom/pull/7) and [PR #8](https://github.com/rua-den/playroom/pull/8).
- [Exact B3 code-head run #38514327407](https://github.com/rua-den/playroom/actions/runs/38514327407): backend 279 passed; frontend 79 passed/3 skipped; typecheck, build, compileall, Chromium synthetic E2E PASS. This verifies code SHA `2652a453a037666b6020374dc1d0fc62f7afc8ec`. Subsequent docs-only commits were not rerun as code changes.
- None of this tests **actual Ollama Cloud**, a **physical Android/iOS device**, or **VPS/Caddy/TLS**.

## Verified implementation boundaries / risks

| Area | Confirmed from current source | Consequence for B4 |
| --- | --- | --- |
| Model profile | `backend/playroom/model_profiles.py::OllamaCloudVerifier` pins `https://ollama.com/v1`, API `gpt-oss:120b`; server GET `/models` checks model availability. | **Even profile verification makes a real provider HTTP request**. Require approval before trying. |
| JSON output | Strict schema is disabled for Ollama Cloud, while `backend/playroom/generation.py::_narrator_request` demands JSON `segments` for non-test narrator. | Observe actual model's JSON success rate; parser still validates cast/version; malformed output must not auto-commit. |
| Cost rate | Static uncached USD/token prices are input `0.00000015` and output `0.00000060`, with `pricing_verified=True` in a pinned profile. | Rate is **not fetched from a live billing endpoint**. Reconfirm vendor price before the first call and inspect provider-side billing afterward. |
| Cost authorization | [PR #11](https://github.com/rua-den/playroom/pull/11) enforces persisted owner `policy`/per-job cap and requires an additional, owner-approved, expiring cumulative trial grant for paid pinned narrator jobs. The `paid_trial_reservations` ledger is inserted atomically with the job and rechecked just before upstream dispatch. | **Conservative local reservation/ceiling only, not a vendor invoice guarantee.** The app retains unknown/cancelled post-dispatch reservations, blocks concurrent oversubscription, and stops on cost overrun. Code merge CI [PASS](https://github.com/rua-den/playroom/actions/runs/38538132285). |
| Credential storage | `backend/playroom/credentials.py` stores credentials in server-side JSON; file `0600`, secret root `0700`; API list uses masked text. | Keep credential off Git, CI, docs, log, screenshots and conversation; owner configures through a private HTTPS/loopback app or server-side secret mechanism. Treat server/shared-data backups as sensitive. |
| Production access | `backend/playroom/app.py` defaults allowed hosts to localhost/127.0.0.1 and uses secure cookies; production requires explicit host config. | Do not open on Internet via arbitrary port or turn off secure cookies to make a phone link work. |
| Deployment | This repository currently has no `deploy/playroom.service`, `deploy/playroom.caddyfile` or production release workflow. | Existing Playroom demo cannot be described as already deployed. VPS/Caddy/SSH changes are a **separate owner gate**. |

Official price at this review: [Ollama gpt-oss:120b-cloud model card](https://ollama.com/library/gpt-oss%3A120b-cloud) and [Ollama model pricing](https://ollama.com/pricing) show **USD 0.15/1M input**, **USD 0.014/1M cached input**, **USD 0.60/1M output**. Models, availability, charge type and price may change; reverify at actual trial time. Billing cap is a conservative internal estimate, not a guarantee of provider invoice.

## No-cost preflight (safe with fake provider only)

Use the synthetic local demo from README, never a private story import. Existing verified CI is sufficient evidence for the listed exact SHA; if checking a later code SHA, rerun:

```bash
uv sync --locked --extra test
uv run --locked --extra test pytest backend/tests -q
uv run --locked python -m compileall -q backend/playroom
(cd frontend && npm ci && npm test && npm run typecheck && npm run build)
```

For a local fake-provider demo, use `uv run playroom-demo --data-dir .playroom-demo` **only on the host controlled by the owner**; default binds `127.0.0.1`. Demo credentials, SQLite, and output are disposable synthetic data. **Do not expose demo's loopback server to the public Internet.** No model account or paid token is needed for this preflight.

## Owner authorization record — required BEFORE any real API call

Record approval outside Git with **all** fields; missing/ambiguous values mean no remote request.

- Provider: **Ollama Cloud**; pinned model: **`gpt-oss:120b`** (`gpt-oss:120b-cloud` label); exact endpoint `https://ollama.com/v1`.
- Who enters the credential: owner on a secure, supported server environment. **Do not paste secrets into this issue or report.**
- Approved content: explicitly **synthetic only**, or separately name the private campaign/data explicitly authorized to leave the host. Default is synthetic only.
- Run mode: **economy**, narrator only; no quality/context/consolidation calls to non-strict Ollama.
- Cost policy: `capped_paid` in persisted Settings; **positive per-generation USD cap:** `<owner value>`; **total authorized trial USD ceiling:** `<owner value>`; **approved maximum per-send USD:** `<owner value>`; **max number of manually confirmed Send actions:** `<owner value>`. Both per-job and trial caps now require a distinct owner-approved backend grant ([PR #11](https://github.com/rua-den/playroom/pull/11)). The UI values are conservative **estimates**, not a hard vendor billing guarantee; monitor the vendor dashboard. Never run an automated paid multi-turn sequence without separate explicit provider/content authorization.
- Allowed trial location: owner-local/staging environment `<actual URL/host>`; **physical device test** `<authorized yes/no>`. No VPS/site/SSH change is implied by model-trial consent.
- Trial authorization expiry `<UTC date/time>`; recording `<approver>` and explicit acceptance of API costs. Once expired, require new approval.
- Abort rule: unparseable/refused/truncated output, unselected NPC, player-agency violation, unexpected billed cost, questionable transcript privacy, or unknown job outcome => **STOP**, retain idempotency identity, do not automatically resend.

## Configuring the verified budget guard (no provider call until an explicit Send)

After choosing a paid verified narrator profile in Playroom, save **Economy** mode, **Capped paid** policy, and the maximum per-generation USD under **Cài đặt provider → Ngân sách và chính sách**. Under **Ngân sách toàn phiên trả phí**, enter total authorized USD, maximum estimated USD per send, maximum number of new jobs, and an ISO UTC expiry timestamp. Tick the explicit consent checkbox; **Chấp thuận ngân sách phiên** creates an owner-scoped, durable grant. **Xem hạn mức toàn phiên** displays reserved/remaining and jobs used; **Thu hồi phiên trả phí** prevents queued new upstream dispatch.

No key is included in this document. The credential is added only by the owner in the supported secure, isolated environment. The grant does **not** itself dispatch model requests; each Send requires a separate user action. Exceeding the estimated total/individual allowance or expiry blocks before provider dispatch, but **the vendor may still bill differently**; stop and reconcile any discrepancy. An ambiguous provider outcome retains its reservation and cannot be charged again by automatic reconnect.

At this checkpoint the feature is implemented, but the owner has **not** authorized actual Ollama inference, any private story transfer, production publication, or physical-device validation in this conversation. The source HEAD merge verification applies to code SHA `01548fb1a620455022e3a50dac63d72e82b85c22`; later documentation-only commits do not supersede that test record.

## Public-safe synthetic mini-world for the live trial

This is an invented test fixture, **not** part of the user's Henn/BANGTAN story.

- **Setting**: a quiet independent bookstore at night. The player persona **Lan** stands at the front counter. NPC **Vy** is present at the counter; NPC **Bình** is working at another location and **is not present**. The names are illustrative; actual character IDs and immutable `profile_version_id` values must come from Playroom's selected profiles, not be invented.
- **Public canon**: a blue paper note was placed in a wooden box at the counter. The contents of the note are unknown to both NPCs.
- **Narrator-only knowledge**: a delivery agent switched the note earlier. That fact is not known to Vy or Bình and cannot appear in their direct speech absent a documented observation.
- **Scene requirement**: only Lan and Vy are in the bookshop. Bình can be *mentioned* but cannot spontaneously speak from inside the shop, appear, or know its conversation without scene/knowledge change.
- **Player agency**: the narrator may respond with Vy's behavior and environmental consequences but must not generate Lan's new decisions, spoken lines, physical movements, thoughts, or goals.

### Three user-owned turns — manually sent, sequentially, only when authorized

1. `*Lan mở chiếc hộp gỗ trên quầy.* "Vy, cậu có thấy tờ giấy xanh không?"`
2. `*Lan nhìn về phía cửa sổ, vẫn đứng cạnh quầy.* "Mình sẽ kiểm tra lại ngăn kéo."`
3. `*Lan đặt chiếc hộp xuống.* "Đừng kể chuyện này với Bình khi mình chưa nói nhé."`

**Verify each job after Send**, before the next one: matching checkpoint, one job/key, terminal stop, parseable `{"segments":[...]}` with nonempty `narration`/`dialogue`, dialogue only for selected NPC IDs plus exact selected `profile_version_id`; no user-authored additions for Lan. Track `usage`, `finish_reason`, calculated/reserved/actual/unknown cost and whether the story persisted once. Neither positive parsing nor a model's self-claim is proof of semantic quality; inspect the actual text.

**Reconnect exercise:** During one explicitly approved job, reload browser and recover by saved job/key; inspect that the upstream attempt count is unchanged. A network error or by-key lookup failure is not permission to issue another paid job.

## Manual quality scorecard (fill only after approved live runs)

| Field | Turn 1 | Turn 2 | Turn 3 |
| --- | --- | --- | --- |
| Job/checkpoint IDs (redacted reference) | not run | not run | not run |
| Provider model/finish reason | not run | not run | not run |
| JSON parse + chosen speaker/version | not run | not run | not run |
| Player agency (PASS/BLOCK) | not run | not run | not run |
| Scene presence and NPC knowledge (PASS/BLOCK) | not run | not run | not run |
| Continuity/voice quality (1–5) | not scored | not scored | not scored |
| Actual/estimated/unknown cost & provider invoice | not run | not run | not run |
| Reload/reconnect same job; duplicate upstream calls | not run | not run | not run |

Acceptance: zero persona/scene/knowledge/duplicate-charge blockers, each quality dimension at least **4/5** on the user's evaluation, no unexpected vendor spend. Never fill this table with fake CI data as though it came from the live provider.

## Physical phone + VPS separate permission gate

1. Obtain owner permission for device trial and decide **actual Android/iOS model + browser**, network, test URL, add-to-home-screen expectation. Chromium viewport emulation does not count.
2. To put a phone on an Internet-accessible link, obtain **independent** authorization for staging/production access and first perform **read-only** VPS inventory: host OS/CPU architecture/RAM/disk, existing services/listeners, systemd Uvicorn and Python/uv availability, Caddy version/site configuration mechanism, DNS/TLS, wedding-online uptime, separated secrets/shared SQLite/backups. Never infer from templates.
3. Design private subdomain and app-only service/storage. Secure cookie, approved allowed host, TLS/HSTS, same-origin checks, authenticated SSE and existing-proxy safety must pass before issuing a phone link.
4. Only after owner-approved deployment: login, compose three turns, soft-keyboard/IME, switch apps/background/resume, reconnect, 360/390/430px layout on actual device, installed PWA where supported, persistence after a service restart, separate wedding service health.
5. No agent has been given VPS credentials or permission to edit Caddy/systemd in this B4 preflight.

## Decision / blockers as of 2026-10-14

**Completed:** earlier B1–B3 synthetic/browser acceptance, static provider pricing review, then [PR #11](https://github.com/rua-den/playroom/pull/11) implemented and tested the owner-granted cumulative budget guard, immutable job debit, queued policy revocation and last-moment dispatch check (merge code CI: backend 293, frontend 80 PASS/3 skipped, real Chromium PASS). Synthetic three-turn plan and owner scorecard are ready.

**Not completed:** provider account/credential verification, any network call to Ollama with credentials, actual cost measurement, semantic live story scoring, physical phone test, VPS/Caddy inventory or deployment.

**B4: NOT PASS.** Execute [Issue #9](https://github.com/rua-den/playroom/issues/9) only under explicit cost/data/device authorization and new coding work under `AGENTS.md` model-routing rules.

## 2026-10-15 verified Free starter implementation

[PR #16](https://github.com/rua-den/playroom/pull/16) is merged (exact code SHA `e81533f4597f2c35d46f28d0a7b026a9d9679439`). [Merge-head CI #38678014735](https://github.com/rua-den/playroom/actions/runs/38678014735) PASS — 303 backend and 84 frontend PASS/3 skipped, Chromium E2E PASS. UI now allows verified `gemma4:31b-cloud` Free starter and retains paid `gpt-oss:120b-cloud` explicitly.

A repository secret preflight [#38675986601](https://github.com/rua-den/playroom/actions/runs/38675986601) confirmed `gemma4:31b` is visible in this account's authenticated catalog, without invoking an inference. The original older paragraph here about the **only** fixed Ollama `gpt-oss:120b` profile is a historical finding and is superseded. **Still B4 NOT PASS**: model availability and static starter-plan eligibility do not verify remaining credits, billing source, actual narrator quality or a physical device. Consent and risk ceiling for a live completion remain separate.



## Update — 2026-10-15 B4 credit-source preflight

The previous "no balance endpoint" uncertainty has been superseded by Ollama's [official `GET /api/balance` documentation](https://docs.ollama.com/api/balance). Protected-main preflight [#38695103573](https://github.com/rua-den/playroom/actions/runs/38695103573) checked the owner's existing repository key **read-only** and recorded included credits POSITIVE / purchased credits ZERO (snapshot only, no exact amounts in logs); zero inference calls. It is not a guaranteed purchased-credit lockout.

[Issue #17](https://github.com/rua-den/playroom/issues/17) now CLOSED by [PR #18](https://github.com/rua-den/playroom/pull/18): starter Gemma4 in `free_only` cannot be dispatched when purchased-credit billing exclusion isn't proven. Owner-approved `capped_paid` grants are mandatory even for starter-labelled Ollama profiles. Backend **309** and frontend **85 pass/3 skipped**, Chromium PASS on exact PR/main code. B4 *real* model/physical phone still NOT PASS and requires independent approval; see current [Issue #9](https://github.com/rua-den/playroom/issues/9).

[PR #19](https://github.com/rua-den/playroom/pull/19) main verification [#38695103532](https://github.com/rua-den/playroom/actions/runs/38695103532): first Chromium browser job timed out waiting for turn count; failed-job rerun PASS on same SHA. Keep this flake visible for follow-up if it recurs.


## 2026-10-15 live Gemma4 adapter trial evidence

With user approval for *synthetic Free-account testing only*, [one-turn run #38720371467](https://github.com/rua-den/playroom/actions/runs/38720371467) produced valid streamed JSON, but its job status was FAILED on a heuristic false positive repeating Lan's *already-authored* box-opening. [Three-turn run #38721810244](https://github.com/rua-den/playroom/actions/runs/38721810244) later PASSed all three streamed Gemma4 outputs: 2042 input / 513 output tokens, locally calculated USD 0.00049108, valid `segments` and Vy speaker/version, no detected new Lan agency, absent Bình speech or private-knowledge leakage. Purchased balance was ZERO at each preflight; included balance covered the next local guard. No exact account balances were printed. [Details](2026-10-15-b4-gemma4-live-results.md).

This is a real model adapter test, NOT a live end-to-end HTTP/SQLite Playroom story or a physical-device result. Existing B4 device/VPS/site approval boundaries remain; do not mark B4 PASS on this evidence alone. [Browser flake #25](https://github.com/rua-den/playroom/issues/20) is separate.
