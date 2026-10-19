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
