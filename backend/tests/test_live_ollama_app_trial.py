from __future__ import annotations

import pytest

from live_ollama_app_trial import (
    MAX_OUTPUT_TOKENS,
    MAX_TRIAL_USD,
    CountingHttpClient,
    trial_contract,
)


def test_offline_contract_has_one_dispatch_and_small_bounds():
    contract = trial_contract()
    assert contract["max_provider_posts"] == 1
    assert contract["max_output_tokens"] == MAX_OUTPUT_TOKENS
    assert contract["max_usd"] == MAX_TRIAL_USD
    assert contract["private_fixture"] is True


def test_counting_client_rejects_second_provider_post():
    client = CountingHttpClient(object())
    client.record_post("https://ollama.com/v1/chat/completions")
    with pytest.raises(RuntimeError, match="at most one"):
        client.record_post("https://ollama.com/v1/chat/completions")


def test_live_gate_denies_missing_approval_and_reruns_before_dispatch(monkeypatch):
    from live_ollama_app_trial import ensure_live_gate

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("B4_LOCAL_APP_APPROVAL", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    assert ensure_live_gate() is False

    monkeypatch.setenv("B4_LOCAL_APP_APPROVAL", "B4_LOCAL_APP_TRIAL_2026_10_18")
    monkeypatch.setenv("OLLAMA_API_KEY", "redacted-test-key")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert ensure_live_gate() is False


def test_offline_main_does_not_read_key_or_make_network(monkeypatch, capsys):
    from live_ollama_app_trial import main

    monkeypatch.setenv("B4_DRY_RUN", "1")
    monkeypatch.setenv("OLLAMA_API_KEY", "must-not-be-used")
    assert main() == 0
    assert "OFFLINE CONTRACT: PASS" in capsys.readouterr().out
