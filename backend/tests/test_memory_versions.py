from __future__ import annotations

import pytest
from uuid import uuid4

from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.domain import StateConflict
from playroom.auth import create_owner
from playroom.memory import append_memory_version, get_effective_scene, list_effective_memory, list_memory_proposals, reject_memory, approve_memory, set_retrieval_policy, update_scene
from playroom.timeline import get_branch_head, create_committed_revision


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "memory.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def owner(db):
    return create_owner(db, "owner@example.test", "strong test password")


def _campaign(db, owner, title):
    campaign = create_campaign(db, owner.id, title, {"name": "World"}, [{"id": str(uuid4()), "name": "Linh"}], {"name": "Player"})
    return campaign, campaign.initial_branch_id


def test_campaign_and_branch_scope_and_pending_approval(db, owner):
    one, branch_one = _campaign(db, owner, "One")
    two, branch_two = _campaign(db, owner, "Two")
    head_one = get_branch_head(db, one.id, branch_one)
    head_two = get_branch_head(db, two.id, branch_two)
    _, revision_id = create_committed_revision(db, one.id, branch_one, "Linh hứa sẽ trở lại", "Linh hứa sẽ trở lại.")
    head_one = get_branch_head(db, one.id, branch_one)
    approved = append_memory_version(db, one.id, branch_one, "promise", "Linh sẽ trở lại", origin="user", expected_state_version=head_one.state_version, source_revision_ids=[revision_id])
    pending = append_memory_version(db, one.id, branch_one, "event", "Linh đang cân nhắc", origin="ai", expected_state_version=approved.state_version, source_revision_ids=[revision_id])

    assert [item.text for item in list_effective_memory(db, one.id, branch_one, pending.checkpoint_id)] == ["Linh sẽ trở lại"]
    assert list_effective_memory(db, two.id, branch_two, head_two.checkpoint_id) == []


def test_single_valued_slot_conflict_requires_explicit_supersession(db, owner):
    campaign, branch = _campaign(db, owner, "Conflicts")
    head = get_branch_head(db, campaign.id, branch)
    first = append_memory_version(db, campaign.id, branch, "fact", "Linh cao 170cm", origin="user", expected_state_version=head.state_version, source_revision_ids=[], subject_id=campaign.character_ids[0], predicate="height", value="170cm")
    with pytest.raises(StateConflict, match="supersedes"):
        append_memory_version(db, campaign.id, branch, "fact", "Linh cao 180cm", origin="user", expected_state_version=first.state_version, source_revision_ids=[], subject_id=campaign.character_ids[0], predicate="height", value="180cm")
    second = append_memory_version(db, campaign.id, branch, "fact", "Linh cao 180cm", origin="user", expected_state_version=first.state_version, source_revision_ids=[], subject_id=campaign.character_ids[0], predicate="height", value="180cm", supersedes_id=first.memory_id)
    assert second.state_version == first.state_version + 1


def test_scene_presence_and_knowledge_are_explicit_and_checkpointed(db, owner):
    campaign, branch = _campaign(db, owner, "Scenes")
    head = get_branch_head(db, campaign.id, branch)
    actor_id = campaign.character_ids[0]
    focus_id, parallel_id = str(uuid4()), str(uuid4())
    scene = update_scene(db, campaign.id, branch, {"focus_scene_id": focus_id, "scenes": [{"id": focus_id, "location": "Ga", "present_ids": [actor_id], "time": "tối"}, {"id": parallel_id, "location": "Nhà", "present_ids": []}]}, expected_state_version=head.state_version)
    knowledge = append_memory_version(db, campaign.id, branch, "event", "Mira được nhắc đến", origin="user", expected_state_version=scene.state_version, source_revision_ids=[], knowledge_scope="narrator_only", known_by=[])
    old = list_effective_memory(db, campaign.id, branch, head.checkpoint_id)
    current = list_effective_memory(db, campaign.id, branch, knowledge.checkpoint_id)
    scene_state = get_effective_scene(db, campaign.id, branch, knowledge.checkpoint_id)
    assert old == []
    assert current[0].knowledge_scope == "narrator_only"
    assert current[0].known_by == ()
    assert scene_state["focus_scene_id"] == focus_id
    assert scene_state["scenes"][focus_id]["present_ids"] == [actor_id]
    assert "Mira" not in scene_state["scenes"][focus_id]["present_ids"]
    assert scene_state["scenes"][parallel_id]["present_ids"] == []


def test_pin_tombstone_and_retrieval_policy_do_not_rewrite_history(db, owner):
    campaign, branch = _campaign(db, owner, "Pins")
    head = get_branch_head(db, campaign.id, branch)
    event = append_memory_version(db, campaign.id, branch, "event", "Lời hứa", origin="user", expected_state_version=head.state_version, source_revision_ids=[])
    pinned = append_memory_version(db, campaign.id, branch, "event", "Lời hứa", origin="user", expected_state_version=event.state_version, source_revision_ids=[], memory_id=event.memory_id, pinned=True)
    hidden = append_memory_version(db, campaign.id, branch, "event", "Lời hứa", origin="user", expected_state_version=pinned.state_version, source_revision_ids=[], memory_id=event.memory_id, status="deleted", pinned=True)
    assert list_effective_memory(db, campaign.id, branch, event.checkpoint_id)[0].pinned is False
    assert list_effective_memory(db, campaign.id, branch, pinned.checkpoint_id)[0].pinned is True
    assert list_effective_memory(db, campaign.id, branch, hidden.checkpoint_id) == []

    auto = set_retrieval_policy(db, campaign.id, branch, "auto", expected_state_version=hidden.state_version)
    important = set_retrieval_policy(db, campaign.id, branch, "important_only", expected_state_version=auto.state_version)
    disabled = set_retrieval_policy(db, campaign.id, branch, "disabled", expected_state_version=important.state_version)
    assert auto.snapshot["retrieval_policy"] == "auto"
    assert important.snapshot["retrieval_policy"] == "important_only"
    assert disabled.snapshot["retrieval_policy"] == "disabled"


def test_optional_retrieval_modes_keep_mandatory_canon_and_filter_optional_events(db, owner):
    campaign, branch = _campaign(db, owner, "Modes")
    head = get_branch_head(db, campaign.id, branch)
    canon = append_memory_version(db, campaign.id, branch, "canon", "Henn luôn đi giày đỏ", origin="user", expected_state_version=head.state_version, source_revision_ids=[], mandatory=True)
    event = append_memory_version(db, campaign.id, branch, "event", "Linh hứa quay lại", origin="user", expected_state_version=canon.state_version, source_revision_ids=[])
    important = set_retrieval_policy(db, campaign.id, branch, "important_only", expected_state_version=event.state_version)
    assert [memory.kind for memory in list_effective_memory(db, campaign.id, branch, important.id)] == ["canon"]
    disabled = set_retrieval_policy(db, campaign.id, branch, "disabled", expected_state_version=important.state_version)
    assert [memory.kind for memory in list_effective_memory(db, campaign.id, branch, disabled.id)] == ["canon"]


def test_memory_rejects_uncommitted_or_foreign_source_revision(db, owner):
    campaign, branch = _campaign(db, owner, "Sources")
    head = get_branch_head(db, campaign.id, branch)
    from playroom.domain import ValidationError
    with pytest.raises(ValidationError, match="committed revision"):
        append_memory_version(db, campaign.id, branch, "event", "Chưa xảy ra", origin="ai", expected_state_version=head.state_version, source_revision_ids=[str(uuid4())])
    assert get_branch_head(db, campaign.id, branch).state_version == head.state_version


def test_memory_versions_keep_their_original_effective_cursor_at_later_reads(db, owner):
    campaign, branch = _campaign(db, owner, "As of")
    head = get_branch_head(db, campaign.id, branch)
    first = append_memory_version(db, campaign.id, branch, "event", "Linh hứa quay lại", origin="user", expected_state_version=head.state_version, source_revision_ids=[])
    later = append_memory_version(db, campaign.id, branch, "event", "Trời đổ mưa", origin="user", expected_state_version=first.state_version, source_revision_ids=[])
    at_later_head = list_effective_memory(db, campaign.id, branch, later.checkpoint_id)
    original = next(item for item in at_later_head if item.memory_id == first.memory_id)
    assert original.state_version == first.state_version
    assert original.checkpoint_id == first.checkpoint_id
    assert original.read_state_version == later.state_version
    assert original.read_checkpoint_id == later.checkpoint_id


def test_pending_ai_replacement_preserves_approved_fact_until_explicit_review(db, owner):
    campaign, branch = _campaign(db, owner, "Review")
    character_id = campaign.character_ids[0]
    head = get_branch_head(db, campaign.id, branch)
    approved = append_memory_version(db, campaign.id, branch, "fact", "Linh cao 170cm", origin="user", expected_state_version=head.state_version, source_revision_ids=[], subject_id=character_id, predicate="height", value="170cm")
    _, revision_id = create_committed_revision(db, campaign.id, branch, "Linh cao lên", "Linh nói chiều cao mới là 180cm.")
    after_turn = get_branch_head(db, campaign.id, branch)
    pending = append_memory_version(db, campaign.id, branch, "fact", "Linh cao 180cm", origin="ai", expected_state_version=after_turn.state_version, source_revision_ids=[revision_id], memory_id=approved.memory_id, subject_id=character_id, predicate="height", value="180cm")
    current = list_effective_memory(db, campaign.id, branch, pending.checkpoint_id)
    assert [item.text for item in current if item.memory_id == approved.memory_id] == ["Linh cao 170cm"]
    assert [item.text for item in list_memory_proposals(db, campaign.id, branch, pending.checkpoint_id)] == ["Linh cao 180cm"]

    rejected = reject_memory(db, campaign.id, branch, approved.memory_id, expected_state_version=pending.state_version)
    assert [item.text for item in list_effective_memory(db, campaign.id, branch, rejected.checkpoint_id) if item.memory_id == approved.memory_id] == ["Linh cao 170cm"]
    assert list_memory_proposals(db, campaign.id, branch, rejected.checkpoint_id) == []

    next_pending = append_memory_version(db, campaign.id, branch, "fact", "Linh cao 180cm", origin="ai", expected_state_version=rejected.state_version, source_revision_ids=[revision_id], memory_id=approved.memory_id, subject_id=character_id, predicate="height", value="180cm")
    accepted = approve_memory(db, campaign.id, branch, approved.memory_id, expected_state_version=next_pending.state_version)
    assert [item.text for item in list_effective_memory(db, campaign.id, branch, accepted.checkpoint_id) if item.memory_id == approved.memory_id] == ["Linh cao 180cm"]
