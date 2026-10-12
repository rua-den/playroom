from __future__ import annotations

from playroom.token_budget import evaluate_budget


def test_exact_and_estimated_counters_are_labeled_and_required_overflow_blocks():
    exact = evaluate_budget([{"id": "canon", "text": "abcd", "mandatory": True}], {"input_limit": 20, "output_limit": 8, "wrapper_buffer": 4, "requested_output": 8}, counter=lambda text: len(text))
    assert exact["counter_mode"] == "exact"
    assert exact["blocks"][0]["token_cost"] == 4
    assert exact["fits"] is True

    estimated = evaluate_budget([{"id": "canon", "text": "abcdefgh", "mandatory": True}], {"input_limit": 5, "output_limit": 8, "wrapper_buffer": 4, "requested_output": 8})
    assert estimated["counter_mode"] == "estimated"
    assert estimated["fits"] is False
    assert estimated["failure"]["code"] == "REQUIRED_CONTEXT_OVERFLOW"


def test_missing_verified_capabilities_blocks_instead_of_guessing():
    result = evaluate_budget([], {"model_id": "model-with-unknown-limits"})
    assert result["fits"] is False
    assert result["failure"]["code"] == "UNSUPPORTED_MODEL_LIMITS"
