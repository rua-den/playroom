# Playroom legacy bundle import — verified checkpoint (17 October 2026)

**Repository:** `rua-den/playroom`  
**Initial main:** `44e7409178df53e85177fc079ae0706471bd93db`  
**Merged implementation:** [PR #34](https://github.com/rua-den/playroom/pull/34), main commit `2975dc1a6950725e6ad70b2415eeef45f2a896a4`.  
**Exact PR-head CI:** [Actions #39051072648](https://github.com/rua-den/playroom/actions/runs/39051072648), head `754463f479f36f2c765b999f75762d4897e820b1`, backend/frontend/Chromium **PASS on first run for that exact final head**.  
**Exact merged-main CI:** [Actions #39051194140](https://github.com/rua-den/playroom/actions/runs/39051194140), main `2975dc1a6950725e6ad70b2415eeef45f2a896a4`, backend/frontend/Chromium **PASS**.

## What is now implemented

- A separate `playroom_legacy_story_bundle` version `1.0.0` import path, unlike official ChatGPT `conversations.json`. Select one owner-local JSON file, inspect bounded metadata-only preview, stage authenticated source into owner-scoped persistent SQLite, and open a new provisional campaign.
- Strict 20 MiB payload, schema/UUID/persona/NPC/reference/order/source-flag checks. Relationship/canon/event summaries become **pending imported memories**, not user/assistant conversation turns. Scene and the previous authored user excerpt are staged with unverified source attribution. No missing historical chapters or dialogue are fabricated.
- Model Send remains server-locked until owner review of persona, cast/presence, knowledge scopes, missing history, and **separate explicit provider-data consent**. The selected source is never transmitted to an external provider at preview, import or review; a later explicit Send still requires configured provider and its existing grant/policy checks.
- UI has **Nhập Legacy**, preview/confirmation, review of source proposals, and consent check. Chromium tests exercise synthetic import → unauthorized Send blocked → review → one fake Send → reload. Import preserves source bytes as JSON in local database, not in this public repository.

## Verification record and limitations

The initial synthetic parser contract was intentionally RED at `812fce4`. Intermediate pushes had genuine test/typecheck failures; these were diagnosed and fixed rather than relabeled as green. The final PR and exact merged main runs above are both green. The public tests use only invented Lan/Vy fixture content. The owner's private story bundle was inspected **locally only for its schema consistency**, not uploaded to GitHub or provider, and **was not run as a full importer/live-model end-to-end test**; actual owner-local private-file import and reviewed story continuity remain an acceptance step. No physical-device or VPS/Caddy deployment was performed.

## Resume order

1. Owner-local acceptance of the actual selected private Legacy bundle using `playroom-live-local`; verify the displayed pending memories, focus scene and chapter metadata, fix mapping/knowledge discrepancies as needed before approving. Do not import personal data to public CI.
2. Finish [Issue #27](https://github.com/rua-den/playroom/issues/27): official ChatGPT export ZIP/multipart/long-history source with safeguards, incremental/resumable processing, and sanitized real-export compatibility.
3. Investigate remaining lost-POST [Issue #20](https://github.com/rua-den/playroom/issues/20) regression; existing reconnect draft-race fixes were released in PR #31 but old timeout remains open.
4. [Issue #9](https://github.com/rua-den/playroom/issues/9): authenticated app → SQLite → real Gemma4 trial, then separately authorized physical phone and VPS/DNS/Caddy deployment. Synthetic three-turn direct provider smoke test alone does not close B4.

The owner's prior synthetic provider-testing risk ceiling (USD 5) is **not** consent for private content transfer, automatic spend, default grant or infrastructure changes. Follow latest `origin/main` and repository `AGENTS.md` before new code.
