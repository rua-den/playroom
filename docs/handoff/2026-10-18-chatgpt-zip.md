# ChatGPT ZIP discovery checkpoint — 18 October 2026

## Scope and starting state

Starting main: `466b336`, after the [Legacy acceptance checkpoint](2026-10-18-legacy-acceptance-followup.md). Work reuses the clean isolated checkout at `D:\stu\worktrees\playroom-import-followup`, branch `feat/issue27-export-import-20261018`. Current owner routing: Luna medium implements/tests, Sol reviews and independently verifies.

This is the next bounded slice of [#27](https://github.com/rua-den/playroom/issues/27): local ZIP/numbered-JSON discovery, one explicitly selected conversation through existing authenticated preview/import, async UI ownership, and 125-turn synthetic acceptance. The existing current-path parser, immutable source archive, separate checkpoint review and generation restrictions remain authoritative.

The owner supplied the same local Legacy bundle as before. Controlled shape inspection confirmed Legacy format without an official ChatGPT mapping; it is not an official-export compatibility fixture. Do not copy its contents into code, logs, tests, GitHub or a provider. Sanitized official-export acceptance remains unverified.

## Design decisions

- Keep the whole account archive on the browser, preserving the existing JSON import privacy contract. ZIP discovery is local; only one owner-selected conversation reaches the app server. No multipart account-archive upload or provider invocation.
- Initial limits: 20 MiB total selected input, 512 ZIP entries, 60 MiB declared/actual total decompressed data, 20 MiB per conversation JSON entry and selected conversation. Reject unsupported/unsafe ZIPs explicitly; never extract paths, execute content, or silently truncate.
- Support safe nested conversation JSON names and numbered variants. Ignore account metadata/attachments rather than treating them as story. Exact duplicate source IDs may collapse; conflicting duplicates fail visibly.
- Bind file reads, preview/error results and import callbacks to source/mount identity. Reset confirmation on file/thread replacement. An already-authorized import keeps its original source/config/idempotency key and is neither cancelled nor automatically retried.
- Preserve original selected JSON objects and historical text/roles. Do not claim new per-turn timestamp storage, chunked progress, Markdown/TXT fallback or whole-account restoration in this slice.

## Work ledger

- [x] Local guarded ZIP/JSON reader and regression tests; owner `issue27_zip_reader`.
- [x] ChatGPT importer integration and deferred-result regressions; owner `issue27_zip_ui`.
- [x] 125-turn restart/idempotency and real Chromium ZIP import/review/owner-summary/new-fake-Send acceptance; owner `issue27_zip_acceptance`.
- [ ] Independent diff/security review, parent full checks and exact PR/merged-code CI.
- [ ] Update release evidence and current README/handoff pointer.

The reader produces `readChatGptExportFiles(files: File[]): Promise<ChatGptConversation[]>`; the UI consumes it without a backend contract change. The browser gate consumes the built UI and existing authenticated JSON API. The three workers own disjoint files; all commits use explicit paths and never amend shared history.

## Remaining #27 scope

Keep #27 open for durable bounded chunk/resume imports, larger-source handling, remaining preview/correction/provenance requirements and a sanitized real-export sample. The synthetic 125-turn case verifies the current bounded import path; it is not evidence of resumable processing or universal export compatibility. #20 remains open for the prior intermittent recovery gate. No live provider, phone or VPS work is authorized by this checkpoint.

## Supported ZIP profile and review ruling

The initial reader supports classic single-disk ZIP with stored/DEFLATE entries and UTF-8 names, including safe nested `conversations.json`, `conversations-1.json` and `conversations_1.json`. Encrypted, ZIP64, data-descriptor and unsupported-method archives fail closed; extract a trusted export locally and choose its JSON files if its ZIP profile is unsupported. The 60 MiB declared budget includes all ZIP entries; actual output is counted for the conversation entries that are inflated. Ignored account metadata and attachments are not inflated. Entry counts and output budgets are shared across the selected ZIP files.

Independent review found a low severity decoder limitation: fflate may accept unused bytes after a valid DEFLATE stream inside the declared compressed payload. Ruling: tolerate that padding rather than couple to private library state or add another DEFLATE parser. The central/local metadata, decoded size, output budget and CRC still agree, and the padding cannot change imported text, execute a path or trigger an upload/provider call. This is not strict validation of every compressed-stream encoding or a universal ZIP compatibility claim.

Official references: [OpenAI export](https://help.openai.com/en/articles/7260999-exporting-your-chatgpt-history-and-data), [numbered JSON export files](https://help.openai.com/en/articles/9106926-transfer-exported-conversations-between-chatgpt-accounts), [fflate upstream](https://github.com/101arrowz/fflate). These establish the ZIP/JSON input family, not a stable official mapping schema.

## Verification in progress

At `57d3ce4`, parent fresh checks: backend **356 passed / 1 Windows POSIX-only skip**; frontend **136 passed / 3 skipped**; locked install, typecheck, production build, compileall and raw full-range diff checks passed. Initial production dependency audit flagged fflate 0.8.2 advisory [GHSA-px8p-9vwx-vf98](https://github.com/advisories/GHSA-px8p-9vwx-vf98); the pin/lock was upgraded to **0.8.3** and fresh locked install/audit reports **zero vulnerabilities**. The affected `unzipSync` API is not used.

Independent Sol final review at `57d3ce4`: no blocking findings; focused frontend **27 passed**, reader **15 passed**, backend import **12 passed**, typecheck/build/audit/raw diff passed. The padding limitation above remains explicit. Reviewer did not independently run Chromium.

Regression evidence is distinguished from test-first history: the initial new reader suite failed on its absent module; later guard tests were mostly added after implementation. A retrospective run of the final 15 tests against exact reader `1c17770` produced five actual failures (pre-read size, shared entry count, standard DEFLATE flags, false-size output, shared declared-output/EOCD checks), and restoring current code returned 15 passed. UI StrictMode and oversized selected-conversation tests had actual failures before their fixes; the initial six ZIP UI tests all failed before reaching deeper async cases because the old component rejected ZIP.

The first parent full Chromium run passed ZIP discovery but failed in the new test at `select_option(label=re.Pattern)`: Playwright expects a string/value. `57d3ce4` fixes the test by locating the option by title and selecting its actual value. The next run passed discovery/import/reload/review but the post-review Send did not produce turn 126. Retained diagnostics and a separate parent TestClient probe established the exact cause: text preview `ready`, **3427 / 7488** estimated input tokens, but execution failed with `STATE_CONFLICT: Required narrator context exceeds the configured input budget` before any provider call. The complete wire request exceeds the verified budget even though the text-block preview fits; no cap or history was changed.

The final browser acceptance asserts that fail-closed case exactly, then uses the existing owner-authored, source-covered summary UI before a new explicit Send. All 125 original turns/source stay preserved; this is not automatic summarization, a provider retry, or resumable import processing. The preview/wire-budget discrepancy remains a known usability limitation.

Parent full Chromium at `cd8ab6f` failed in the older stale-409 scenario before reaching ZIP: four jobs committed, POST returned 409, stale route hit once, by-key GET started but had no response for the 12-second assertion period, Send remained disabled and provider calls stayed at four. The network wait is observed; its underlying cause remains unresolved. Agent runs also encountered the older lost-POST failure (third synthetic story Send, expected three turns but two remained), and new harness selector ambiguities/stale count assertions while constructing the ZIP case. These are not erased or reported as clean first runs.

Parent then executed the **exact current ZIP scenario block from the repository** in a fresh real Chromium/demo assembly with a temporary DB, bypassing only the unrelated earlier gameplay scenario setup. At `3f5629c`: **PASS** for local ZIP discovery, selected-only preview/import, 125 original turns, reload/review, exact wire-budget refusal with zero provider calls, manually authored approved `narrator_only` summary covering the first 117 source revisions, unchanged 125 revision IDs, a new explicit Send producing turn 126, exact new action/fake narration and reload. Zero external requests; summary creation did not dispatch a provider; exactly one fake provider call followed the final explicit Send. This is isolated feature acceptance, not a passing local full gate or real model acceptance.

Final Sol test-diff review through `3f5629c` resolved campaign-scoped diagnostic provenance and the immediate pre-Send no-auto-dispatch proof; no blocking finding remains. Remote exact PR/full merged-code CI is pending.
