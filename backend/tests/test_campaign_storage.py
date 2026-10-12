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
