# Modal UI refactor — owner feedback, 19 October 2026

Owner asks that auxiliary screens open as proper modals and requests finding, installing and using an online design skill. Installed and read `C:/Users/huy.nguyen/.codex/skills/frontend-design/SKILL.md` from https://github.com/anthropics/skills/tree/main/skills/frontend-design using the system skill-installer. It is available for later turns; its design guidance has been applied to this plan.

## Diagnosis

The supplied screenshot shows Settings clipped horizontally and anchored at the bottom-left. Existing `.mobile-overlay` uses `align-items: flex-end` without horizontal centering, and `.mobile-sheet` is capped at 420px at every viewport. Intrinsic fieldset/select widths exceed the narrow content box. The whole sheet scrolls, carrying its title and close button out of view. Current Settings and Context duplicate focus-trap effects; Create and Import replace the underlying story instead of opening as modals.

## Bounded design

Reuse one accessible modal primitive for Settings, Context (profiles, memory, scene), Create, ChatGPT Import and Legacy Import. The reading/library view remains mounted behind it, preserving the current story and unsent composer. Keep save/send as direct actions. Retain current explicit close semantics; do not add backdrop dismissal that can lose a draft.

Desktop: centered panel around 720px wide, up to 900px where context needs space. Small screens: nearly full viewport with safe margins. Use a fixed header with left-aligned title and right-aligned close control, then a separate vertically scrolling body. No horizontal scrolling or clipped controls; fieldsets, flex children, inputs and selects need shrinkable width constraints. The modal must fit the dynamic viewport. Toast remains above the overlay.

The primitive owns background inertness, body scroll locking, visible enabled focus targets, Tab/Shift+Tab containment, Escape, and restoring the actual invoking button. Preserve owner/async identity guards and avoid duplicate traps. No new dependency, network font, backend change, credential/account migration, automatic provider dispatch or import approval.

## Visual direction and critique

Quiet reading room, with controls subordinate to the story. Tokens: ink `#171614`, panel `#211d19`, inset `#151311`, parchment text `#f6f1e9`, muted `#aaa093`, restrained brass `#d6b879`. Segoe UI/system typography supports Vietnamese. Use 16px/24px spacing, 12px controls and 18px modal corners, readable labels and consistent light-theme equivalents. Avoid decorative all-caps labels, repeated nested cards and motion unrelated to a user action. First pass considered merely widening the old sheet; it fails the owner's consistent-modal request and leaves scrolling/focus duplication, so use the shared primitive instead.

```
           background library or current story (inert)
        +--------------------------------------------+
        | Settings / Create / Import / Context  Close |
        +--------------------------------------------+
        |                                            |
        |  grouped form content, full-width controls  |
        |  vertical body scroll only                 |
        |                                            |
        +--------------------------------------------+
                     toast above overlay
```

## Verification and execution state

Add behavior regressions before implementation: modal opens from each action, background unavailable, Escape/Tab/restore, unsent current-story input retained after closing. Synthetic browser checks at 375px, 757px and desktop must prove panel centering/bounds, no horizontal overflow, visible header/close after body scroll, form labels and light/dark readability. Root reviews actual synthetic screenshots and final diff, then runs full frontend/typecheck/build and both locked Chromium flows. Complete exact PR-head and merged-main CI before delivering the primary local build.

Implementation was dispatched to required `gpt-5.6-luna` medium but both shell and editor agents returned **Selected model is at capacity** before this refactor began. Latest human routing forbids root code implementation or a silent model substitution. No modal code has been written or delivered. Finish outstanding toast corrections from `2026-10-19-save-toast.md` together with this work once required coding capacity or an explicit routing exception is available. Preserve the existing partial editor changes; do not mistake prior toast test evidence for proof of this unimplemented modal refactor.

## Completion update after owner-approved Luna 6

The owner explicitly approved continuing with **gpt-6-luna**. Luna 6 medium implemented the modal refactor and remaining toast corrections; root reviewed the diffs and an independent Sol review found no remaining Critical or Important findings after the toast timer correction. This section supersedes the blocked execution state above.

Shared modal surfaces now cover Settings, Context, Create and both import flows. They retain the underlying story/composer, use a fixed header and scrolling body, constrain form width and keep checkbox/radio controls compact. The primitive lazily mounts content on first open, restores inert/body overflow state and the invoking control, and filters hidden/disabled/collapsed focus targets. Create/import drafts survive manual close and reset after acknowledged success. Settings refreshes its panel on reopening. Toast feedback appears above the overlay, only after explicit mutation acknowledgement; failed saves retain their drafts, stale inline errors clear after a successful retry, and memory refresh failures do not misreport an acknowledged write. Hover/focus pauses preserve the remaining five-second success countdown. Owner-keyed remount and captured-old-API tests cover notification isolation.

Regression evidence: the previous build passed its original gate but failed the new desktop centering check at **x=16, width=420 in a 1280px viewport**. The final implementation passed the measured modal/overflow/header/focus/draft/provider-count checks at 375px, 757px and desktop. Root inspected synthetic dark/light Settings and Context/Create/ChatGPT/Legacy screenshots in `%TEMP%/playroom-modal-screenshots/`. Initial old-test failures came from missing native summary focus targets, trying to click an inert background Settings button, and a toast selector matching hidden retained overlays; assertions were adapted to the actual modal contract without skipping or loosening the invariants.

Root verification at production/test head `597c2b99ad4f5aeba892e7776be901db79943532`: **159 frontend tests passed / 3 existing skips**, typecheck/build passed, and the locked Chromium command exited zero with both **B3 synthetic + save toast PASS** and **Live local Chromium PASS**. Local backend baseline: **386 passed / 1 expected Windows skip**. Exact PR-head and merged-main CI evidence is recorded on the release PR; do not claim it from these local results alone. No new real-provider trial, private content transmission, schema/account/credential migration or automatic import approval is involved. Saved local data counts before delivery remain two campaigns, six turns/revisions, one Legacy source and one review checkpoint; primary untracked `playroom/` remains preserved.
