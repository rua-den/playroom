from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from playroom.domain import ValidationError
from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT, OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_API_MODEL, OLLAMA_FREE_CLOUD_MODEL, OLLAMA_FREE_CLOUD_API_MODEL, OllamaCloudVerifier, validate_dispatch
from playroom.provider import OllamaCloudAdapter, ProviderResult, default_provider_factory
from playroom.wire_cost import provider_wire


def _profile(**overrides):
    profile = {
        "id": "ollama-profile", "version": 1, "profile_hash": "hash",
        "provider": "ollama", "endpoint": OLLAMA_CLOUD_ENDPOINT,
        "model": OLLAMA_CLOUD_API_MODEL, "model_label": OLLAMA_CLOUD_MODEL, "provider_tag": None,
        "context_limit": 131072, "output_limit": 4096,
        "supported_parameters": ["max_tokens"], "output_parameter": "max_tokens",
        "structured_output": False, "pricing_verified": True,
        "credential_tier": "paid", "secret_version": "cred-1",
        "pricing": {"prompt": "0.00000015", "completion": "0.00000060"},
    }
    profile.update(overrides)
    return profile


def test_ollama_verifier_pins_endpoint_model_and_pricing_snapshot():
    requests = []
    def route(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": OLLAMA_CLOUD_API_MODEL}, {"id": "other"}]})

    verifier = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(route)))
    result = verifier.verify("ollama-secret", OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)

    assert result["provider"] == "ollama"
    assert result["endpoint"] == OLLAMA_CLOUD_ENDPOINT
    assert result["model"] == OLLAMA_CLOUD_API_MODEL
    assert result["model_label"] == OLLAMA_CLOUD_MODEL
    assert result["context_limit"] == 131072
    assert result["pricing"] == {"prompt": "0.00000015", "completion": "0.00000060", "currency": "USD", "unit": "USD/token"}
    assert result["metadata_source"].startswith(OLLAMA_CLOUD_ENDPOINT)
    assert requests[0].url == f"{OLLAMA_CLOUD_ENDPOINT}/models"
    assert requests[0].headers["authorization"] == "Bearer ollama-secret"


def test_ollama_verifier_rejects_custom_endpoint_and_missing_exact_model():
    verifier = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "other"}]}))))
    with pytest.raises(ValidationError, match="pinned Ollama"):
        verifier.verify("secret", OLLAMA_CLOUD_MODEL, "https://evil.example/v1")
    with pytest.raises(ValidationError, match="unavailable"):
        verifier.verify("secret", OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)

    wrong_label = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": OLLAMA_CLOUD_MODEL}]}))))
    with pytest.raises(ValidationError, match="unavailable"):
        wrong_label.verify("secret", OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)


def test_ollama_adapter_uses_fixed_openai_wire_without_openrouter_routing():
    captured = {}
    body = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: {"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5},"choices":[{"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    def route(request):
        captured.update(json.loads(request.content))
        assert str(request.url) == f"{OLLAMA_CLOUD_ENDPOINT}/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    profile = _profile()
    adapter = OllamaCloudAdapter("secret", OLLAMA_CLOUD_ENDPOINT, profile=profile, http_client=httpx.Client(transport=httpx.MockTransport(route)))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert "provider" not in captured
    assert captured["model"] == OLLAMA_CLOUD_API_MODEL
    assert "".join(item for item in events if isinstance(item, str)) == "Hello"
    assert isinstance(events[-1], ProviderResult)
    assert events[-1].usage["total_tokens"] == 5
    assert isinstance(default_provider_factory(owner_id="o", stage="narration", profile=profile, credential="secret", http_client=adapter.client), OllamaCloudAdapter)


def test_ollama_wire_omits_openrouter_fields():
    wire = provider_wire({"messages": [], "reserved_completion_tokens": 5}, _profile())
    assert "provider" not in wire
    assert wire["model"] == OLLAMA_CLOUD_API_MODEL


def test_ollama_factory_is_narrator_only():
    with pytest.raises(ValueError, match="narrator"):
        default_provider_factory(owner_id="o", stage="context", profile=_profile(), credential="secret")


def test_gemma4_free_starter_verifier_uses_real_api_model_id_and_separate_evidence():
    calls = []
    def route(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"id": "gemma4:31b"}, {"id": "gpt-oss:120b"}]})
    verifier = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(route)))
    free = verifier.verify("secret-fixture", OLLAMA_FREE_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)
    assert free["provider"] == "ollama"
    assert free["model_label"] == "gemma4:31b-cloud"
    assert free["model"] == "gemma4:31b"
    assert free["credential_tier"] == "free"
    assert free["free_starter_eligible"] is True
    assert free["starter_eligibility_source"].startswith("https://ollama.com/")
    assert free["starter_eligibility_checked_at"]
    assert free["account_free_credits_remaining"] is None
    assert free["purchased_credit_exposure_unknown"] is True
    assert free["context_limit"] == 262144
    assert free["native_structured_output"] is False
    assert free["pricing"] == {
        "prompt": "0.00000014", "completion": "0.00000040",
        "currency": "USD", "unit": "USD/token",
    }
    assert len(calls) == 1 and str(calls[0].url) == "https://ollama.com/v1/models"
    validate_dispatch({**free, "secret_version": "credential-fixture"}, "free_only", None)
    paid = verifier.verify("secret-fixture", OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)
    assert paid["model"] == "gpt-oss:120b" and paid["credential_tier"] == "paid"
    with pytest.raises(ValidationError, match="free_only"):
        validate_dispatch({**paid, "secret_version": "credential-fixture"}, "free_only", None)


def test_free_model_must_be_exact_catalog_id_not_display_alias():
    verifier = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": [{"id": "gemma4:cloud"}, {"id": "gemma4"}]})
    )))
    with pytest.raises(ValidationError, match="unavailable"):
        verifier.verify("secret", OLLAMA_FREE_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)


@pytest.mark.parametrize("label", ["gemma4", "gemma4:cloud", "gemma4:31b", "unknown:cloud", "gpt-oss:120b"])
def test_reject_unverified_model_labels(label):
    verifier = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": [{"id": label}, {"id": OLLAMA_FREE_CLOUD_API_MODEL}]})
    )))
    with pytest.raises(ValidationError, match="unavailable"):
        verifier.verify("secret", label, OLLAMA_CLOUD_ENDPOINT)


def test_free_starter_pinned_endpoint_and_credentials_are_mandatory():
    verifier = OllamaCloudVerifier(http_client=httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": [{"id": OLLAMA_FREE_CLOUD_API_MODEL}]})
    )))
    with pytest.raises(ValidationError, match="pinned"):
        verifier.verify("secret", OLLAMA_FREE_CLOUD_MODEL, "https://example.invalid/v1")
    with pytest.raises(ValidationError, match="credential"):
        verifier.verify("", OLLAMA_FREE_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)
