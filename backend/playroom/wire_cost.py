from __future__ import annotations

"""Shared provider-wire packing, counting and cost helpers.

The generation worker builds one prepared request per stage.  The same
prepared request is persisted, budgeted and handed to an adapter.  Runtime
handles (events, locks and provider instances) never enter the wire hash.
"""

import hashlib
import json
from decimal import Decimal
from typing import Callable

from .domain import ValidationError
from .model_profiles import estimate_cost_usd

DEFAULT_INPUT_LIMIT = 12_000
DEFAULT_OUTPUT_LIMIT = 4_000
DEFAULT_WRAPPER_BUFFER = 512
DEFAULT_CONTEXT_WINDOW = 16_512
DEFAULT_COUNTER_ID = "utf8-bytes-div-3"


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def wire_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def declared_count(value, *, counter: Callable[[str], int] | None = None) -> int:
    """Count a serialized value with the server-owned declared counter."""
    text = value if isinstance(value, str) else canonical_json(value)
    if counter is not None:
        return max(1, int(counter(text)))
    # The portable estimate is deliberately conservative and counts UTF-8
    # bytes, so Vietnamese combining marks and astral characters are included.
    return max(1, (len(text.encode("utf-8")) + 2) // 3)


def effective_input_cap(profile: dict, budget: dict | None = None) -> int:
    budget = budget or {}
    context_window = int(profile.get("context_limit", profile.get("context_window", DEFAULT_CONTEXT_WINDOW)))
    verified_input = int(profile.get("input_limit", profile.get("context_limit", DEFAULT_INPUT_LIMIT)))
    configured_input = int(budget.get("input_limit", DEFAULT_INPUT_LIMIT))
    output = int(budget.get("requested_output", budget.get("total_output", DEFAULT_OUTPUT_LIMIT)))
    wrapper = int(budget.get("wrapper_buffer", DEFAULT_WRAPPER_BUFFER))
    return min(configured_input, verified_input, context_window - output - wrapper)


def normalized_budget(profile: dict, configured: dict | None = None) -> dict:
    """Return a role budget bounded by immutable verified profile limits."""
    configured = configured or {}
    context_window = int(profile.get("context_limit", profile.get("context_window", DEFAULT_CONTEXT_WINDOW)))
    verified_input = int(profile.get("input_limit", profile.get("context_limit", DEFAULT_INPUT_LIMIT)))
    verified_output = int(profile.get("output_limit", DEFAULT_OUTPUT_LIMIT))
    requested = configured.get("requested_output", configured.get("total_output", DEFAULT_OUTPUT_LIMIT))
    values = {
        "input_limit": min(int(configured.get("input_limit", DEFAULT_INPUT_LIMIT)), verified_input),
        "requested_output": min(int(requested), verified_output, DEFAULT_OUTPUT_LIMIT),
        "wrapper_buffer": int(configured.get("wrapper_buffer", DEFAULT_WRAPPER_BUFFER)),
        "context_window": context_window,
        "output_limit": verified_output,
    }
    if values["input_limit"] < 1 or values["requested_output"] < 1 or values["wrapper_buffer"] < 0:
        raise ValidationError("Role budget values must be positive and within verified limits")
    values["input_cap"] = effective_input_cap(profile, values)
    if values["input_cap"] < 0:
        raise ValidationError("Role budget leaves no room for input after output and wrapper reserve")
    return values


def provider_wire(request: dict, profile: dict, *, schema: dict | None = None) -> dict:
    """Build the exact provider payload shape used by the OpenRouter adapter."""
    output_parameter = profile.get("output_parameter") or (
        "max_completion_tokens" if "max_completion_tokens" in set(profile.get("supported_parameters", ())) else "max_tokens"
    )
    requested_output = int(request.get("reserved_completion_tokens", request.get("reserved_output_tokens", 0)))
    provider = {"allow_fallbacks": False, "require_parameters": True}
    if profile.get("provider_tag"):
        provider["only"] = [profile["provider_tag"]]
    result = {
        "model": profile.get("model") or request.get("model"),
        "messages": request.get("messages", []),
        "stream": True,
        "stream_options": {"include_usage": True},
        output_parameter: requested_output,
        "provider": provider,
    }
    if schema is not None:
        result["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.get("schema_name", "selection_plan"),
                "strict": True,
                "schema": schema,
            },
        }
    return result


def count_provider_wire(request: dict, profile: dict, *, schema: dict | None = None, counter=None) -> dict:
    payload = provider_wire(request, profile, schema=schema)
    serialized = canonical_json(payload)
    return {
        "wire": payload,
        "serialized": serialized,
        "payload_hash": wire_hash(payload),
        "input_tokens": declared_count(serialized, counter=counter),
        "counter_mode": "exact" if counter is not None else "estimated",
        "counter_id": getattr(counter, "counter_id", None) or ("server-exact" if counter is not None else DEFAULT_COUNTER_ID),
    }


def stage_cost(profile: dict, input_tokens: int, output_tokens: int) -> Decimal:
    return estimate_cost_usd(profile, input_tokens, output_tokens)

