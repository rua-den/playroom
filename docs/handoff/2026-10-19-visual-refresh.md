# Playroom visual refresh — 19 October 2026

Owner requested a complete visual refactor after the modal/toast release, rather than another isolated layout correction. Base main: `154abeb1599089e7a5446426caffeaa536a1d727` (PR #46). Reuse `D:/stu/worktrees/playroom-import-followup`, branch `feat/ui-visual-refresh-20261019`. Owner-authorized Luna 6 medium implements; root orchestrates, reviews and independently verifies.

Apply installed `C:/Users/huy.nguyen/.codex/skills/frontend-design/SKILL.md`. An optional style question was offered; after sufficient response time, root stated the default modern reading-room direction. Scope: library, navigation, reading/chat/composer, login, Settings and shared form/modal styling. Keep APIs, generation/recovery state machines, spending controls, approval boundaries, owner isolation and saved data intact.

## Design direction

Graphite and muted jade, with a coordinated light theme. Dark core tokens: canvas `#1B2428`, surface `#222E33`, inset `#172126`, text `#ECF2F0`, muted `#A2B3B5`, accent `#7FC7B5`. Light equivalents: `#F3F7F6`, `#FFFFFF`, `#E9F1EF`, `#1D3434`, `#556E70`, `#245E55`. Use local Segoe UI/system typography, restrained 30–36px headings, 17px/1.75 reading text around 66ch, and 8/12/16/24/32 spacing. Refine these choices where visual verification or contrast requires it.

Replace accumulated CSS overrides with a coherent token-driven stylesheet. A quiet rail on wide screens and compact mobile navigation should keep the story dominant. Library entries should feel like a shelf through restrained book-spine or code-native icon details, using only actual saved title/status/date metadata. Avoid invented chapter/turn counts, prose excerpts or generated private covers. Auth, buttons, fields, tabs, status notes, toasts and modals share the same type/spacing/color system. Settings should group connection, roles and spending controls, progressively disclosing technical detail while keeping demo/runtime and consent information clear.

```
wide:    quiet navigation rail | library shelf / reading column
narrow:  compact navigation    | story first, useful composer
modal:   persistent title/close, vertically scrolling grouped form
```

The design review must judge the overall hierarchy and actual screenshots, not just new hex values. Keep all content legible in dark/light, critical controls within the viewport and checkbox/radio sizes compact. No network font, new package, external artwork, provider call or private-data screenshot is needed.

## Verification boundary

Existing functional browser coverage remains authoritative: library/current-story persistence, unsent draft retention, import review and consent, explicit fake Send/reconnect, modal focus/isolation and save feedback must continue to pass. Use actual synthetic login/library/chat/form screens at 375px, 757px and desktop, in both themes, for visual critique. Add meaningful behavior tests only where navigation or disclosure changes; do not mirror cosmetic CSS in unit tests or weaken existing assertions.

Root reviews all implementation diffs, runs full frontend/typecheck/build and both locked Chromium flows, obtains an independent code review, then requires exact PR-head and merged-main CI before delivery. Primary localhost 8001 remains on main until the reviewed release is ready. Before this work, read-only local counts were two campaigns, six turns/revisions, one Legacy source and one review checkpoint; preserve the source/data directories and primary untracked `playroom/`.
