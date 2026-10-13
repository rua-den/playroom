# Chat and Story First: Product Design

**Date:** 2026-10-13
**Status:** Approved direction; awaiting user review of this design

## Goal

Make Playroom feel like a focused roleplay conversation: the player writes naturally, the narrator builds on the current scene, and durable character attribution stays reliable. The story should occupy the screen; operational details should appear only when they help the player take the next step.

## Product decisions

### 1. Reading and composing

- The campaign transcript is the primary surface, in a centered reading column with comfortable line length and clear spacing.
- Keep the chronological conversation. Distinguish player input, narrator prose, and character dialogue through modest visual treatment and existing role labels. Do not turn each segment into a dashboard card.
- Render the player's `**...**` spans as action or thought narration, and ordinary text as the player's dialogue, consistent with the current structured segment model. Preserve legacy turns that have no structured segments.
- Keep a single freeform composer anchored at the bottom of the conversation. Its hint is short: “Dùng **...** cho hành động hoặc suy nghĩ”. Enter submits; Shift+Enter inserts a newline.
- The composer has one gameplay button: Send. Clicking it records the player's turn and starts generation. During generation, the same button becomes a disabled progress state; do not add Cancel, Save draft, Commit candidate, or Commit and continue buttons to the play surface.
- On successful generation, validate the structured result and automatically commit the reply to the story. Render it as the next narrator/character turn without asking the player to approve it. A failed generation shows a concise error and re-enables the same Send button for retry.
- Collapse generation phase counts, usage/cost, and raw technical details under a per-turn details disclosure. Do not remove data or alter billing behavior.
- Keep campaign switching, Settings, memory/context inspection, and logout available through the existing app navigation, outside the main story flow.
- Preserve any unsent composer text across detail disclosure toggles. Do not change or synthesize saved campaign history as part of this work.

### 2. Narrator behavior

Improve the narrator's instructions using only the supplied, eligible context:

- Respond to the latest player action or dialogue and carry forward relevant scene, character, and memory details. Avoid generic atmosphere-setting when it does not connect to the current beat.
- Advance the scene with a concrete reaction, consequence, or change when context supports it. Avoid reusing the same sentence or opening across nearby turns.
- Preserve each selected character's established voice and knowledge. A character may speak only when selected and plausibly present in the current scene.
- Leave the player-controlled character's actions and thoughts to the player.
- Do not force A/B choices, quests, stats, or other game mechanics. Do not invent canon or present uncertain details as established facts; continue conservatively when context is insufficient.

These are generation instructions and review criteria, not a guarantee of prose quality. Any claim about model quality requires a later, separately authorized real-provider play trial.

## Existing invariants

- Keep the durable generation lifecycle and cancellation/epoch protections. Validate the structured result and character attribution before automatically committing a successful reply; the player does not need to approve every generated turn.
- Keep stable character IDs and profile-version attribution for dialogue. Never infer a missing speaker, invent IDs, or weaken selected-cast validation.
- Keep the raw player input and existing persisted narrative fields intact. Preserve exact legacy display for turns without structured segments.
- Keep context selection, canon precedence, memory eligibility, billing, caps, provider configuration, and campaign data behavior unchanged.
- Do not make a real model call, deploy, or publish as part of implementing this design.

## Acceptance criteria

1. The transcript is the visual focus, with the composer fixed at the bottom and a concise `**...**` hint.
2. The play surface has one gameplay button in the composer: Send. Enter submits; Shift+Enter inserts a newline.
3. The button shows a disabled progress state while generating; a successful, validated result is automatically committed and rendered. Failures re-enable Send and retain enough context for retry.
4. Existing action/thought, dialogue, narration, and character attribution render correctly, including legacy turns.
5. Generation internals are collapsed by default and remain inspectable without adding controls to the main play surface.
6. Narrator request guidance covers contextual response, concrete scene advancement, voice/knowledge, player agency, and avoiding repetitive generic openings without relaxing schema or context rules.
7. Regression coverage verifies send/progress/auto-commit behavior and narrator prompt contents; existing focused and full suites stay green.
8. No synthetic transcript, stored campaign data, cost policy, credentials, or provider behavior is changed.

## Out of scope

- New quest/choice/stat systems, character management changes, onboarding, or campaign data migration.
- Replacing the current generation architecture, context director, candidate state machine, or narrator output schema.
- Forcing generated actions on the player or changing the existing roleplay syntax.
- A claim that prose quality is solved without a separately approved real-provider trial.
