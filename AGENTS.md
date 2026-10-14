# Playroom agent instructions

## Model routing

- Use `gpt-5.6-sol` for orchestration: requirements, architecture, planning, coordination, review and final verification.
- Always delegate implementation that writes or refactors code to `gpt-5.6-luna`, with `medium` reasoning unless the task explicitly requires another effort.
- The orchestrator must review the diff and run relevant verification after the coding agent finishes, before claiming completion.
- If the required Luna model is unavailable, stop implementation and tell the user. Do not silently substitute another model or write implementation code in the orchestrator.
- Documentation, planning and review can be performed by the orchestrator.

### Owner-authorized temporary fallback — Issue #2 only

The owner asked to continue directly in the ChatGPT session on 2026-10-14 after being told that Luna delegation was unavailable. For [Issue #2](https://github.com/rua-den/playroom/issues/2) only, that instruction authorizes a direct ChatGPT implementation fallback if Luna cannot be dispatched. Keep this explicit exception narrowly scoped to the recovery fix and its tests; do not infer general model-routing changes for future tasks. The implementing assistant must review the exact diff, perform every verification available, explicitly list anything unrun, and never claim B1 PASS without running focused and full relevant tests. The normal Luna-only routing remains the default elsewhere.

## Read order

1. `README.md`.
2. `docs/superpowers/specs/2026-10-12-personal-playroom-design.md`.
3. `docs/superpowers/specs/2026-10-12-runtime-ai-context-policy.md`.
4. `docs/superpowers/plans/2026-10-12-personal-playroom-implementation-plan.md`.
5. `docs/superpowers/reviews/2026-10-12-personal-playroom-plan-review.md` and `docs/references/playrooom-style-and-evaluation.md`.

On the user's Windows host, read `C:\Users\huy.nguyen\.codex\RTK.md` and prefix shell commands with `rtk` as instructed there. Do not assume this host-specific path exists on CI or the VPS.

## Product and data rules

- Mobile-first private web app, accessible through the user's existing VPS.
- The current proxy is **Caddy**, confirmed directly by the user. Old wedding-online Nginx/Certbot docs do not override that fact.
- Verify live OS/architecture/resources, Python/systemd, ports, Caddy configuration and domain before deployment. Do not treat example values as production settings.
- Canon, approved memory, scene, transcript and summaries are separate; retain provenance and immutable state checkpoints.
- Never silently overwrite user-approved canon, truncate required context or import data from an abandoned future branch.
- Generation reconnect must recover the existing job/idempotency key without automatically resubmitting provider requests.
- Do not invent the missing initial history of the user's `playrooom` chat.
- Preserve memory/style/checkpoints across runtime-model changes. Quality/economy share data; free-only cannot silently call a paid fallback. Director outputs reference IDs, not authority to change canon.
- Normalize provider refusal/quota/incomplete separately; partial or max-token output cannot auto-commit as a completed turn.

## Scope and operation

- Follow delivery checkpoints so a usable phone trial can precede full branch/import/release automation.
- No real paid AI calls in automated tests. Use the fake provider; live trials require user-controlled configuration/action.
- Keep Playroom's service, data, secrets, releases and domain configuration separate from wedding-online.
- Production publication and infrastructure changes require the user's authorization for that action; a docs task does not authorize deployment.
- Never put API keys, SSH private keys, session credentials, production databases, exports with private story data, or third-party APK bundles in Git.
- Run verification appropriate to the change. For docs-only work, check links, consistency and diff; do not claim application tests/build/deployment passed.
