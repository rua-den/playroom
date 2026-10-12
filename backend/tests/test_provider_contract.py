from __future__ import annotations

import json
from decimal import Decimal

import httpx2 as httpx
import pytest

from playroom.credentials import CredentialStore
from playroom.model_profiles import validate_dispatch, OpenRouterVerifier
from playroom.provider import OpenRouterAdapter, ProviderFailure
from playroom.domain import ValidationError


def test_openrouter_stream_parses_comments_multiline_data_and_terminal_usage():
    body = b": keepalive\r\ndata: {\"choices\":[{\"delta\":{\"content\":\"Xin\"}}]}\n\ndata: {\"choices\":[{\"delta\":{\"content\":\" chao\"}}]}\ndata: {\"usage\":{\"prompt_tokens\":4,\"completion_tokens\":7,\"total_tokens\":11},\"choices\":[{\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", http_client=httpx.Client(transport=transport))
    events = list(adapter.generate_text({"model": "m", "messages": [], "profile": {"allow_fallbacks": False}}))
    assert "".join(event for event in events if isinstance(event, str)) == "Xin chao"
    assert events[-1].usage["total_tokens"] == 11


def test_openrouter_provider_error_and_missing_terminal_are_distinct():
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"message": "quota"}}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", http_client=httpx.Client(transport=transport))
    assert next(adapter.generate_text({"model": "m", "messages": []})).code == "QUOTA_EXHAUSTED"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', headers={"content-type": "text/event-stream"}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", http_client=httpx.Client(transport=transport))
    events = list(adapter.generate_text({"model": "m", "messages": []}))
    assert isinstance(events[-1], ProviderFailure) and events[-1].code == "OUTPUT_TRUNCATED"


def test_credential_store_masks_and_rotation_keeps_versions(tmp_path):
    store = CredentialStore(tmp_path / "secrets")
    first = store.put("owner-a", "sk-old")
    second = store.put("owner-a", "sk-new")
    assert first.version == 1 and second.version == 2
    assert store.masked("owner-a", first.id)["masked"] == "sk-***old"
    assert store.masked("owner-a", first.id)["secret"] is None
    assert store.get("owner-a", first.id) == "sk-old"
    store.revoke("owner-a", first.id)
    with pytest.raises(ValidationError, match="revoked"):
        store.get("owner-a", first.id)


def test_paid_cap_is_money_and_unknown_eligibility_fails_closed():
    with pytest.raises(ValidationError, match="billing"):
        validate_dispatch({"endpoint": "x", "model": "m", "secret_version": "s", "pricing_verified": False, "credential_tier": "unknown"}, "free_only", 1)
    with pytest.raises(ValidationError, match="cap"):
        validate_dispatch({"endpoint": "x", "model": "m", "secret_version": "s", "pricing_verified": True, "credential_tier": "paid", "estimated_cost_usd": "0.02"}, "capped_paid", 1, Decimal("0.01"))


def test_openrouter_metadata_verification_requires_exact_endpoint_and_records_tier():
    def route(request):
        if request.url.path.endswith("/models/m"):
            return httpx.Response(200, json={"data": {"pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format"]}})
        return httpx.Response(200, json={"data": {"is_free_tier": True, "limit": None}})
    verifier = OpenRouterVerifier(http_client=httpx.Client(transport=httpx.MockTransport(route)))
    result = verifier.verify("secret", "m", "https://openrouter.ai/api/v1/chat/completions")
    assert result["credential_tier"] == "free" and result["structured_output"] is True
