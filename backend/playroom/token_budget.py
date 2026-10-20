from __future__ import annotations

import json


def _estimate_tokens(text: str) -> int:
    # Conservative portable estimate used only when no compatible tokenizer is configured.
    return (len(text.encode("utf-8")) + 2) // 3


def evaluate_budget(blocks: list[dict], config: dict, *, counter=None, counter_id: str = "synthetic-test-counter") -> dict:
    required = ("context_window", "input_limit", "output_limit", "wrapper_buffer", "requested_output")
    if not isinstance(config, dict) or not (config.get("capabilities_verified") or config.get("is_test_profile") or config.get("limits_source") == "application_default") or not all(isinstance(config.get(key), int) and config[key] >= 0 for key in required):
        return {"fits": False, "counter_mode": "unavailable", "blocks": [], "failure": {"code": "UNSUPPORTED_MODEL_LIMITS", "message": "Verified model input/output limits are required before context can be evaluated."}}
    if config["input_limit"] < 1 or config["output_limit"] < 1 or config["requested_output"] > config["output_limit"]:
        return {"fits": False, "counter_mode": "unavailable", "blocks": [], "failure": {"code": "UNSUPPORTED_MODEL_LIMITS", "message": "Configured model limits cannot satisfy the requested output allowance."}}
    mode = "exact" if counter is not None else "estimated"
    costs = []
    for block in blocks:
        text = block.get("text", "")
        cost = max(1, int(counter(text))) if counter is not None else _estimate_tokens(text)
        costs.append({"id": block["id"], "token_cost": cost, "mandatory": bool(block.get("mandatory"))})
    input_tokens = sum(item["token_cost"] for item in costs)
    effective_input_cap = min(config["input_limit"], config["context_window"] - config["requested_output"] - config["wrapper_buffer"])
    fits = effective_input_cap >= 0 and input_tokens <= effective_input_cap
    failure = None if fits else {"code": "REQUIRED_CONTEXT_OVERFLOW", "message": "Required context, wrapper, and output reserve exceed verified model limits; review memory before sending."}
    return {"fits": fits, "counter_mode": mode, "counter_id": counter_id if counter is not None else "utf8-bytes-div-3", "blocks": costs, "input_tokens": input_tokens, "input_limit": config["input_limit"], "input_cap": effective_input_cap, "context_window": config["context_window"], "output_reserve": config["requested_output"], "output_limit": config["output_limit"], "wrapper_buffer": config["wrapper_buffer"], "failure": failure, "serialized_blocks_hash_input": json.dumps(costs, sort_keys=True)}
