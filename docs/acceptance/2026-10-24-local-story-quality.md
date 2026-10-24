# Local synthetic story quality — 24 October 2026

**Verdict: incomplete acceptance; useful quality evidence with a confirmed agency defect.** The owner authorized use of the machine's `ollama_key`. These runs used invented Lan/Vy/Bình data through authenticated Playroom APIs, SQLite, persisted trial authorization, the production Ollama adapter and normal candidate/commit validation. They did not use private story data, a physical phone or the VPS.

## Live evidence

Base: `ede0fca375c5739ffceb735926026942faece9ee` (PR #90). Runner: local commit `7c1b1af`; second run additionally used prompt/report fix `d0acb00`. Model: Ollama `gemma4:31b`.

| Run | Provider POST attempts | Committed turns | Result |
|---|---:|---:|---|
| `live-01` | 1 | 0 | `SCHEMA_INVALID`: model shortened the selected character UUID; server rejected it. |
| `live-02` | 18 | 18 | Stopped before dispatch of turn 19; failed job stored generic `PROVIDER_ERROR`. |

The first response returned `00000000-0000-4000-8000-0000000001` instead of selected `00000000-0000-4000-8000-000000000001`, while copying the profile version correctly. The prompt was strengthened to require the same-row ID pair byte-for-byte, including every zero. Validation remains strict. The later 18 valid responses are stochastic evidence, not proof the wording fixes ID reliability generally.

For `live-02`, the durable dispatch ledger contains 18 attempts while the app reserved 19 jobs. No provider output was saved for job 19. A subsequent separate read-only balance check returned HTTP 429. This supports a metadata rate-limit explanation, but the original pre-dispatch exception was not classified, so its exact cause remains unproven. The run was not resumed and no failed request was automatically retried.

The script's current `status: stopped` is also its conservative default during execution; only normal loop completion becomes `completed`.

## Human reading of all 18 committed responses

Scores are subjective for this narrow fixture, not a universal model benchmark.

| Dimension | Score | Evidence |
|---|---:|---|
| Vietnamese dialogue | 3/5 | Mostly readable, short, teasing replies; occasional stock phrasing. |
| Character consistency | 3/5 | Vy stays blunt and sarcastic, but switches from “tớ” to “mình”; motivation remains mostly curiosity. Only one speaking NPC was tested. |
| Object/scene continuity | 4/5 | Box/paper state and the shop-to-courtyard move remain recognizable across the approved midpoint summary. |
| Variation and progression | 2/5 | Ten of 18 turns triggered the opening-stem diagnostic; gestures repeatedly use glances, raised eyebrows, crossed arms and waiting. No exact repeated reply or paragraph was detected. |
| Player agency | 2/5 | Turn 8 asserts Lan's unprovided emotional expression, despite passing the then-current guard. |

Representative passages:

- Turn 3 answers the player's joke: “Khai gì mà khai. Cậu cứ làm như mình đang thẩm vấn tội phạm không bằng.”
- Turn 8 narration invents “khuôn mặt đang phân vân của Lan.” The submitted action only folded the paper and asked whether hiding it was fair. A question does not authorize the narrator to assign a facial expression or emotion.
- Turn 10 adds “Ánh nắng buổi chiều…” although no time of day was established. The existing exact-clock guard does not certify all ambient/spatial claims.
- Turn 14, asked for Bình's restricted drawer code, Vy says “Không biết.” She does not disclose `Z83`.
- Turn 18 reduces Vy's motivation to watching where the game leads, then returns to waiting for Lan. Fluent dialogue alone does not establish rich interaction.

There was no observed disclosure of the narrator-only swapped-paper fact or Bình-only code, and Bình never became a speaking participant. The old heuristic reported zero agency warnings, illustrating why that scanner is only diagnostic: human reading found the turn-8 miss.

Turns 11–18 selected the approved summary and courtyard scene. The summary was deliberately curated from player actions/requests and did not retain every generated NPC statement. This is **not** proof of complete long-term NPC memory. The fixture also repeats physical box/paper operations, limiting conclusions about open-ended plot development or multi-character voice separation.

## Spending bounds and evidence handling

The round used a USD 0.20 aggregate risk envelope within the owner's earlier USD 5 synthetic-testing authorization. Each job reserved at most USD 0.00912000 with a 60,000-byte wire-input bound and 1,800 output tokens. Total persisted reservations across both runs: **USD 0.18240000** (20 reservations, including the undispatched failed job).

The 18 successful responses reported 70,767 input tokens and 4,311 output tokens: **USD 0.01163178** using [Ollama's published pricing](https://ollama.com/pricing) of USD 0.14/M input and USD 0.40/M output tokens. Usage for the first rejected response is unknown, so there is no complete round cost. Reservations and token estimates are not an invoice. Balance preflights are snapshots; included-credit checks do not imply a provider billing guarantee.

Runtime reports, the dispatch ledger and full synthetic transcript remain outside Git. Dedicated runtime directories also contain the credential store and must stay private; never upload the database, secret directory or whole run folder. No key was put in source, command arguments or this report.

## Follow-up and limits

The reviewed source changes retain strict UUID validation, add a regression for the observed shortened ID, and preserve bounded rejected output for inspection. The possessive player-expression miss now has policy and candidate/commit regressions; the shared guard recognizes the observed “đang phân vân” construction without assigning nearby NPC emotion to the player. This is a targeted high-confidence check, not complete semantic agency detection.

Future preflight exceptions persist only their type and HTTP status, never their URL, message, headers or credential. An offline 429 regression proves zero provider POSTs, zero commits and no retry. The historical live reports remain unchanged. The narrator prompt already discourages repetitive staging, so no duplicate style instruction was added to pretend that problem was solved.

The fixes were tested offline after the live observations. No additional provider run validates the final agency/diagnostic patch; this report does not retroactively apply that patch to the 18 committed responses.

Do not call this a 20-turn PASS, a physical-phone test, private-character acceptance or deployment validation. The next quality checkpoint should exercise varied goals and multiple NPC voices; production safeguards still need human review for subtle agency and unsupported scene facts. Issue #27's real sanitized export acceptance and Issue #9's physical-phone/deployment gates remain separate.
