# Warm reading UI — 2026-10-20

The owner requested a review/refactor of the current interface and approved “Đổi sang tông giấy ấm, phong cách đọc sách”. Work starts from `d065f39ade9971d005bd2e22655777ca7a2cac18` on `codex/warm-reading-ui`.

## Scope

- Warm ivory paper in light mode; warm charcoal and brass in dark mode. Existing light/dark/system preference remains.
- Offline Georgia/Cambria serif for story prose and book titles; existing system sans for controls, forms and settings.
- One shared **Truyện và tác vụ** modal for selecting stories, creating and importing, on desktop and mobile. Remove duplicate select, recent-story list and direct reading-page import actions. Keep direct create/import actions in the library and existing context button names.
- Reading column dominates; composer textarea now spans its available width. Compact sticky composer retains all existing generation controls.
- At viewport heights of 500px or less, the composer follows normal document flow so landscape reading and focused input remain reachable without covering the story.
- **Đọc tiếp** is the primary library action for the current story. Create is secondary when a story is selected; imports and deletion are quiet. Cards keep a consistent grid size.
- No new dependencies, external fonts, images, provider calls, backend production changes or data migrations.
- Existing favicon and installed-app metadata use the warm palette without changing icon geometry.

## Implementation verification

The new navigation/draft regression first failed against the old UI because the duplicate `Truyện hiện tại` select was still present. After implementation it passes and checks that opening grouped actions, creating then dismissing, and opening context preserve the mounted unsent draft and avoid refetching the story.

- Focused AppShell/CampaignHome: **44 passed**.
- Full frontend: **197 passed, 3 existing skips**, 19 test files.
- TypeScript and Vite production build: passed.
- `git diff --check` and Python syntax check of the changed browser test: passed.
- Form-control border contrast: minimum **3.24:1** across canvas, surface, inset and raised surfaces in both palettes. Normal text tokens meet **4.5:1**.
- Orchestrator's baseline backend suite: **461 passed, 1 Windows skip**; compile passed.

Final browser review identified a short-viewport overlap at 812×375. A new real Chromium regression first failed with transcript bottom **362.14px** and composer top **199px**. After the short-height CSS rule, the same narrow test passed geometry, unsent draft preservation, input focus/reachability and restored portrait sticky behavior. The updated build/typecheck and manifest JSON/SVG XML parse also passed. The initial probe using `.venv` could not import Playwright; the bounded retry used the pinned `uv --with playwright==1.56.0` runtime successfully.

Browser tests now exercise the same grouped navigation at every width while retaining selected-story, action availability, focus return, draft, modal, import and recovery checks.

## Orchestrator verification

Independent review found no blocking issues. The orchestrator reran the full frontend suite (**197 passed / 3 existing skips**), typecheck and production build, and inspected synthetic light/dark reading screens. Manual geometry checks at 320, 375, 768, 1024 and 1440px found no horizontal overflow. The 812×375 overlap was independently confirmed fixed: composer top **402.14px**, after transcript bottom **362.14px**.

The complete pinned Chromium command passed all three flows after the final correction: synthetic gameplay/reconnect/ChatGPT and Legacy import-review/save toast; desktop/mobile library trash/undo/restore; and assembled local runtime fake Send/commit/reload. No failed full Chromium attempt occurred in this change; the deliberate short-height RED probe above remains recorded separately.

This local report does not claim physical-phone, live-provider or deployment acceptance. Exact-PR and merged-main CI evidence is recorded on the release PR; it is not inferred from the local results above.
