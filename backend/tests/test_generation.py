from __future__ import annotations

import pytest

from playroom.generation import GenerationService
from playroom.provider import FakeProvider, ProviderFailure
from playroom.db import connect, migrate
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.timeline import get_branch_head


def _story(tmp_path):
    db = connect(tmp_path / "generation.sqlite3")
    migrate(db)
    owner = create_owner(db, "generation@example.test", "generation password")
    campaign = create_campaign(db, owner.id, "Generation", {"name": "World"}, [], {"name": "Player"})
    return db, owner, campaign


def test_fake_provider_stream_completes_and_service_can_commit_candidate(tmp_path):
    db, owner, campaign = _story(tmp_path)
    provider = FakeProvider(["The rain pauses."])
    service = GenerationService(db, provider)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look outside", idempotency_key="req-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "candidate"
    assert job["attempts"] == ["narration"]
    committed = service.commit_candidate(owner.id, job["id"])
    assert committed["status"] == "committed"
    assert service.get_job(owner.id, job["id"])["status"] == "committed"


def test_idempotency_conflicting_payload_rejected_and_failure_stays_draft(tmp_path):
    db, owner, campaign = _story(tmp_path)
    service = GenerationService(db, FakeProvider([ProviderFailure("MODEL_REFUSED", "no")]))
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    first = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Wait", idempotency_key="req-2", expected_checkpoint_id=head.checkpoint_id)
    assert first["status"] == "failed"
    assert first["draft"] == ""
    with pytest.raises(Exception, match="idempotency"):
        service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Different", idempotency_key="req-2", expected_checkpoint_id=head.checkpoint_id)
