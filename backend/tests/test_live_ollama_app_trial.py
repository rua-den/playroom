from __future__ import annotations

import json
import pytest

from live_ollama_app_trial import (
    MAX_OUTPUT_TOKENS,
    MAX_TRIAL_USD,
    CountingHttpClient,
    _balance_preflight,
    _run_app_flow,
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


def test_counting_client_rejects_unpinned_provider_post():
    client = CountingHttpClient(object())
    with pytest.raises(RuntimeError, match="pinned"):
        client.record_post("https://example.test/chat/completions")


def test_offline_app_flow_exercises_real_verifier_adapter_and_persistence():
    posts, verifier_gets = _run_app_flow(offline=True)
    assert (posts, verifier_gets) == (1, 1)


@pytest.mark.parametrize(
    "payload",
    [
        {"included": {"balance_usd": "0.009"}, "purchased": {"balance_usd": "0"}},
        {"included": {"balance_usd": "0.01"}, "purchased": {"balance_usd": "0.001"}},
        {"included": {"balance_usd": "NaN"}, "purchased": {"balance_usd": "0"}},
    ],
)
def test_balance_preflight_denies_insufficient_purchased_or_unknown(monkeypatch, payload):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def read(self):
            return json.dumps(payload).encode()
        def __iter__(self):
            return iter(())
        def json(self):
            return payload

    class Opener:
        def open(self, *args, **kwargs):
            return Response()
    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: Opener())
    with pytest.raises(RuntimeError, match="balance preflight"):
        _balance_preflight("fixture-key")


def test_balance_preflight_does_not_follow_redirect(monkeypatch):
    class RedirectingOpener:
        def open(self, request, **kwargs):
            raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
                request.full_url, 302, "redirect", {"Location": "https://evil.example/balance"}, None
            )
    monkeypatch.setattr("urllib.request.build_opener", lambda *args, **kwargs: RedirectingOpener())
    with pytest.raises(RuntimeError, match="balance preflight"):
        _balance_preflight("fixture-key")


def test_offline_verifier_patch_is_restored():
    import playroom.api.configuration as configuration_api
    original = configuration_api.OllamaCloudVerifier
    _run_app_flow(offline=True)
    assert configuration_api.OllamaCloudVerifier is original


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
