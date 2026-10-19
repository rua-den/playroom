from __future__ import annotations

import json
import pytest
import httpx2 as httpx

from live_ollama_app_trial import (
    MAX_OUTPUT_TOKENS,
    MAX_TRIAL_USD,
    CountingHttpClient,
    FIXTURE_KEY,
    OLLAMA_CLOUD_ENDPOINT,
    OfflineProviderTransport,
    NPC_VERSION,
    NPC_ID,
    _response_shape_summary,
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


def test_counting_client_rejects_non_post_before_transport():
    client = CountingHttpClient(object())
    with pytest.raises(RuntimeError, match="method"):
        client.guard.check("GET", "https://ollama.com/v1/chat/completions", {"model": "gemma4:31b", "max_tokens": 1})


def test_offline_fixture_rejects_wrong_persisted_credential():
    fixture = OfflineProviderTransport()
    client = httpx.Client(transport=httpx.MockTransport(fixture))
    with pytest.raises(RuntimeError, match="credential"):
        client.get(f"{OLLAMA_CLOUD_ENDPOINT}/models", headers={"Authorization": "Bearer wrong-key"})
    client.close()


def test_old_invented_npc_version_fixture_is_red():
    fixture = OfflineProviderTransport()
    fixture.npc_profile_version = "persisted-version"
    request = httpx.Request(
        "POST", f"{OLLAMA_CLOUD_ENDPOINT}/chat/completions",
        headers={"Authorization": f"Bearer {FIXTURE_KEY}"},
        json={"model": "gemma4:31b", "max_tokens": 640, "messages": [{"content": NPC_VERSION}]},
    )
    with pytest.raises(RuntimeError, match="invented"):
        fixture(request)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("null", {"json_valid": True, "segment_kind_valid": False, "selected_attribution_match": False}),
        ('{"segments": [{"kind": "narration"}, null]}', {"json_valid": True, "segment_kind_valid": False, "selected_attribution_match": False}),
        ('{"segments": [{"kind": "dialogue", "character_id": "x", "profile_version_id": "wrong"}]}', {"json_valid": True, "segment_kind_valid": True, "selected_attribution_match": False}),
        (json.dumps({"segments": [{"kind": "dialogue", "character_id": NPC_ID, "profile_version_id": "persisted"}]}), {"json_valid": True, "segment_kind_valid": True, "selected_attribution_match": True}),
        ('```json\n{"segments": []}\n```', {"json_valid": False, "fenced": True, "segment_kind_valid": False, "selected_attribution_match": False}),
    ],
)
def test_response_shape_summary_is_strict_and_redacts_content(text, expected):
    summary = _response_shape_summary(text, "persisted")
    assert {key: summary[key] for key in expected} == expected
    rendered = json.dumps(summary)
    assert "persisted" not in rendered
    assert NPC_ID not in rendered
    assert "wrong" not in rendered


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

    monkeypatch.setenv("B4_LOCAL_APP_APPROVAL", "B4_LOCAL_APP_TRIAL_2026_10_19")
    monkeypatch.setenv("OLLAMA_API_KEY", "redacted-test-key")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert ensure_live_gate() is False


def test_offline_main_does_not_read_key_or_make_network(monkeypatch, capsys):
    from live_ollama_app_trial import main

    monkeypatch.setenv("B4_DRY_RUN", "1")
    monkeypatch.setenv("OLLAMA_API_KEY", "must-not-be-used")
    assert main() == 0
    assert "OFFLINE CONTRACT: PASS" in capsys.readouterr().out
