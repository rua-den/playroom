# Ollama Cloud Provider Implementation Plan

## Goal

Add an Ollama Cloud narrator profile for `gpt-oss:120b-cloud`, stored credentials, provider verification and dispatch while preserving existing OpenRouter behavior and paid-spend limits.

## Architecture

Reuse Playroom's credential store, immutable verified model profiles, generation cost policy, and provider result contract. Add a narrow Ollama verifier/adapter path with the fixed `https://ollama.com/v1` endpoint. The frontend exposes the provider and key field in existing settings. Live calls are excluded from automated verification.

## Tech Stack

Python backend, existing HTTP client and provider interfaces, React/TypeScript settings UI, pytest, Vitest, and existing project typecheck/build scripts.

## Spec

`docs/superpowers/specs/2026-10-13-ollama-cloud-provider-design.md`

## Global Constraints

- Preserve every pre-existing worktree change; do not reset or clean.
- Keep OpenRouter behavior and profiles compatible.
- Never expose credential values in logs, API responses, or tests.
- Fix Ollama's endpoint to `https://ollama.com/v1`; reject arbitrary endpoints.
- Do not dispatch a paid request unless the existing user-confirmed `capped_paid` cap permits it.
- No live Ollama call, frontend redesign, broad refactor, or deployment.
- Write regression tests first and observe RED before implementation.

## B1 — Verify and pin Ollama Cloud profile

### Files

- `backend/playroom/model_profiles.py`
- `backend/playroom/api/configuration.py`
- `backend/playroom/app.py`
- `backend/tests/test_model_profiles.py`
- `backend/tests/test_configuration.py`

### Steps

1. Add failing tests for fixed endpoint, bearer credential verification, exact model availability, safe errors, and versioned pricing/context metadata.
2. Implement an Ollama Cloud verifier that uses mocked `/v1/models` responses and rejects unsupported model IDs or endpoints.
3. Record the official pricing snapshot and conservative limits in the immutable verified profile while preserving OpenRouter verification.
4. Run the focused verifier/configuration tests.

## B2 — Dispatch narrator requests through Ollama

### Files

- `backend/playroom/provider.py`
- `backend/playroom/generation.py`
- `backend/playroom/wire_cost.py`
- `backend/tests/test_provider.py`
- `backend/tests/test_generation_durable.py`

### Steps

1. Add failing adapter tests for streaming text, terminal usage, malformed/error responses, fixed model, and absence of OpenRouter routing fields.
2. Add Ollama adapter/factory selection with bearer auth and the existing normalized provider result contract.
3. Test cost-cap rejection before network dispatch and ensure no automatic provider fallback.
4. Run provider and generation tests, including OpenRouter regression coverage.

## B3 — Add Ollama Cloud credentials to settings

### Files

- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- `frontend/src/components/SettingsPanel.tsx`
- `frontend/src/components/SettingsPanel.test.tsx`

### Steps

1. Add failing UI/API tests for Ollama Cloud key entry, secret storage, model selection, and verification feedback.
2. Implement the settings option using the existing secret-store API; never render the saved secret after creation.
3. Keep the user-confirmed spending cap visible and make profile readiness clear before generation.
4. Run focused frontend tests, full frontend suite, typecheck, and build.

## B4 — Independent review and verification

1. Review the complete diff against the spec and global constraints.
2. Run focused backend and frontend tests, then full backend tests, full frontend tests, typecheck, build, and `git diff --check`.
3. Inspect git status and confirm no pre-existing changes were dropped or accidentally staged.
4. Report exact settings steps and wait for the user's key to be saved before any real-model call.
