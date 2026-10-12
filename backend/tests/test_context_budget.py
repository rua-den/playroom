from __future__ import annotations

from playroom.token_budget import evaluate_budget


def test_exact_and_estimated_counters_are_labeled_and_required_overflow_blocks():
    exact = evaluate_budget([{"id": "canon", "text": "abcd", "mandatory": True}], {"is_test_profile": True, "context_window": 40, "input_limit": 20, "output_limit": 8, "wrapper_buffer": 4, "requested_output": 8}, counter=lambda text: len(text))
    assert exact["counter_mode"] == "exact"
    assert exact["blocks"][0]["token_cost"] == 4
    assert exact["fits"] is True

    estimated = evaluate_budget([{"id": "canon", "text": "abcdefghijklmnopqrst", "mandatory": True}], {"is_test_profile": True, "context_window": 20, "input_limit": 5, "output_limit": 8, "wrapper_buffer": 4, "requested_output": 8})
    assert estimated["counter_mode"] == "estimated"
    assert estimated["fits"] is False
    assert estimated["failure"]["code"] == "REQUIRED_CONTEXT_OVERFLOW"


def test_missing_verified_capabilities_blocks_instead_of_guessing():
    result = evaluate_budget([], {"model_id": "model-with-unknown-limits"})
    assert result["fits"] is False
    assert result["failure"]["code"] == "UNSUPPORTED_MODEL_LIMITS"


def test_context_window_formula_reserves_output_and_wrapper_once():
    result = evaluate_budget([{'id': 'payload', 'text': 'abcd', 'mandatory': True}], {'context_window': 14, 'input_limit': 12, 'output_limit': 8, 'wrapper_buffer': 3, 'requested_output': 8, 'capabilities_verified': True}, counter=lambda text: len(text))
    assert result['fits'] is False
    assert result['context_window'] == 14
    assert result['input_cap'] == 3
    assert result['input_tokens'] == 4
    assert result['counter_id'] == 'synthetic-test-counter'
