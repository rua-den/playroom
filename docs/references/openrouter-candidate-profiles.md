# OpenRouter candidate profiles

Checked 2026-10-12 against the public model and endpoint APIs. These are candidates to configure and compare, not selected defaults or evidence of roleplay quality. No credential was read and no inference request was made.

| Candidate | Model ID | Endpoint context / max total completion | Listed input / output per 1M tokens | Role fit before user trial |
|---|---|---|---|---|
| Free | nvidia/nemotron-3-super-120b-a12b:free | 262,144 / 235,929 | $0 / $0 | Catalog and nvidia endpoint list structured_outputs + response_format; eligible for evaluation of all three roles only after credential and endpoint checks |
| Paid | anthropic/claude-sonnet-4.6 | 1,000,000 / 128,000 | Anthropic endpoint: $3 / $15 | Structured output listed; candidate narrator/director/consolidator when the owner explicitly enables capped_paid |

Sources: [Nemotron model page](https://openrouter.ai/nvidia/nemotron-3-super-120b-a12b:free), [Sonnet pricing](https://openrouter.ai/anthropic/claude-sonnet-4.6/pricing), [model catalog](https://openrouter.ai/api/v1/models), [Nemotron endpoints](https://openrouter.ai/api/v1/models/nvidia/nemotron-3-super-120b-a12b:free/endpoints), [Sonnet endpoints](https://openrouter.ai/api/v1/models/anthropic/claude-sonnet-4.6/endpoints).

The Nemotron marketing description mentions its underlying model's 1M window; the actual free endpoint lists 262,144. Its page FAQ also quotes a different completion maximum from the endpoint API. Use the chosen endpoint's checked limits, not the marketing values. Some regional Sonnet providers quote $3.30 / $16.50; do not use the $3 / $15 estimate for those endpoints.

A public page for qwen/qwen3-next-80b-a3b-instruct:free still exists but that exact ID was absent from the current public catalog. Do not configure it from the page alone.

Free endpoints can be rate limited or removed. The Nemotron page discloses logging/use of trial input for NVIDIA improvement; let the owner inspect the endpoint's data policy before choosing it for private story text. No transcript has been sent. Output reserve includes reasoning, so the maxima above are not promises of visible narration length.

Refresh capability and pricing metadata when configuring a real profile. Bind its endpoint, supported parameters, verified prices and credential version to jobs. Keep provider fallbacks disabled, require parameter support, and prohibit plugins/tools in free_only. Owner settings select IDs; API clients cannot assert their own capability/pricing verification. Unknown credential billing eligibility blocks dispatch. See [routing](https://openrouter.ai/docs/guides/routing/provider-selection), [endpoint metadata](https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints), and [current-key metadata](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key).
