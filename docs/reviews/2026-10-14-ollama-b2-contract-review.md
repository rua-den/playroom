# Playroom B2 — Ollama Cloud narrator contract review

Date: 2026-10-14  
Baseline: GitHub `main` `be38b811fbdd684a682d1de9a0f70a529ad7799f` (no later main change observed before this document)  
Next implementation item: [Issue #4](https://github.com/rua-den/playroom/issues/4)

## What was independently checked

1. [B1 merge](https://github.com/rua-den/playroom/pull/3) is finished; [merge-head Actions](https://github.com/rua-den/playroom/actions/runs/38503392817) succeeded before the subsequent docs commit. At this review baseline, there was **no** B2 code PR.
2. `backend/playroom/model_profiles.py::OllamaCloudVerifier` pins `https://ollama.com/v1`, API model `gpt-oss:120b`, `structured_output=False`, `native_structured_output=False`, `supported_parameters=["max_tokens"]`, and uncached token rates of USD 0.15 / 1M input and USD 0.60 / 1M output. Verification requests `GET /v1/models`, not provider pricing. Therefore `pricing_verified=True` is an application assertion based on static pricing metadata, **not** a price lookup performed during verification.
3. `backend/playroom/generation.py::_narrator_request` correctly omits native JSON schema for Ollama; `_narrate` still requires `parse_narrator_payload()` to return attributed segments for every non-test narrator before it can produce a candidate. In the system prompt, *"Return exactly one JSON object ... when structured roleplay output is enabled"* is ambiguous for Ollama, since its advertised native structured-output flag is false. This is a concrete prompt/validation contract mismatch.
4. `backend/playroom/provider.py::OllamaCloudAdapter` inherits the OpenAI-compatible SSE reader; `backend/playroom/wire_cost.py::provider_wire` emits streaming, include_usage and output token allowance but no `response_format` unless a native schema is supplied. `backend/tests/test_ollama_cloud.py` covers mocked /models, adapter transport and routing, **not a successful end-to-end Ollama narrator candidate/commit**.
5. `backend/playroom/roleplay_segments.py::parse_narrator_payload` accepts JSON object `{"segments":[...]}` or array; validates selected character IDs/profile versions, preserves narration, rejects malformed segments. Pure prose / Markdown JSON fences cannot produce the structured segments the production narrator requires. Structural validation cannot prove semantic player-agency preservation in prose.

## Provider capability decision (based on official documentation)

- Ollama's [structured-output guide](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx) explicitly says cloud currently **does not support structured outputs**. Do **not** advertise strict native-schema support or route Ollama to context/consolidation director roles.
- Ollama's [OpenAI-compatibility guide](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx) lists streaming, include_usage, JSON mode and `response_format` in chat completions. A documented `json_object` output mode may be a viable **non-strict** format hint; it must be separately tested against the pinned `https://ollama.com/v1` endpoint. Do not mistake JSON mode for schema-constrained decoding.
- Ollama's current [model page](https://ollama.com/library/gpt-oss%3A120b-cloud) and [pricing page](https://ollama.com/pricing) list gpt-oss:120b at **USD 0.15 input / 0.60 output per million tokens**; cached input USD 0.014/M is also published. Static Playroom rates match uncached input/output *at review time*, but they must be rechecked before each new paid-trial authorization. No live call or account-balance check was made.

## Acceptance matrix for coding agent

| Case | Expected invariant |
| --- | --- |
| Ollama narrator non-native request | Prompt explicitly demands one JSON `segments` object regardless of native schema flag; no native strict-schema request sent |
| SSE chunks + terminal stop + valid JSON with selected NPC and pinned version | Exactly one candidate, one commit, attribution preserved, one provider attempt |
| Valid JSON with unselected NPC or mismatched pinned version | `SCHEMA_INVALID`; no committed turn |
| Prose, fenced JSON, malformed JSON, empty segments, conflicting `type`/`kind` | Fail closed; no committed turn |
| Truncated/max-tokens, refusal, missing [DONE], missing terminal usage | Preserve correct normalized failures/unknown cost, no auto-commit; verify parser state |
| Reconnect/refresh/recovered candidate | No duplicate upstream call or duplicated revision; existing request ID survives ambiguity |
| `free_only` with paid Ollama profile | Block pre-dispatch; never silently use paid model |
| `quality` director assigned Ollama | Reject unsupported native strict capability; no dispatch |
| Model output narrating unrequested Henn actions | **Semantic model-trial failure** (not reliably caught by JSON schema alone) |
| Absent but mentioned NPC dialogue/teleport | Semantic scene/knowledge evaluation, not mere ID-allowlist verification |

## Narrow coding order

1. RED: add a unit regression asserting that Ollama's system narrator prompt unconditionally requires JSON despite native schema flag=false.
2. Fix prompt contract; add explicit `kind: narration|dialogue`, required speaker ID/version description and no-player-agency instructions. Preserve existing OpenRouter prompts and typed segment validation.
3. RED/GREEN: adapter-level mocked SSE tests (completion and failure classes), then generation-service integration tests using a production-shaped Ollama profile, mocked adapter factory, and deterministic response. Confirm exactly-one commit, attribution, stable checkpoint and no chargeable replay.
4. Evaluate opt-in JSON mode via a discrete adapter test; never turn on `native_structured_output` solely because `response_format: json_object` works. Do not enable a provider option without a test proving wire compatibility; if unverified, stay with explicit prompt and strict post-validation.
5. Full `uv run --locked --extra test pytest backend/tests -q`, `compileall`, frontend test/typecheck/build, GitHub CI at exact PR SHA, independent diff review, merge only after PASS.

## Gates and status

- **Completed:** independent source + official doc research; this review; Issue #4 refined.
- **Not performed:** implementation, new regression execution, live model request, pricing/account verification, phone trial, or VPS changes.
- **Agent routing:** per `AGENTS.md`, direct ChatGPT fallback was authorized for **Issue #2 only**. For B2, `gpt-5.6-luna` is required to write code unless the owner explicitly expands the exception. The current ChatGPT session cannot dispatch Luna.
- **Decision:** keep B2 **OPEN / NOT PASS** and avoid publishing an untested production change.
