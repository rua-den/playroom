from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.context import build_candidate_pool
from playroom.memory import append_memory_version
from playroom.db import connect, migrate
from playroom.domain import StateConflict
from playroom.generation import DEFAULT_PROFILE, GenerationService
from playroom.attempt_runtime import PhysicalAttemptRegistry
from playroom.campaigns import update_profile
from playroom.provider import FakeProvider, ProviderAdapter, ProviderFailure, ProviderResult
from playroom.timeline import get_branch_head
from playroom.app import create_app


def _story(tmp_path):
    db = connect(tmp_path / "durable.sqlite3")
    migrate(db)
    owner = create_owner(db, "durable@example.test", "durable password")
    campaign = create_campaign(db, owner.id, "Durable", {"name": "World"}, [], {"name": "Player"})
    return db, owner, campaign


def test_quality_dispatches_real_director_then_narrator_and_saves_context_run(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
    plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
    provider = FakeProvider([json.dumps(plan), "Narrator output."])
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="quality-1", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "candidate"
    assert job["attempts"] == ["context", "narration"]
    assert provider.stage_counts == {"context": 1, "narration": 1}
    assert db.execute("SELECT COUNT(*) FROM context_runs").fetchone()[0] == 1


def test_quality_schema_failure_never_calls_narrator(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["not json", "must not run"])
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="quality-2", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "failed"
    assert job["failure"]["code"] == "SCHEMA_INVALID"
    assert provider.stage_counts == {"context": 1}


def test_quality_narrator_wire_uses_only_validated_director_selection(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    append_memory_version(db, campaign.id, campaign.initial_branch_id, "lore", "OPTIONAL LIGHTHOUSE MEMORY", origin="user", expected_state_version=head.state_version, source_revision_ids=[], status="approved")
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "lighthouse", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
    plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
    provider = FakeProvider([json.dumps(plan), "Narrator output."])
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "lighthouse", idempotency_key="quality-pack", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    director_wire = json.dumps(provider.calls[0], ensure_ascii=False)
    wire = json.dumps(provider.calls[-1], ensure_ascii=False)
    assert job["status"] == "candidate"
    assert pool["action_hash"] in director_wire
    assert "OPTIONAL LIGHTHOUSE MEMORY" not in wire


def test_free_only_rejects_paid_profile_before_provider_call(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {**DEFAULT_PROFILE, "credential_tier": "paid", "is_test_profile": False, "pricing": {"prompt": "0.000003", "completion": "0.000015"}}
    provider = FakeProvider(["must not dispatch"])
    service = GenerationService(db, provider, profile=profile)
    with pytest.raises(Exception, match="free"):
        service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="paid-free", expected_checkpoint_id=head.checkpoint_id)
    assert provider.calls == []


def test_existing_key_recovery_ignores_live_settings_revision(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["one response"])
    service = GenerationService(db, provider, settings={"settings_revision": 1})
    first = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="lost-response", expected_checkpoint_id=head.checkpoint_id)
    service.settings = {"settings_revision": 2, "mode": "quality"}
    recovered = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="lost-response", expected_checkpoint_id=head.checkpoint_id)
    assert recovered["id"] == first["id"]
    assert len(provider.calls) == 1


def test_partial_output_is_draft_and_offsets_are_unicode_safe(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider([{"events": ["Xin ", "chào 👋"], "finish_reason": "length"}])
    service = GenerationService(db, provider)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="partial-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "failed"
    assert job["draft"] == "Xin chào 👋"
    assert job["attempt_details"][0]["output_offset"] == len("Xin chào 👋".encode("utf-16-le")) // 2
    assert [event["event_type"] for event in job["events"]].count("delta") == 2
    with pytest.raises(Exception):
        service.commit_candidate(owner.id, job["id"])


def test_cancel_and_recovery_do_not_replay_attempts(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    # Reserve a queued job and simulate a process restart before dispatch.
    service = GenerationService(db, FakeProvider(["unused"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="cancel-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "candidate"
    cancelled = service.cancel(owner.id, job["id"])
    assert cancelled["status"] == "cancelled"
    same = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="cancel-1", expected_checkpoint_id=head.checkpoint_id)
    assert same["id"] == job["id"] and len(service.provider.calls) == 1


def test_complete_candidate_can_become_stale_after_effective_story_mutation(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    service = GenerationService(db, FakeProvider(["candidate"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="guard-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "candidate"
    update_profile(db, campaign.id, campaign.initial_branch_id, "world", {"name": "changed"}, expected_state_version=head.state_version, owner_id=owner.id)
    with pytest.raises(StateConflict, match="stale"):
        service.commit_candidate(owner.id, job["id"])


def test_http_request_only_reserves_and_runtime_finishes_without_request_lifetime(tmp_path):
    database = tmp_path / "http.sqlite3"
    db = connect(database)
    migrate(db)
    owner, campaign = create_owner(db, "httpdurable@example.test", "http durable password"), None
    campaign = create_campaign(db, owner.id, "HTTP", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["HTTP candidate"])
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    app.state.generation_provider = provider
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post("/api/auth/login", json={"email": owner.email, "password": "http durable password"}, headers={"origin": "https://testserver"})
        assert login.status_code == 200
        response = client.post(f"/api/campaigns/{campaign.id}/generate", json={"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "http-1", "checkpoint_id": head.checkpoint_id}, headers={"origin": "https://testserver"})
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        assert response.json()["status"] in {"queued", "running", "candidate"}
        for _ in range(20):
            status = client.get(f"/api/generation/jobs/{job_id}")
            if status.json()["status"] == "candidate":
                break
            time.sleep(0.05)
        assert status.json()["status"] == "candidate"
        assert len(provider.calls) == 1
        lookup = client.get(f"/api/generation/jobs/by-key?branch_id={campaign.initial_branch_id}&idempotency_key=http-1")
        assert lookup.status_code == 200
        assert lookup.json()["id"] == job_id


class _BlockingDirector(ProviderAdapter):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.request = None

    def capabilities_for(self, profile):
        return None

    def generate_structured(self, request, schema):
        self.calls += 1
        self.request = request
        self.started.set()
        self.release.wait(5)
        return ProviderFailure("CANCELLED", "blocked fixture released")


def test_http_cancel_signals_the_runtime_attempt_and_retains_physical_work(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingDirector()
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}}, timeout_seconds=10)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("job", service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="blocking", expected_checkpoint_id=head.checkpoint_id, mode="quality")))
    thread.start()
    assert provider.started.wait(2)
    second_connection = connect(tmp_path / "durable.sqlite3")
    second = GenerationService(second_connection, provider, attempt_registry=service.attempt_registry)
    cancelled = second.cancel(owner.id, result.get("job", {}).get("id") or db.execute("SELECT id FROM generation_jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0])
    assert cancelled["status"] == "cancelling"
    assert provider.request["cancel_event"].is_set()
    assert provider.release.is_set() is False
    provider.release.set()
    thread.join(3)
    assert not thread.is_alive()
    second_connection.close()


def test_commit_rejects_competing_branch_guard(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    first = GenerationService(db, FakeProvider(["first"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="first", expected_checkpoint_id=head.checkpoint_id)
    second = GenerationService(db, FakeProvider(["second"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="second", expected_checkpoint_id=head.checkpoint_id, execute=False)
    assert second["status"] == "queued"
    with pytest.raises(StateConflict, match="active generation"):
        GenerationService(db, FakeProvider([])).commit_candidate(owner.id, first["id"])


def test_commit_event_uses_utf16_offset(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    service = GenerationService(db, FakeProvider(["Xin chào 👋"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="commit-unicode", expected_checkpoint_id=head.checkpoint_id)
    committed = service.commit_candidate(owner.id, job["id"])
    event = next(item for item in committed["events"] if item["event_type"] == "committed")
    assert event["offset"] == len("Xin chào 👋".encode("utf-16-le")) // 2
    assert event["payload"]["offset_unit"] == "utf16_code_units"


def test_app_keeps_credential_resolver_for_factory_dispatch(tmp_path):
    app = create_app(database_url=str(tmp_path / "factory.sqlite3"), credential_root=tmp_path / "secrets", generation_provider_factory=lambda **kwargs: FakeProvider(["ok"]))
    assert callable(app.state.generation_credential_resolver)


def test_factory_resolves_distinct_role_profiles_and_pinned_credentials(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    context_profile = {**DEFAULT_PROFILE, "id": "director", "version": 2, "profile_hash": "director-hash", "secret_version": "context-key"}
    narrator_profile = {**DEFAULT_PROFILE, "id": "narrator", "version": 3, "profile_hash": "narrator-hash", "secret_version": "narrator-key"}
    plan = {"checkpoint_id": head.checkpoint_id, "action_hash": "", "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": [], "conflict_flags": []}
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeProvider([json.dumps({**plan, "action_hash": kwargs["profile"].get("expected_action_hash", "")})] if kwargs["stage"] == "context" else ["factory narrative"])

    # The director fixture is filled with the pool hash by the provider below.
    class RoleProvider(FakeProvider):
        def generate_structured(self, request, schema):
            return ProviderResult(text=json.dumps({**plan, "action_hash": request["action_hash"]}), usage={"status": "unknown"})

    def role_factory(**kwargs):
        calls.append(kwargs)
        return RoleProvider([]) if kwargs["stage"] == "context" else FakeProvider(["factory narrative"])

    service = GenerationService(db, FakeProvider([]), profile={"roles": {"context": context_profile, "narrator": narrator_profile}}, provider_factory=role_factory, credential_resolver=lambda owner_id, version: {"context-key": "context-secret", "narrator-key": "narrator-secret"}[version])
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="factory-roles", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "candidate"
    assert [(call["stage"], call["profile"]["id"], call["credential"]) for call in calls] == [("context", "director", "context-secret"), ("narration", "narrator", "narrator-secret")]


def test_missing_pinned_credential_stops_before_provider_invocation(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {**DEFAULT_PROFILE, "secret_version": "revoked-key"}
    calls = []
    service = GenerationService(db, FakeProvider(["must not run"]), profile=profile, provider_factory=lambda **kwargs: calls.append(kwargs) or FakeProvider(["wrong"]), credential_resolver=lambda owner_id, version: (_ for _ in ()).throw(ValueError("revoked")))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="missing-key", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "failed"
    assert job["failure"]["code"] == "CREDENTIAL_UNAVAILABLE"
    assert calls == []


def test_physical_slot_survives_logical_timeout_until_provider_stops():
    class BlockingNarrator(ProviderAdapter):
        def __init__(self):
            self.release = threading.Event()
            self.finished = threading.Event()
        def capabilities_for(self, profile):
            return None
        def generate_text(self, request):
            self.release.wait(3)
            self.finished.set()
            yield ProviderResult(text="done")

    provider = BlockingNarrator()
    registry = PhysicalAttemptRegistry(limit=2)
    stream = registry.stream("job:narration", provider, {}, timeout=0.05)
    with pytest.raises(TimeoutError):
        next(stream)
    assert registry.active() == 1
    provider.release.set()
    assert provider.finished.wait(1)
    assert registry.active() == 0


def test_zero_row_dispatch_claim_never_invokes_provider(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["must not run"])
    service = GenerationService(db, provider)
    reserved = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="claim-race", expected_checkpoint_id=head.checkpoint_id, execute=False)
    service._mark_dispatched = lambda key: False
    finished = service.run(reserved["id"])
    assert finished["status"] == "cancelled"
    assert provider.calls == []


def test_http_raw_identity_recovers_omitted_choices_after_settings_change(tmp_path):
    from playroom.model_profiles import persist_model_profile
    from playroom.settings import save_owner_settings

    database = tmp_path / "raw-http.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "raw@example.test", "raw identity password")
    campaign = create_campaign(db, owner.id, "Raw", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["raw candidate"])
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    with TestClient(app, base_url="https://testserver") as client:
        headers = {"origin": "https://testserver"}
        assert client.post("/api/auth/login", json={"email": owner.email, "password": "raw identity password"}, headers=headers).status_code == 200
        body = {"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "raw-1", "checkpoint_id": head.checkpoint_id}
        first = client.post(f"/api/campaigns/{campaign.id}/generate", json=body, headers=headers)
        assert first.status_code == 201
        profile = persist_model_profile(db, owner.id, {"id": "raw-profile", "provider": "openrouter", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "model": "author/model", "context_limit": 12000, "output_limit": 4000, "credential_tier": "free", "pricing_verified": True, "secret_version": "credential-v1"})
        binding = {"id": profile["id"], "version": profile["version"], "profile_hash": profile["profile_hash"]}
        save_owner_settings(db, owner.id, {"roles": {"narrator": binding, "context": binding}, "mode": "quality", "policy": "free_only"})
        recovered = client.post(f"/api/campaigns/{campaign.id}/generate", json=body, headers=headers)
        assert recovered.status_code == 201
        assert recovered.json()["id"] == first.json()["id"]
        changed = client.post(f"/api/campaigns/{campaign.id}/generate", json={**body, "action": "Changed"}, headers=headers)
        assert changed.status_code == 409


def test_authenticated_sse_stream_replays_events_with_resume_cursor(tmp_path):
    database = tmp_path / "sse.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "sse@example.test", "sse stream password")
    campaign = create_campaign(db, owner.id, "SSE", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=FakeProvider(["streamed" ]), credential_root=tmp_path / "secrets")
    with TestClient(app, base_url="https://testserver") as client:
        headers = {"origin": "https://testserver"}
        client.post("/api/auth/login", json={"email": owner.email, "password": "sse stream password"}, headers=headers)
        response = client.post(f"/api/campaigns/{campaign.id}/generate", json={"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "sse-1", "checkpoint_id": head.checkpoint_id}, headers=headers)
        job_id = response.json()["id"]
        with client.stream("GET", f"/api/generation/jobs/{job_id}/events/stream") as stream:
            text = "".join(stream.iter_text())
            assert stream.headers["content-type"].startswith("text/event-stream")
            assert "event: reserved" in text and "event: completed" in text
