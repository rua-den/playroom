from __future__ import annotations

import pytest
from uuid import uuid4

from playroom.generation import DEFAULT_PROFILE, GenerationService
from playroom.provider import FakeProvider, ProviderFailure
from playroom.db import connect, migrate
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.timeline import get_branch_head, load_state_checkpoint
from playroom.memory import append_memory_version


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



def test_generation_fails_before_candidate_when_narrator_steals_player_action(tmp_path):
    db, owner, campaign = _story(tmp_path)
    profile = {
        **DEFAULT_PROFILE,
        "is_test_profile": False,
        "legacy_plain_output": False,
        "native_structured_output": False,
        "supported_parameters": [],
    }
    provider = FakeProvider([
        '{"segments":[{"kind":"narration","text":"Player gật đầu rồi đứng dậy."}]}'
    ])
    service = GenerationService(db, provider, profile=profile)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(
        owner.id,
        campaign.id,
        campaign.initial_branch_id,
        "Ừ, tôi nghe.",
        idempotency_key="agency-guard-1",
        expected_checkpoint_id=head.checkpoint_id,
    )

    assert job["status"] == "failed"
    assert job["failure"]["code"] == "PLAYER_AGENCY_VIOLATION"
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id == head.checkpoint_id
    with pytest.raises(Exception, match="complete candidate"):
        service.commit_candidate(owner.id, job["id"])


@pytest.mark.parametrize("action,text,expected_status", [
    ("**Player lo lắng.**", "Player vui mừng.", "failed"),
    ("**Player gấp tờ giấy xanh làm đôi.** Vy, giấu Bình có công bằng không?", "Vy nhìn khuôn mặt đang phân vân của Player.", "failed"),
    ("**Vy lo lắng nhìn Player.**", "Khuôn mặt đầy lo lắng của Player.", "failed"),
    ("Ừ.", "Vy nói với Player, giọng đầy lo lắng.", "candidate"),
    ("**Player lo lắng.**", "Khuôn mặt đầy lo lắng của Player.", "candidate"),
])
def test_specific_player_state_guard_controls_candidate_commit(tmp_path, action, text, expected_status):
    import json

    db, owner, campaign = _story(tmp_path)
    profile = {**DEFAULT_PROFILE, "is_test_profile": False, "legacy_plain_output": False,
               "native_structured_output": False, "supported_parameters": []}
    service = GenerationService(db, FakeProvider([json.dumps({"segments": [{"kind": "narration", "text": text}]})]), profile=profile)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, action,
                           idempotency_key="specific-state", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == expected_status
    if expected_status == "failed":
        assert job["failure"]["code"] == "PLAYER_AGENCY_VIOLATION"
        assert get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id == head.checkpoint_id
        with pytest.raises(Exception, match="complete candidate"):
            service.commit_candidate(owner.id, job["id"])
    else:
        assert service.commit_candidate(owner.id, job["id"])["status"] == "committed"



def test_generation_fails_before_candidate_when_npc_leaks_narrator_only_memory(tmp_path):
    db = connect(tmp_path / "knowledge-fence.sqlite3")
    migrate(db)
    owner = create_owner(db, "knowledge@example.test", "knowledge password")
    yuna_id = str(uuid4())
    campaign = create_campaign(
        db,
        owner.id,
        "Knowledge fence",
        {"name": "World"},
        [{"id": yuna_id, "name": "Yuna", "aliases": []}],
        {"name": "Henn"},
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    append_memory_version(
        db,
        campaign.id,
        campaign.initial_branch_id,
        "canon",
        "Mã B-17 là ngăn tủ số 17.",
        origin="user",
        expected_state_version=head.state_version,
        source_revision_ids=[],
        mandatory=True,
        knowledge_scope="narrator_only",
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    checkpoint = load_state_checkpoint(db, campaign.id, campaign.initial_branch_id, head.checkpoint_id)
    yuna_profile = checkpoint.snapshot["profile_versions"][f"character:{yuna_id}"]
    profile = {
        **DEFAULT_PROFILE,
        "is_test_profile": False,
        "legacy_plain_output": False,
        "native_structured_output": False,
        "supported_parameters": [],
    }
    provider = FakeProvider([
        '{"segments":[{"kind":"dialogue","text":"B17 chắc là mã của một ngăn tủ.",'
        f'"character_id":"{yuna_id}","profile_version_id":"{yuna_profile}"'
        '}]}'
    ])
    service = GenerationService(db, provider, profile=profile)
    job = service.generate(
        owner.id,
        campaign.id,
        campaign.initial_branch_id,
        "Yuna, cậu nghĩ sao?",
        idempotency_key="knowledge-fence-1",
        expected_checkpoint_id=head.checkpoint_id,
    )

    assert job["status"] == "failed"
    assert job["failure"]["code"] == "NPC_KNOWLEDGE_VIOLATION"
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id == head.checkpoint_id



def test_generation_fails_before_candidate_on_invented_exact_time(tmp_path):
    db, owner, campaign = _story(tmp_path)
    profile = {
        **DEFAULT_PROFILE,
        "is_test_profile": False,
        "legacy_plain_output": False,
        "native_structured_output": False,
        "supported_parameters": [],
    }
    provider = FakeProvider([
        '{"segments":[{"kind":"narration","text":"Đúng 17:12, tiếng chuông vang lên."}]}'
    ])
    service = GenerationService(db, provider, profile=profile)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(
        owner.id,
        campaign.id,
        campaign.initial_branch_id,
        "Tiếp tục.",
        idempotency_key="grounded-time-1",
        expected_checkpoint_id=head.checkpoint_id,
    )

    assert job["status"] == "failed"
    assert job["failure"]["code"] == "UNGROUNDED_PRECISION"
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id == head.checkpoint_id



def test_generation_fails_before_candidate_when_narrator_assigns_player_emotion(tmp_path):
    db, owner, campaign = _story(tmp_path)
    profile = {
        **DEFAULT_PROFILE,
        "is_test_profile": False,
        "legacy_plain_output": False,
        "native_structured_output": False,
        "supported_parameters": [],
    }
    provider = FakeProvider([
        '{"segments":[{"kind":"narration","text":"Player có vẻ lo lắng trước câu hỏi."}]}'
    ])
    service = GenerationService(db, provider, profile=profile)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    job = service.generate(
        owner.id,
        campaign.id,
        campaign.initial_branch_id,
        "Tôi nghe đây.",
        idempotency_key="agency-emotion-1",
        expected_checkpoint_id=head.checkpoint_id,
    )

    assert job["status"] == "failed"
    assert job["failure"]["code"] == "PLAYER_AGENCY_VIOLATION"
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id == head.checkpoint_id
