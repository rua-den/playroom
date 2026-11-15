# Synthetic story quality scorecard — 21/10/2026

This is a privacy-safe human review of existing **synthetic** long-story runs. It does not use BANGTAN/Henn private canon and does not make new provider requests.

## Evidence reviewed

- GPT-OSS comparison job `118201210943` in workflow run `39293792814`: 24/24 synthetic chapters (157–180), six scenes, four NPC profiles.
- Gemma4 comparison job `118204936015` in workflow run `39294927711`: the same 24-action synthetic fixture and story checkpoint.
- Issue #61's earlier manual notes and the production regressions derived from public synthetic output.
- Current production safeguards merged after those historical runs:
  - #77 player-agency guard;
  - #78 NPC `narrator_only` / `known_by` knowledge fence;
  - #79 exact-clock grounding guard.
- Gemma's historical fenced-JSON compatibility defect was later fixed separately by #66. Therefore the old Gemma format warnings below are parser-history evidence, **not** a current model-quality verdict.

The old runner is adapter-only, not the complete Playroom database application. PR #42 separately proved one real authenticated app + SQLite + provider + commit + restart/reload path.

## Mechanical observations from the archived logs

| Observation | GPT-OSS 120B | Gemma4 31B |
|---|---:|---:|
| Completed synthetic turns | 24/24 | 24/24 |
| Mean narrative characters | 1,044 | 1,019 |
| Prompt tokens across 24 turns | 66,898 | 58,024 |
| Completion tokens across 24 turns | 15,386 | 7,680 |
| Heuristic agency warnings in this comparison run | 5 (Ch.162, 165, 166, 167, 177) | 0 |
| Secret-knowledge heuristic warnings in this comparison run | 0 | 0 |
| Historical format warnings | 0 | 24/24 fenced responses |
| “ánh sáng” in printed excerpts | 19 | 0 |
| “nhẹ nhàng” in printed excerpts | 14 | 1 |
| “gật đầu” in printed excerpts | 8 | 2 |
| “không khí” in printed excerpts | 8 | 4 |

These phrase counts are simple observations from the excerpts printed by those exact jobs, not a universal benchmark.

## Human review

### Player agency

**GPT-OSS: weak / inconsistent.** It often restates a player-authored movement safely, but several turns add extra Lan movement, body language or state around the submitted action. The earlier long run also produced a confirmed case where an intention to inspect a drawer became a completed drawer-opening/search action. This is why #77 now validates production output before `candidate`.

**Gemma4: stronger in this fixture.** The archived comparison did not trigger the old agency heuristic. Its prose more often leaves the player's next act open and lets NPCs react. This is not proof that Gemma can never steal player actions; #77 applies regardless of model.

### NPC voice differentiation

**GPT-OSS: mixed.** NPC roles are recognizable, but dialogue frequently converges on polite evidence-checking and generic helpful advice. The surrounding prose repeats the same lighting, calmness and “careful investigation” texture across unrelated scenes.

**Gemma4: stronger.** Khoa's impatient joking, Bình's defensive/cautious evidence focus, Vy's energetic speculation and Mai's rules/consent framing are more visibly separated in the archived prose. The voices are still archetypal rather than deeply individualized, but they are easier to distinguish without speaker labels.

### Repetition and scene texture

**GPT-OSS: weak.** The simple excerpt counts support the manual impression that it leans heavily on ambient light and soft/gentle staging. This makes different rooms feel written from the same template.

**Gemma4: better, still formulaic.** It repeats facial expressions and “pause / think / react” beats, but relies less on the same lighting vocabulary and gives more scene-specific behavior.

### Grounded continuity

**Both remain mixed.** Historical outputs sometimes add precise times, object provenance, storage locations or other details that were not established by the player. Gemma's archived photo-room sequence, for example, invented precise timing claims while reasoning about evidence. Production #79 now blocks unsupported exact `HH:MM` values, while #78 blocks restricted NPC facts. Generic semantic claims such as arbitrary prop placement are **not** considered solved; fail-closing those with broad regexes would create unacceptable false positives.

### Structure / parser reliability

The raw historical numbers favor GPT-OSS because it returned directly parseable structured JSON in that comparison while Gemma wrapped all 24 responses in fences. That comparison is obsolete for current parser compatibility: #66 subsequently added strict acceptance for one complete JSON fence while preserving cast/version validation. Structure should therefore be re-evaluated during ordinary owner play, not used as a reason to prefer GPT-OSS today.

## Current product recommendation

For **narration quality**, prefer **Gemma4 31B** as the first model to try in owner play. The archived synthetic prose is less repetitive, has clearer NPC voice separation, and showed fewer player-agency symptoms than GPT-OSS in the same 24-action fixture.

Keep the model-independent server fences enabled regardless of provider. A model response is not trusted merely because it is fluent or schema-valid.

GPT-OSS remains useful as a comparison/fallback model, but the archived long-story evidence does not support calling it GPT-equivalent for this roleplay style.

## What is and is not complete

Completed:
- high-confidence production player-agency enforcement;
- restricted NPC knowledge enforcement;
- exact-clock grounding enforcement;
- same-fixture synthetic long-story comparison and human scorecard;
- authenticated real-app provider path previously proven in #42.

Still intentionally manual / observational:
- subtle unsupported spatial/state assertions;
- humor taste and emotional naturalness;
- whether real BANGTAN characters feel in-character over long play;
- physical-phone UX;
- official ChatGPT-export acceptance for #27.

Do not send private BANGTAN material to a cloud provider merely to improve this scorecard. The next useful quality evidence should come from owner play with reviewed data and normal explicit Send actions, not an automated private-story benchmark.


## 22/10/2026 live authenticated-app follow-up

Codex #83 changed narrator guidance, so prose quality was re-verified with real `gemma4:31b-cloud` output through the authenticated Playroom HTTP + SQLite path. All trials below used only the same synthetic Lan/Vy fixture, at most three provider requests, no retry, purchased-credit-zero preflight, and no private BANGTAN/Henn data.

### Stage A — verify #83 instead of trusting prompt wording

Run `39765453148`, live job `119779786075`, main after #86: 3/3 turns committed and the existing agency/knowledge/cast checks were clean. Human review still found generic stage direction and repeated opening shape: turns 2 and 3 both began with variants of `Vy nhìn ... rồi ...`. The existing checker only caught identical openings, so it missed this repetition.

### Stage B — explicit voice/style + opening-shape diagnostics

#87 merged as `60f109985e069c5f978d1f278ab1e12e829ca1a0`. It:
- made the anti-repetition narrator guidance concrete without hard-rejecting style;
- gave synthetic Vy explicit traits/voice and the campaign an explicit youth-story style;
- added `repeated_opening_stem` and stock-stage observations.

Run `39766598161`, live job `119783595280` showed a clear style improvement: openings varied and Vy's dialogue became shorter, drier and more character-specific. Human review then found two deeper issues the older checks missed:
- Vy invented unsupported testimony: `Lúc nãy tôi thấy cậu cất vào đấy mà`;
- narration assigned the player an observable emotion: `khuôn mặt đầy lo lắng của Lan`.

### Stage C — player-emotion guard + sourced NPC observation guidance

#88 merged as `83b29b595bbe93bda843eed165e1c7f4a77e3c3f`. High-confidence narrator-authored player emotion cues now fail closed as `PLAYER_AGENCY_VIOLATION` unless the player authored that emotion. NPC memories/observations about player actions are instructed to require context evidence; potential first-person witness claims are surfaced for human review rather than hard-blocked, because legitimate transcript-backed memories must remain possible.

Final run `39767494310`, live job `119786579721`: **PASS 3/3**, exactly three provider POSTs and three committed turns. The app reserved USD `0.01476000` under the test cap; this is a Playroom reservation, not a provider invoice.

Human-reviewed final outputs:
- Turn 1: Vy remembers only that the paper had been in the box, then jokes/speculates that Lan might have discarded it. This is NPC suspicion, not narrator-authored player history.
- Turn 2: Lan says she will inspect the drawer; Vy waits. The model does **not** perform the drawer inspection for Lan.
- Turn 3: Vy agrees to keep the matter from Bình without assigning Lan an emotion, thought or internal state.

Final diagnostics reported no player-agency, absent-speaker, restricted-knowledge, repeated-reply, repeated-opening, repeated-opening-stem, or player-observation-claim warnings. The final prose is materially less templated and Vy's dry/direct voice is more distinct than the #83 baseline.

**Verdict:** short synthetic authenticated-app narration acceptance is PASS for this fixture. This does not prove arbitrary semantic grounding, long-range character quality, or private BANGTAN characterization; those remain owner-play observations, and private story data should not be uploaded merely to extend this benchmark.
