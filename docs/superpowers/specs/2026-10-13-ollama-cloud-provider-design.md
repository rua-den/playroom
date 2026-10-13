# Ollama Cloud Provider Design

## Goal

Allow Playroom to use Ollama Cloud's `gpt-oss:120b-cloud` as a narrator, with its API key stored using the existing credential vault and with cost limits enforced before dispatch.

## User experience

In provider settings, the user can add an Ollama Cloud credential and choose the supported model. The endpoint is fixed to `https://ollama.com/v1`; the user does not need to copy or configure an endpoint. The key is entered only in the local settings UI and is never requested in chat. Existing OpenRouter settings and profiles continue to work.

## Runtime behavior

- Verify the bearer credential against Ollama Cloud and confirm that the exact model is available.
- Create a versioned, immutable verified profile for that model, including a timestamped pricing snapshot and conservative context/output limits.
- Dispatch only narrator generation through Ollama's OpenAI-compatible `/chat/completions` API.
- Keep the OpenRouter adapter and request format unchanged. Ollama requests must not include OpenRouter-specific provider-routing fields.
- Normalize streaming text and usage into Playroom's existing provider result format.
- Enforce the existing `capped_paid` policy and its user-confirmed USD cap before any paid request. Never silently fall back to another provider.
- Automated tests use mocked HTTP responses. A live request is made only after the user saves their key in the app and explicitly asks to test it.

## Model metadata

Use the official Ollama model page as the source for the initial pinned snapshot: 128K context, input USD 0.15 per million tokens and output USD 0.60 per million tokens. Record the source and retrieval date in profile metadata. Re-verification refreshes the snapshot; historical generation records keep their original profile and cost policy.

## Validation

Cover credential verification, unavailable model rejection, fixed endpoint enforcement, request shaping, streamed result/usage normalization, cost-cap rejection, and OpenRouter regression behavior. Run focused backend tests, the full backend suite, frontend tests, typecheck, build, and `git diff --check` before completion.

## Sources

- https://docs.ollama.com/api/openai-compatibility
- https://docs.ollama.com/api/authentication
- https://ollama.com/library/gpt-oss:120b-cloud
