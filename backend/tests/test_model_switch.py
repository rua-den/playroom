from __future__ import annotations

from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.model_profiles import persist_model_profile, get_model_profile
from playroom.timeline import get_branch_head
from playroom.generation import GenerationService
from playroom.provider import FakeProvider


class StubVerifier:
    def verify(self, secret, model, endpoint, *, provider_tag=None):
        assert secret.startswith("sk-")
        supported = ["max_tokens", "response_format", "structured_outputs"]
        return {"id": "profile-a", "provider": "openrouter", "model": model, "model_id": model, "endpoint": endpoint, "provider_tag": provider_tag or "exact", "tag": provider_tag or "exact", "context_limit": 8192, "output_limit": 1024, "credential_tier": "free", "pricing_verified": True, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": supported, "native_structured_output": "structured_outputs" in supported and "response_format" in supported, "structured_schema_parameter": "response_format", "structured_output": "structured_outputs" in supported and "response_format" in supported}


def test_owner_provider_configuration_is_versioned_and_masked(tmp_path):
    database = tmp_path / "settings.sqlite3"
    connection = connect(database)
    migrate(connection)
    owner = create_owner(connection, "config@example.test", "config owner password")
    campaign = create_campaign(connection, owner.id, "Config", {"name": "World"}, [], {"name": "Player"})
    initial_checkpoint = get_branch_head(connection, campaign.id, campaign.initial_branch_id).checkpoint_id
    connection.close()
    app = create_app(database_url=f"sqlite:///{database}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets", provider_verifier=StubVerifier())
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": "config@example.test", "password": "config owner password"}, headers=headers).status_code == 200
    added = client.post("/api/provider/credentials", json={"secret": "sk-secret-value"}, headers=headers)
    assert added.status_code == 201
    credential = added.json()
    assert credential["secret"] is None and "sk-secret-value" not in added.text
    profiles = client.post("/api/provider/profiles/verify", json={"credential_id": credential["id"], "model": "author/model:free", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "provider_tag": "exact"}, headers=headers)
    assert profiles.status_code == 201, profiles.text
    profile_id = profiles.json()["id"]
    saved = client.put("/api/provider/settings", json={"narrator_profile_id": profile_id, "mode": "economy", "policy": "free_only"}, headers=headers)
    assert saved.status_code == 200
    revision = saved.json()["settings_revision"]
    assert revision == 1 and saved.json()["settings_hash"]
    again = client.put("/api/provider/settings", json={"context_profile_id": profile_id, "narrator_profile_id": profile_id, "mode": "quality", "policy": "free_only"}, headers=headers)
    assert again.json()["settings_revision"] == 2
    assert set(again.json()["roles"]) == {"context", "narrator"}
    all_roles = client.put("/api/provider/settings", json={"context_profile_id": profile_id, "narrator_profile_id": profile_id, "consolidation_profile_id": profile_id, "mode": "economy", "policy": "free_only"}, headers=headers)
    assert all_roles.status_code == 200
    assert set(all_roles.json()["roles"]) == {"context", "narrator", "consolidation"}
    assert get_branch_head(connect(database), campaign.id, campaign.initial_branch_id).checkpoint_id == initial_checkpoint
    connection = connect(database)
    assert connection.execute("SELECT COUNT(*) FROM owner_settings_versions").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM model_profile_versions").fetchone()[0] == 1
    settings = saved.json()
    assert settings["roles"]["narrator"]["version"] == 1
    connection.close()


def test_configuration_requires_quality_roles_and_redacts_invalid_secret(tmp_path):
    database = tmp_path / "invalid-config.sqlite3"
    connection = connect(database); migrate(connection); owner = create_owner(connection, "invalid@example.test", "invalid owner password"); connection.close()
    app = create_app(database_url=f"sqlite:///{database}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets", provider_verifier=StubVerifier())
    client = TestClient(app, base_url="https://testserver"); headers = {"origin": "https://testserver"}
    client.post("/api/auth/login", json={"email": "invalid@example.test", "password": "invalid owner password"}, headers=headers)
    secret = "sk-" + ("x" * 4094)
    response = client.post("/api/provider/credentials", json={"secret": secret}, headers=headers)
    assert response.status_code == 422 and secret not in response.text
    malformed = client.post("/api/provider/credentials", json={"secret": {"raw": "do-not-echo"}}, headers=headers)
    assert malformed.status_code == 422 and "do-not-echo" not in malformed.text
    added = client.post("/api/provider/credentials", json={"secret": "sk-valid"}, headers=headers)
    verified = client.post("/api/provider/profiles/verify", json={"credential_id": added.json()["id"], "model": "author/model", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "provider_tag": "exact"}, headers=headers)
    quality = client.put("/api/provider/settings", json={"narrator_profile_id": verified.json()["id"], "mode": "quality"}, headers=headers)
    assert quality.status_code == 422


def test_profile_reads_do_not_commit_callers_transaction(tmp_path):
    connection = connect(tmp_path / "profiles.sqlite3"); migrate(connection)
    owner = create_owner(connection, "read@example.test", "read owner password")
    profile = persist_model_profile(connection, owner.id, {"id": "p", "version": 1, "provider": "openrouter", "model": "author/model:free", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "provider_tag": "exact", "context_limit": 10, "output_limit": 5, "credential_tier": "free", "pricing_verified": True})
    connection.execute("CREATE TABLE marker(value TEXT)")
    connection.execute("BEGIN")
    connection.execute("INSERT INTO marker VALUES ('pending')")
    get_model_profile(connection, owner.id, profile["id"])
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM marker").fetchone()[0] == 0
    connection.close()


def test_short_secret_mask_and_revoked_version_are_safe(tmp_path):
    from playroom.credentials import CredentialStore
    from playroom.domain import ValidationError
    store = CredentialStore(tmp_path / "secrets")
    record = store.put("owner", "x")
    assert store.masked("owner", record.id)["masked"] == "***"
    store.revoke("owner", record.id)
    try:
        store.get("owner", record.id)
    except ValidationError as exc:
        assert "x" not in str(exc)
    else:
        raise AssertionError("revoked credential was readable")


def test_generation_status_and_commit_routes_have_no_provider_nameerror(tmp_path):
    database = tmp_path / "generation-api.sqlite3"
    connection = connect(database)
    migrate(connection)
    owner = create_owner(connection, "generation-api@example.test", "generation api password")
    campaign = create_campaign(connection, owner.id, "Generation API", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(connection, campaign.id, campaign.initial_branch_id)
    job = GenerationService(connection, FakeProvider(["A complete response."])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="api-1", expected_checkpoint_id=head.checkpoint_id)
    connection.close()
    app = create_app(database_url=f"sqlite:///{database}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets", provider_verifier=StubVerifier())
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/auth/login", json={"email": "generation-api@example.test", "password": "generation api password"}, headers={"origin": "https://testserver"})
    assert client.get(f"/api/generation/jobs/{job['id']}").status_code == 200
    committed = client.post(f"/api/generation/jobs/{job['id']}/commit", headers={"origin": "https://testserver"})
    assert committed.status_code == 200, committed.text
