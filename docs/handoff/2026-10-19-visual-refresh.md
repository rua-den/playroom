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

## Integrated implementation and local verification

Fetched and merged current remote main `90b143742f87ea176535318e2bcdb026991c88c0` through normal merge `8b4dda6`. PR #47 bounded/resumable ChatGPT imports, #48 narrator agency rules and #49 synthetic 156-chapter-scale import tests are preserved. Backend application sources, import client/types and ChatGPT import component have no divergence from that main. No further live inference workflow was dispatched.

Final implementation head: `6e61d29654f288ac7fb3df9950550cd7fbd4c094`. The selected story comes first in library DOM order without mutating server order; mobile story actions remain available in a modal; context actions wait for a projection. Settings sections retain mounted drafts, and the compact composer notice explicitly explains that demo responses can repeat and changing the model does not enable real AI. Shared editor selects now use the same themed controls.

Root verification: 166 frontend tests passed with three existing skips; 392 backend tests passed with one skip. Typecheck/build, backend compilation and diff whitespace checks passed. After the final CSS change, root rebuilt and reran the locked Playwright 1.56.0 Chromium gate: both synthetic B3 and real local app assembly with a fake provider passed, exit zero. Coverage retains 125-turn bounded import, review/consent, reconnect, persisted story/draft, responsive visible navigation, modal focus/geometry and save toast checks. Root inspected synthetic light/dark login, library, chat, settings, context and management screenshots at 375/757/1280px as applicable; no private localhost screenshots were taken. Independent Sol review cleared final source head.

Read-only primary counts before updating the app were two campaigns, seven turns/revisions, one Legacy source and one review checkpoint. The extra turn predates the update. Keep `.playroom-demo`, `.playroom-live`, private source data and untracked `playroom/` intact. Updating primary now also requires restarting its demo backend because the newly integrated main includes backend changes. Preserve its data directory and loopback port 8001; do not open or refresh the user's browser automatically.

Release still requires exact PR-head and merged-main CI. Record those immutable run URLs in the PR/final release report. Local verification does not claim real private-export compatibility, real provider output quality, physical-phone acceptance or deployment.
