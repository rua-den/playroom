from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.context import build_candidate_pool
from playroom.db import connect, migrate
from playroom.domain import StateConflict
from playroom.generation import DEFAULT_PROFILE, GenerationService
from playroom.campaigns import update_profile
from playroom.provider import FakeProvider, ProviderFailure
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


def test_partial_output_is_draft_and_offsets_are_unicode_safe(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider([{"events": ["Xin ", "chào 👋"], "finish_reason": "length"}])
    service = GenerationService(db, provider)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="partial-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "failed"
    assert job["draft"] == "Xin chào 👋"
    assert job["attempt_details"][0]["output_offset"] == len("Xin chào 👋")
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


def test_candidate_guard_blocks_effective_story_mutation_until_commit(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    service = GenerationService(db, FakeProvider(["candidate"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="guard-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "candidate"
    with pytest.raises(StateConflict, match="locked"):
        update_profile(db, campaign.id, campaign.initial_branch_id, "world", {"name": "changed"}, expected_state_version=head.state_version, owner_id=owner.id)
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
        assert status.json()["status"] == "candidate"
        assert len(provider.calls) == 1
