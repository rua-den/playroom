from __future__ import annotations

import pytest
from uuid import uuid4

from playroom.campaigns import add_character, archive_campaign, create_campaign, get_campaign, get_effective_profile, remove_profile, rename_campaign, update_profile
from playroom.db import connect, migrate
from playroom.domain import StateConflict, ValidationError
from playroom.auth import create_owner
from playroom.timeline import get_branch_head, load_state_checkpoint, resolve_character_alias


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "playroom.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def owner(db):
    return create_owner(db, "owner@example.test", "strong test password")


def test_campaign_starts_with_branch_and_reopenable_checkpoint(db, owner, tmp_path):
    character_id = str(uuid4())
    campaign = create_campaign(
        db,
        owner_id=owner.id,
        title="Hành trình",
        world={"name": "Thành phố mưa"},
        characters=[{"id": character_id, "name": "Henn", "aliases": ["Hen"]}],
        persona={"name": "Henn", "agency_rule": "Người chơi điều khiển Henn"},
    )

    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    assert head.state_version == 1
    assert head.checkpoint_id
    checkpoint = load_state_checkpoint(db, campaign.id, campaign.initial_branch_id, head.checkpoint_id)
    assert checkpoint.snapshot["profile_versions"]
    assert checkpoint.snapshot["scene_version_id"] is not None
    from playroom.memory import get_effective_scene
    scene = get_effective_scene(db, campaign.id, campaign.initial_branch_id, head.checkpoint_id)
    assert scene["effective_cursor"] == {"state_version": 1, "checkpoint_id": head.checkpoint_id}

    path = db.execute("PRAGMA database_list").fetchone()[2]
    db.close()
    reopened = connect(path)
    migrate(reopened)
    assert get_branch_head(reopened, campaign.id, campaign.initial_branch_id).checkpoint_id == head.checkpoint_id
    assert get_effective_profile(reopened, campaign.id, campaign.initial_branch_id, head.checkpoint_id, "world")["name"] == "Thành phố mưa"
    reopened.close()


def test_profile_edits_create_new_version_without_mutating_old_checkpoint(db, owner):
    campaign = create_campaign(db, owner.id, "Nhật ký", {"name": "Mưa"}, [], {"name": "Tôi"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    old_checkpoint = head.checkpoint_id

    new_head = update_profile(
        db,
        campaign.id,
        campaign.initial_branch_id,
        "world",
        {"name": "Nắng"},
        expected_state_version=head.state_version,
    )

    assert get_effective_profile(db, campaign.id, campaign.initial_branch_id, old_checkpoint, "world")["name"] == "Mưa"
    assert get_effective_profile(db, campaign.id, campaign.initial_branch_id, new_head.id, "world")["name"] == "Nắng"
    with pytest.raises(StateConflict):
        update_profile(db, campaign.id, campaign.initial_branch_id, "world", {"name": "Sai"}, expected_state_version=1)


def test_ambiguous_alias_returns_both_character_ids_without_merging(db, owner):
    first_id, second_id = str(uuid4()), str(uuid4())
    campaign = create_campaign(
        db,
        owner.id,
        "Alias",
        {"name": "World"},
        [{"id": first_id, "name": "An", "aliases": ["Mây"]}, {"id": second_id, "name": "Bình", "aliases": ["may"]}],
        {"name": "Player"},
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    matches = resolve_character_alias(db, campaign.id, campaign.initial_branch_id, head.checkpoint_id, "MÂY")
    assert {profile["id"] for profile in matches} == {first_id, second_id}


def test_route_inventory_requires_owner_for_every_private_feature_route():
    from playroom.app import create_app

    app = create_app(database_url="sqlite:///:memory:", allowed_hosts={"testserver"})
    public = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("GET", "/health")}
    for route in app.routes:
        methods = getattr(route, "methods", set())
        path = getattr(route, "path", "")
        if path.startswith("/api/") and any(method in {"GET", "POST", "PATCH", "PUT", "DELETE"} for method in methods):
            for method in methods & {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                if (method, path) not in public:
                    assert any(dep.call.__name__ == "require_owner" for dep in route.dependant.dependencies), (method, path)


def test_campaign_crud_and_optional_character_membership_preserve_history(db, owner):
    campaign = create_campaign(db, owner.id, "Before", {"name": "World"}, [], {"name": "Player"})
    branch = campaign.initial_branch_id
    head = get_branch_head(db, campaign.id, branch)
    old_checkpoint = head.checkpoint_id
    added_id = str(uuid4())
    added = add_character(db, campaign.id, branch, {"id": added_id, "name": "Mây"}, expected_state_version=head.state_version, owner_id=owner.id)
    assert get_effective_profile(db, campaign.id, branch, added.id, f"character:{added_id}")["name"] == "Mây"
    removed = remove_profile(db, campaign.id, branch, f"character:{added_id}", expected_state_version=added.state_version, owner_id=owner.id)
    with pytest.raises(Exception, match="not present"):
        get_effective_profile(db, campaign.id, branch, removed.id, f"character:{added_id}")
    assert get_effective_profile(db, campaign.id, branch, added.id, f"character:{added_id}")["name"] == "Mây"
    with pytest.raises(ValidationError, match="required world"):
        remove_profile(db, campaign.id, branch, "world", expected_state_version=removed.state_version, owner_id=owner.id)
    renamed = rename_campaign(db, campaign.id, branch, "After", expected_state_version=removed.state_version, owner_id=owner.id)
    archived = archive_campaign(db, campaign.id, branch, expected_state_version=renamed["state_version"], owner_id=owner.id)
    result = get_campaign(db, campaign.id, owner.id)
    assert result["title"] == "After" and result["archived_at"]
    assert get_effective_profile(db, campaign.id, branch, old_checkpoint, "world")["name"] == "World"


def test_character_alias_validation_readd_versions_and_referenced_removal(db, owner):
    from playroom.memory import append_memory_version, update_scene
    from playroom.domain import ValidationError
    campaign = create_campaign(db, owner.id, "Actors", {"name": "World"}, [], {"name": "Player"})
    branch = campaign.initial_branch_id
    head = get_branch_head(db, campaign.id, branch)
    character_id = str(uuid4())
    with pytest.raises(ValidationError, match="aliases"):
        add_character(db, campaign.id, branch, {"id": character_id, "name": "Bad", "aliases": None}, expected_state_version=head.state_version, owner_id=owner.id)
    assert get_branch_head(db, campaign.id, branch).state_version == head.state_version
    added = add_character(db, campaign.id, branch, {"id": character_id, "name": "Good", "aliases": ["G"]}, expected_state_version=head.state_version, owner_id=owner.id)
    with pytest.raises(ValidationError, match="aliases"):
        update_profile(db, campaign.id, branch, f"character:{character_id}", {"id": character_id, "name": "Bad edit", "aliases": [None]}, expected_state_version=added.state_version, owner_id=owner.id)
    assert get_branch_head(db, campaign.id, branch).state_version == added.state_version
    removed = remove_profile(db, campaign.id, branch, f"character:{character_id}", expected_state_version=added.state_version, owner_id=owner.id)
    readded = add_character(db, campaign.id, branch, {"id": character_id, "name": "Good again", "aliases": ["G2"]}, expected_state_version=removed.state_version, owner_id=owner.id)
    profile_version = readded.snapshot["profile_versions"][f"character:{character_id}"]
    new_row = db.execute("SELECT version, supersedes_version_id FROM profile_versions WHERE id = ?", (profile_version,)).fetchone()
    assert new_row["version"] == 2
    assert new_row["supersedes_version_id"] == added.snapshot["profile_versions"][f"character:{character_id}"]

    actor_head = get_branch_head(db, campaign.id, branch)
    scene_id = str(uuid4())
    scene = update_scene(db, campaign.id, branch, {"focus_scene_id": scene_id, "scenes": [{"id": scene_id, "present_ids": [character_id]}]}, expected_state_version=actor_head.state_version)
    with pytest.raises(StateConflict, match="referenced"):
        remove_profile(db, campaign.id, branch, f"character:{character_id}", expected_state_version=scene.state_version, owner_id=owner.id)
    assert get_branch_head(db, campaign.id, branch).state_version == scene.state_version
    cleared_scene = update_scene(db, campaign.id, branch, {"focus_scene_id": scene_id, "scenes": [{"id": scene_id, "present_ids": []}]}, expected_state_version=scene.state_version)
    known = append_memory_version(db, campaign.id, branch, "event", "Character knows this", origin="user", expected_state_version=cleared_scene.state_version, source_revision_ids=[], knowledge_scope="known_by", known_by=[character_id])
    with pytest.raises(StateConflict, match="referenced"):
        remove_profile(db, campaign.id, branch, f"character:{character_id}", expected_state_version=known.state_version, owner_id=owner.id)
    assert get_branch_head(db, campaign.id, branch).state_version == known.state_version


def test_deleted_memory_tombstone_no_longer_blocks_character_removal(db, owner):
    from playroom.memory import append_memory_version, delete_memory, list_memory_history
    campaign = create_campaign(db, owner.id, "Deleted reference", {"name": "World"}, [{"id": str(uuid4()), "name": "Actor"}], {"name": "Player"})
    branch, actor_id = campaign.initial_branch_id, campaign.character_ids[0]
    head = get_branch_head(db, campaign.id, branch)
    memory = append_memory_version(db, campaign.id, branch, "event", "Actor knows", origin="user", expected_state_version=head.state_version, source_revision_ids=[], known_by=[actor_id], knowledge_scope="known_by")
    tombstone = delete_memory(db, campaign.id, branch, memory.memory_id, expected_state_version=memory.state_version)
    removed = remove_profile(db, campaign.id, branch, f"character:{actor_id}", expected_state_version=tombstone.state_version, owner_id=owner.id)
    history = list_memory_history(db, campaign.id, branch, memory.memory_id, tombstone.checkpoint_id)
    old = list_memory_history(db, campaign.id, branch, memory.memory_id, memory.checkpoint_id)
    assert removed.state_version == tombstone.state_version + 1
    assert old[-1].status == "approved" and old[-1].known_by == (actor_id,)
    assert history[-1].status == "deleted" and history[-1].known_by == (actor_id,)
