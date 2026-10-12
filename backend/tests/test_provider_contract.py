from __future__ import annotations

import json
from decimal import Decimal

import httpx2 as httpx
import pytest

from playroom.credentials import CredentialStore
from playroom.model_profiles import validate_dispatch, OpenRouterVerifier, estimate_cost_usd
from playroom.provider import OpenRouterAdapter, ProviderFailure, ProviderResult, FakeProvider
from playroom.domain import ValidationError


def _profile(**overrides):
    profile = {"id": "profile-1", "version": 1, "profile_hash": "hash-1", "provider_tag": "exact", "model": "m", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "context_limit": 100, "output_limit": 10, "supported_parameters": ["max_tokens", "response_format"], "native_structured_output": True, "structured_schema_parameter": "response_format", "structured_output": True}
    profile.update(overrides)
    return profile


class _SplitStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks


def test_openrouter_stream_parses_comments_multiline_data_and_terminal_usage():
    body = b": keepalive\r\ndata: {\"choices\":[{\"delta\":{\"content\":\"Xin\"}}]}\n\ndata: {\"choices\":[{\"delta\":{\"content\":\" chao\"}}]}\n\ndata: {\"usage\":{\"prompt_tokens\":4,\"completion_tokens\":7,\"total_tokens\":11},\"choices\":[{\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=transport))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert "".join(event for event in events if isinstance(event, str)) == "Xin chao"
    assert events[-1].usage["total_tokens"] == 11


def test_openrouter_provider_error_and_missing_terminal_are_distinct():
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"message": "quota"}}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=transport))
    assert next(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10})).code == "QUOTA_EXHAUSTED"

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', headers={"content-type": "text/event-stream"}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=transport))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert isinstance(events[-1], ProviderFailure) and events[-1].code == "MISSING_TERMINAL"


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
        validate_dispatch({"endpoint": "x", "model": "m", "secret_version": "s", "pricing_verified": True, "credential_tier": "paid", "pricing": {"prompt": "0.02", "completion": "0.01"}}, "capped_paid", {"input_tokens": 1, "completion_tokens": 1}, Decimal("0.01"))
    with pytest.raises(ValidationError, match="allowance"):
        validate_dispatch({"endpoint": "x", "model": "m", "secret_version": "s", "pricing_verified": True, "credential_tier": "paid", "pricing": {"prompt": "0.02", "completion": "0.01"}}, "capped_paid", 1, Decimal("0.01"))


def test_openrouter_metadata_verification_requires_exact_endpoint_and_records_tier():
    def route(request):
        if request.url.path.endswith("/models/author/model:free/endpoints"):
            return httpx.Response(200, json={"data": [{"id": "other", "provider_id": "other", "model_name": "author/model:free", "context_length": 8192, "max_completion_tokens": 1024, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format"], "structured_outputs": True}, {"id": "exact", "provider_name": "Exact", "provider_id": "exact", "model_name": "author/model:free", "context_length": 8192, "max_completion_tokens": 1024, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format"], "structured_outputs": True, "data_policy": {"allow_training": False}}]})
        return httpx.Response(200, json={"data": {"is_free_tier": False, "limit": None}})
    verifier = OpenRouterVerifier(http_client=httpx.Client(transport=httpx.MockTransport(route)))
    result = verifier.verify("secret", "author/model:free", "https://openrouter.ai/api/v1/chat/completions", provider_tag="exact")
    assert result["credential_tier"] == "free" and result["structured_output"] is True
    assert result["provider_tag"] == "exact"
    assert result["metadata_source"].endswith("/models/author/model:free/endpoints")


def test_metadata_response_format_alone_does_not_prove_native_schema_support():
    def route(request):
        if request.url.path.endswith("/endpoints"):
            return httpx.Response(200, json={"data": [{"id": "exact", "provider_id": "exact", "model_name": "author/model", "context_length": 8192, "max_completion_tokens": 1024, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format"]}]})
        return httpx.Response(200, json={"data": {"is_free_tier": False}})

    verifier = OpenRouterVerifier(http_client=httpx.Client(transport=httpx.MockTransport(route)))
    result = verifier.verify("secret", "author/model", "https://openrouter.ai/api/v1/chat/completions", provider_tag="exact")
    assert result["native_structured_output"] is False
    assert result["structured_output"] is False


def test_metadata_rejects_ambiguous_provider_tag():
    def route(request):
        if request.url.path.endswith("/endpoints"):
            endpoint = {"id": "exact", "provider_id": "exact", "model_name": "author/model", "context_length": 8192, "max_completion_tokens": 1024, "pricing": {"prompt": "0", "completion": "0"}}
            return httpx.Response(200, json={"data": [endpoint, dict(endpoint)]})
        return httpx.Response(200, json={"data": {"is_free_tier": False}})

    verifier = OpenRouterVerifier(http_client=httpx.Client(transport=httpx.MockTransport(route)))
    with pytest.raises(ValidationError, match="ambiguous"):
        verifier.verify("secret", "author/model", "https://openrouter.ai/api/v1/chat/completions", provider_tag="exact")


def test_adapter_requires_immutable_profile_and_explicit_output_allowance():
    with pytest.raises(ValueError, match="immutable verified profile"):
        OpenRouterAdapter("secret", "https://openrouter.ai/api/v1/chat/completions", profile={"model": "m"})
    adapter = OpenRouterAdapter("secret", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"}))))
    result = list(adapter.generate_text({"messages": []}))
    assert isinstance(result[-1], ProviderFailure) and result[-1].code == "CONFIG_INVALID"


def test_malformed_multiline_event_is_rejected_without_repair():
    body = b"data: {\"choices\":[{\"delta\":{\"content\":\"Xin\"}}]}\n" \
        b"data: {\"choices\":[{\"delta\":{\"content\":\"chao\"}}]}\n\n" \
        b"data: [DONE]\n\n"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=transport))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert isinstance(events[-1], ProviderFailure) and events[-1].code == "PROVIDER_ERROR"


def test_streaming_split_utf8_and_multiline_data_event_completes():
    first = b'{"choices":[{"delta":{"content":"Xin "}}]}'
    second = b'{"choices":[{"delta":{"content":"ch\xc3\xa0o"}}]}'
    stop = b'{"choices":[{"finish_reason":"stop"}]}'
    body = b"data: " + first + b"\r\n\r\n" + b"data: " + second + b"\r\n\r\n" + b"data: " + stop + b"\r\n\r\n" + b"data: [DONE]\r\n\r\n"
    split = body.index(b"\xc3")
    stream = _SplitStream([body[:split], body[split:split + 1], body[split + 1:split + 2], body[split + 2:]])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"}))
    adapter = OpenRouterAdapter("secret-key", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=transport))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert "".join(item for item in events if isinstance(item, str)) == "Xin chào"
    assert isinstance(events[-1], ProviderResult) and events[-1].finish_reason == "stop"


def test_length_refusal_and_schema_shape_are_not_successes():
    def response(body):
        return httpx.MockTransport(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    length = b'data: {"choices":[{"finish_reason":"length"}]}\n\ndata: [DONE]\n\n'
    adapter = OpenRouterAdapter("secret", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=response(length)))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert isinstance(events[-1], ProviderFailure) and events[-1].code == "OUTPUT_TRUNCATED"

    refusal = b'data: {"choices":[{"delta":{"refusal":"no"}}]}\n\ndata: [DONE]\n\n'
    adapter = OpenRouterAdapter("secret", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=response(refusal)))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 10}))
    assert isinstance(events[-1], ProviderFailure) and events[-1].code == "MODEL_REFUSED"

    structured = b'data: {"choices":[{"delta":{"content":"{\\"id\\":1}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    adapter = OpenRouterAdapter("secret", "https://openrouter.ai/api/v1/chat/completions", profile=_profile(), http_client=httpx.Client(transport=response(structured)))
    result = adapter.generate_structured({"messages": [], "reserved_completion_tokens": 10}, {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}, "additionalProperties": False})
    assert isinstance(result, ProviderFailure) and result.code == "SCHEMA_INVALID"


def test_dispatch_cost_rejects_unknown_and_accepts_fractional_cap():
    profile = {"endpoint": "x", "model": "m", "secret_version": "s", "pricing_verified": True, "credential_tier": "paid", "pricing": {"prompt": "0.000003", "completion": "0.000015"}}
    assert estimate_cost_usd(profile, 1000, 4000) == Decimal("0.063")
    with pytest.raises(ValidationError, match="cap"):
        validate_dispatch(profile, "capped_paid", {"input_tokens": 1000, "completion_tokens": 4000}, Decimal("0.01"))
    with pytest.raises(ValidationError, match="price"):
        validate_dispatch({**profile, "pricing": {}}, "capped_paid", {"input_tokens": 1, "completion_tokens": 1}, Decimal("0.01"))
    with pytest.raises(ValidationError, match="allowance"):
        validate_dispatch(profile, "capped_paid", {}, Decimal("0.01"))


def test_fake_provider_can_model_missing_terminal_and_cancellation():
    provider = FakeProvider([{"events": ["partial"], "finish_reason": None}, {"cancelled": True}])
    first = list(provider.generate_text({"stage": "narration"}))
    assert isinstance(first[-1], ProviderFailure) and first[-1].code == "MISSING_TERMINAL"
    second = list(provider.generate_text({"stage": "narration"}))
    assert isinstance(second[-1], ProviderFailure) and second[-1].code == "CANCELLED"
