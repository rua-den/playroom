# Playroom B4 — real Ollama Gemma4 synthetic narrator evidence

Date: **2026-10-15** (Asia/Ho_Chi_Minh). Scope: one-shot and three-turn **synthetic** narrator through the *actual* Playroom `OllamaCloudVerifier`, persisted immutable profile, `OllamaCloudAdapter` SSE client, and `parse_narrator_payload`. **NOT** a full live FastAPI campaign/browser/device acceptance. User authorized Free-account synthetic testing; no Henn/BANGTAN personal canon sent.

## Exact SHA and evidence

- [PR #21](https://github.com/rua-den/playroom/pull/21) one-shot harness; [PR #22](https://github.com/rua-den/playroom/pull/22) corrected pinned `httpx2` import; [PR #23](https://github.com/rua-den/playroom/pull/23) added real immutable profile persistence and offline adapter contract. The first two live workflows exited **before** sending any model POST.
- [One-turn live provider run #38720371467](https://github.com/rua-den/playroom/actions/runs/38720371467), code SHA `f0a3e3fa29df00bfcf29f558fc522114f4291751`: **one actual** `gemma4:31b` streaming completion with terminal `stop`, four parseable `segments`, matching Vy speaker/version, no absent speaker or private-knowledge heuristic flag. Input **360** / output **227** tokens; locally calculated **USD 0.00014120** (not provider invoice). Workflow marked failure because naive regex flagged `Lan mở nắp`, a repetition of the player's existing `Lan mở hộp` action. **Do not misreport that workflow as fully green**.
- [PR #24](https://github.com/rua-den/playroom/pull/24) provided three-turn sequential synthetic continuity contract; its first workflow [#38721386009](https://github.com/rua-den/playroom/actions/runs/38721386009) exited **before model POST** due double-counting the total trial estimate. [PR #26](https://github.com/rua-den/playroom/pull/26) fixed the aggregate-vs-per-turn preflight, tested valid and invalid allowances offline and merged at SHA `cc992c81c0e24839e2aabeff4fe37d8cd56830d1`.
- [Actual three-turn live run #38721810244](https://github.com/rua-den/playroom/actions/runs/38721810244) **PASS 3/3 sequential provider POSTs** at that exact SHA, on first workflow attempt. [Same SHA automated Playroom CI #38721810166](https://github.com/rua-den/playroom/actions/runs/38721810166) **PASS** backend, frontend build/typecheck/tests, and Chromium synthetic E2E. The prior PR browser gate had intermittent timeout twice before passing on run attempt three; [Issue #25](https://github.com/rua-den/playroom/issues/25) tracks that independent browser test race.

## Verified real model outputs

Model: `gemma4:31b`; display label `gemma4:31b-cloud`. Synthetic setting: Lan (player), Vy (present, exact pinned ID/version), Bình (absent); wooden box, blue note, hidden delivery-swap fact. The user's *only* authored actions were opening the box, looking at the window while at the counter, then placing the box down and asking Vy not to tell Bình.

| Turn | Input tokens | Output tokens | Calculated USD from published input/output rates | Provider stop | JSON + selected cast | Agency/scene/knowledge heuristic |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | 344 | 185 | 0.00012216 | stop | PASS (2 segments) | all false |
| 2 | 687 | 168 | 0.00016338 | stop | PASS (2 segments) | all false |
| 3 | 1011 | 160 | 0.00020554 | stop | PASS (2 segments) | all false |
| **Total** | **2042** | **513** | **0.00049108** | **3/3** | **3/3** | **3/3 no warning** |

Observations: Vy remembers the paper was in the box, suggests checking the drawer, and promises not to tell Bình, without speaking as Bình or asserting knowledge of the narrator-private delivery swap. These are short, plausible responses and a **positive early signal**, not an owner-evaluated 4/5 full semantic acceptance or proof of long-session quality.

## Credit source and privacy

- Before each request the protected-main workflow performed authenticated read-only `GET https://ollama.com/api/balance`. **Included Free credits covered its conservative next reservation and purchased credits were zero at each observed preflight**; no exact account balance was printed.
- Three-turn local guard: **maximum three POSTs**, max **640 completion tokens each**, conservative **USD 0.0015 per turn** and **USD 0.0045 aggregate allowance**; the owner's earlier accepted risk ceiling was **USD 0.01**. No ambiguous provider failures or retry occurred in the successful three-turn run.
- Dollar amounts above are **locally computed from reported tokens and public USD/token rates**, not final charge records. Neither balance snapshots nor local reservations guarantee vendor's future billing or disable the use of purchased credits if added later.
- The only prompts sent were invented synthetic Lan/Vy/Bình content. The repository secret remains in protected GitHub Actions, not committed or printed. No personal roleplay canon, physical phone, VPS/Caddy or deployment was involved.

## Remaining B4 gates

**B4 remains INCOMPLETE**. The real adapter/standalone synthetic sequence is proven, but the owner-authenticated Playroom app's **whole HTTP generation → SQLite job → persistent story → reconnect → phone** journey has **not** been verified using the live model. Automated browser tests continue using a fake provider. For final B4 acceptance, perform an explicitly approved staging-only end-to-end app run with scoped credentials/credit guard, then a real physical phone/device smoke. Production domain, VPS, Caddy, backups and wedding-online isolation require separate owner consent and host inventory. Address independent browser race [Issue #25](https://github.com/rua-den/playroom/issues/25). Do not mark B4 PASS based on this test alone.
