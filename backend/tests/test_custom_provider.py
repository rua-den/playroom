from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from playroom.domain import ValidationError
from playroom.model_profiles import normalize_custom_endpoint, validate_custom_profile, validate_dispatch, profile_hash, persist_model_profile, list_model_profiles
from playroom.provider import CustomOpenAIAdapter, ProviderResult


def test_custom_profile_route_saves_owner_declared_snapshot_without_catalog_call(tmp_path):
    from fastapi.testclient import TestClient
    from playroom.app import create_app
    from playroom.auth import create_owner
    from playroom.db import connect, migrate

    database = tmp_path / "custom.sqlite3"
    connection = connect(database)
    migrate(connection)
    first = create_owner(connection, "custom-one@example.test", "password-one")
    second = create_owner(connection, "custom-two@example.test", "password-two")
    connection.close()
    app = create_app(database_url=f"sqlite:///{database}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    origin = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": first.email, "password": "password-one"}, headers=origin).status_code == 200
    response = client.post("/api/provider/profiles/custom", json={
        "endpoint": "http://127.0.0.1:1234/v1", "model": "fixture-model",
    }, headers=origin)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["provider"] == "custom" and saved["secret_version"] is None
    assert saved["pricing_provenance"] == "unknown" and saved["pricing_verified"] is False
    assert client.post("/api/auth/logout", headers=origin).status_code == 204
    assert client.post("/api/auth/login", json={"email": second.email, "password": "password-two"}, headers=origin).status_code == 200
    assert client.get("/api/provider/profiles", headers=origin).json() == []


def test_custom_profiles_list_newest_first_even_when_ids_sort_inversely(tmp_path):
    from playroom.auth import create_owner
    from playroom.db import connect, migrate

    connection = connect(tmp_path / "ordering.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "ordering@example.test", "password-ordering")
    base = validate_custom_profile(endpoint="http://127.0.0.1:1234/v1", model="fixture")
    persist_model_profile(connection, owner.id, {**base, "id": "z-old"})
    persist_model_profile(connection, owner.id, {**base, "id": "a-new", "model": "fixture-new"})
    listed = list_model_profiles(connection, owner.id)
    assert [profile["id"] for profile in listed[:2]] == ["a-new", "z-old"]
    connection.close()


def test_custom_selection_preserves_oversized_owner_budget_but_uses_application_defaults(tmp_path):
    from playroom.auth import create_owner
    from playroom.db import connect, migrate
    from playroom.generation import GenerationService
    from playroom.model_profiles import persist_model_profile
    from playroom.provider import FakeProvider
    from playroom.settings import get_owner_settings, save_owner_settings

    connection = connect(tmp_path / "custom-budget.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "budget@example.test", "password-budget")
    profile = persist_model_profile(
        connection,
        owner.id,
        {**validate_custom_profile(endpoint="http://127.0.0.1:1234/v1", model="fixture"), "id": "custom-budget"},
    )
    saved = save_owner_settings(connection, owner.id, {
        "roles": {"narrator": {"id": profile["id"], "version": profile["version"]}},
        "mode": "economy",
        "policy": "free_only",
        "budgets": {"narrator": {"input_limit": 100000, "requested_output": 8000, "wrapper_buffer": 10000}},
    })
    assert saved["budgets"]["narrator"]["input_limit"] == 100000
    service = GenerationService(connection, FakeProvider([]), profile={"roles": {"narrator": profile}}, settings=saved)
    budget = service._role_budget(profile, saved, "narrator")
    assert budget["input_limit"] == 12000
    assert budget["requested_output"] == 4000
    assert budget["wrapper_buffer"] == 512
    assert get_owner_settings(connection, owner.id)["budgets"]["narrator"]["input_limit"] == 100000
    connection.close()


def test_custom_profile_route_rejects_extra_billing_fields_and_cross_owner_key(tmp_path):
    from fastapi.testclient import TestClient
    from playroom.app import create_app
    from playroom.auth import create_owner
    from playroom.db import connect, migrate

    database = tmp_path / "custom-extra.sqlite3"
    connection = connect(database)
    migrate(connection)
    first = create_owner(connection, "custom-a@example.test", "password-a-long")
    second = create_owner(connection, "custom-b@example.test", "password-b-long")
    connection.close()
    app = create_app(database_url=f"sqlite:///{database}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    origin = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": first.email, "password": "password-a-long"}, headers=origin).status_code == 200
    key = client.post("/api/provider/credentials", json={"secret": "fixture-key-a"}, headers=origin).json()["id"]
    extra = client.post("/api/provider/profiles/custom", json={"endpoint": "https://relay.example.test/v1", "model": "fixture", "billing": "paid_proxy"}, headers=origin)
    assert extra.status_code == 422
    assert client.post("/api/auth/logout", headers=origin).status_code == 204
    assert client.post("/api/auth/login", json={"email": second.email, "password": "password-b-long"}, headers=origin).status_code == 200
    cross_owner = client.post("/api/provider/profiles/custom", json={"endpoint": "https://relay.example.test/v1", "model": "fixture", "credential_id": key}, headers=origin)
    assert cross_owner.status_code == 422 and "fixture-key-a" not in cross_owner.text



@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1/chat/completions"),
        ("http://localhost:11434/v1/", "http://localhost:11434/v1/chat/completions"),
        ("https://relay.example.test/v1/chat/completions", "https://relay.example.test/v1/chat/completions"),
    ],
)
def test_custom_endpoint_accepts_base_or_completion_path(value, expected):
    assert normalize_custom_endpoint(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://10.0.0.2:1234/v1",
        "http://localhost.evil.test/v1",
        "https://relay.example.test/v1?token=secret",
        "https://user:pass@relay.example.test/v1",
        "https://relay.example.test/v1#fragment",
        "https://relay.example.test/v1/\nchat/completions",
    ],
)
def test_custom_endpoint_rejects_unsafe_or_non_loopback_http(value):
    with pytest.raises(ValidationError):
        normalize_custom_endpoint(value)


def test_custom_profile_owner_declared_local_metadata_is_dispatchable_without_key():
    profile = validate_custom_profile(endpoint="http://127.0.0.1:1234/v1", model="fixture-model")
    assert profile["endpoint"].endswith("/chat/completions")
    assert profile["secret_version"] is None
    assert profile["pricing_provenance"] == "unknown"
    persisted = {**profile, "profile_hash": profile_hash(profile)}
    validate_dispatch(persisted, "free_only", {"input_tokens": 0, "completion_tokens": 128})


def test_custom_adapter_pins_wire_and_omits_authorization_without_key():
    captured = {}
    body = b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: {"choices":[{"finish_reason":"stop"}],"usage":{"total_tokens":4}}\n\ndata: [DONE]\n\n'

    def route(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    profile = validate_custom_profile(endpoint="http://127.0.0.1:1234/v1", model="fixture-model")
    profile = {**profile, "profile_hash": profile_hash(profile)}
    adapter = CustomOpenAIAdapter(profile=profile, http_client=httpx.Client(transport=httpx.MockTransport(route)))
    events = list(adapter.generate_text({"messages": [], "reserved_completion_tokens": 32}))
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert "authorization" not in captured["headers"]
    assert captured["payload"] == {"model": "fixture-model", "messages": [], "max_tokens": 32, "stream": True}
    assert "".join(item for item in events if isinstance(item, str)) == "Hello"
    assert isinstance(events[-1], ProviderResult)


def test_custom_profile_keeps_billing_and_pricing_unknown():
    profile = validate_custom_profile(endpoint="https://relay.example.test/v1", model="fixture-model")
    assert profile["pricing"] is None
    assert profile["custom_billing"] == "provider_managed"
    assert profile["credential_tier"] == "unknown"


def test_custom_reservation_keeps_cost_totals_unknown_without_app_cap(tmp_path):
    from playroom.db import connect, migrate
    from playroom.generation import GenerationService
    from playroom.provider import FakeProvider

    connection = connect(tmp_path / "reservation.sqlite3")
    migrate(connection)
    profile = validate_custom_profile(endpoint="http://127.0.0.1:1234/v1", model="fixture")
    profile = {**profile, "id": "custom", "version": 1}
    profile["profile_hash"] = profile_hash({key: value for key, value in profile.items() if key not in {"version", "profile_hash"}})
    service = GenerationService(connection, FakeProvider([]), profile={"roles": {"narrator": profile}}, settings={"budgets": {"narrator": {"input_limit": 1000, "requested_output": 100, "wrapper_buffer": 32}}})
    ledger = service._reservation({"narrator": profile, "context": profile}, "economy", "capped_paid", None)
    assert ledger["cap"] is None and ledger["reserved_total_usd"] is None
    assert ledger["stages"]["narration"]["estimated_cost_usd"] is None


def test_custom_profile_can_bind_and_create_context_preview_without_pricing_claim(tmp_path):
    from fastapi.testclient import TestClient
    from playroom.app import create_app
    from playroom.auth import create_owner
    from playroom.campaigns import create_campaign
    from playroom.db import connect, migrate
    from playroom.timeline import get_branch_head

    database = tmp_path / "custom-integration.sqlite3"
    connection = connect(database); migrate(connection)
    owner = create_owner(connection, "custom-integration@example.test", "password-integration")
    campaign = create_campaign(connection, owner.id, "Custom", {"name": "Fixture"}, [], {"name": "Player"})
    head = get_branch_head(connection, campaign.id, campaign.initial_branch_id)
    connection.close()
    app = create_app(database_url=f"sqlite:///{database}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver"); origin = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "password-integration"}, headers=origin).status_code == 200
    saved = client.post("/api/provider/profiles/custom", json={"endpoint": "http://127.0.0.1:1234/v1", "model": "fixture"}, headers=origin)
    assert saved.status_code == 201
    profile = saved.json()
    settings = client.put("/api/provider/settings", json={"narrator_profile_id": profile["id"], "mode": "economy", "policy": "free_only"}, headers=origin)
    assert settings.status_code == 200, settings.text
    preview = client.post(f"/api/campaigns/{campaign.id}/context/previews", json={"branch_id": campaign.initial_branch_id, "action": "Look around", "profile_id": profile["id"]}, headers=origin)
    assert preview.status_code == 201, preview.text
    assert preview.json()["status"] in {"ready", "blocked"}
