from __future__ import annotations

import json
from uuid import uuid4

import pytest

from playroom.auth import create_owner
from playroom.campaigns import (
    add_character,
    archive_campaign,
    create_campaign,
    remove_profile,
    rename_campaign,
    update_profile,
)
from playroom.db import connect, migrate
from playroom.domain import StateConflict
from playroom.generation import GenerationService
from playroom.memory import (
    append_memory_version,
    approve_memory,
    delete_memory,
    reject_memory,
    set_retrieval_policy,
    update_memory,
    update_scene,
)
from playroom.provider import FakeProvider
from playroom.timeline import (
    create_committed_revision,
    create_state_checkpoint,
    get_branch_head,
    load_state_checkpoint,
)


def _fixture(tmp_path):
    db = connect(tmp_path / "mutation-guards.sqlite3")
    migrate(db)
    owner = create_owner(db, "mutation-guards@example.test", "mutation guards password")
    actor_id = str(uuid4())
    campaign = create_campaign(
        db,
        owner.id,
        "Mutation guards",
        {"name": "World"},
        [{"id": actor_id, "name": "Unused actor", "aliases": []}],
        {"name": "Player"},
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    approved = append_memory_version(
        db, campaign.id, campaign.initial_branch_id, "lore", "Approved memory",
        origin="user", expected_state_version=head.state_version,
        source_revision_ids=[], status="approved",
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pending = append_memory_version(
        db, campaign.id, campaign.initial_branch_id, "promise", "Pending memory",
        origin="user", expected_state_version=head.state_version,
        source_revision_ids=[], status="pending",
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    return {
        "db": db, "owner": owner, "campaign": campaign, "branch_id": campaign.initial_branch_id,
        "actor_key": f"character:{actor_id}", "actor_id": actor_id,
        "approved": approved, "pending": pending, "head": head,
    }


def _snapshot(fixture):
    db, campaign, branch_id = fixture["db"], fixture["campaign"], fixture["branch_id"]
    counts = {
        table: db.execute(f"SELECT COUNT(*) FROM {table} WHERE campaign_id=?", (campaign.id,)).fetchone()[0]
        for table in ("profile_versions", "memory_versions", "scene_versions", "state_checkpoints")
    }
    counts["turn_revisions"] = db.execute(
        "SELECT COUNT(*) FROM turn_revisions WHERE turn_id IN (SELECT id FROM turns WHERE campaign_id=?)",
        (campaign.id,),
    ).fetchone()[0]
    branch = db.execute("SELECT state_version,head_checkpoint_id FROM branches WHERE id=?", (branch_id,)).fetchone()
    campaign_row = db.execute("SELECT title,archived_at FROM campaigns WHERE id=?", (campaign.id,)).fetchone()
    checkpoint = db.execute("SELECT id,state_version,snapshot_json FROM state_checkpoints WHERE id=?", (branch["head_checkpoint_id"],)).fetchone()
    profiles = [tuple(row) for row in db.execute("SELECT profile_key,version,data_json FROM profile_versions WHERE campaign_id=? ORDER BY profile_key,version", (campaign.id,))]
    memories = [tuple(row) for row in db.execute("SELECT memory_id,version,status,text,pinned,entity_ids_json,known_by_json FROM memory_versions WHERE campaign_id=? ORDER BY memory_id,version", (campaign.id,))]
    scenes = [tuple(row) for row in db.execute("SELECT id,version,data_json FROM scene_versions WHERE campaign_id=? ORDER BY version,id", (campaign.id,))]
    return {
        "counts": counts, "branch": tuple(branch), "campaign": tuple(campaign_row),
        "checkpoint": tuple(checkpoint), "profiles": profiles, "memories": memories, "scenes": scenes,
    }


MUTATIONS = (
    "world_edit", "persona_edit", "style_edit", "actor_edit", "actor_add", "actor_remove",
    "rename", "archive", "memory_create_approved", "memory_create_pending", "memory_edit",
    "memory_pin", "memory_approve", "memory_reject", "memory_delete", "scene_edit",
    "retrieval_policy", "public_checkpoint", "public_revision",
)


def _apply(fixture, mutation):
    db, owner, campaign, branch_id = fixture["db"], fixture["owner"], fixture["campaign"], fixture["branch_id"]
    head = get_branch_head(db, campaign.id, branch_id)
    expected = head.state_version
    if mutation.endswith("_edit") and mutation.split("_")[0] in {"world", "persona", "style", "actor"}:
        key = mutation.removesuffix("_edit") if mutation != "actor_edit" else fixture["actor_key"]
        data = {"id": fixture["actor_id"], "name": "Changed", "aliases": []} if key.startswith("character:") else {"name": "Changed"}
        return update_profile(db, campaign.id, branch_id, key, data, expected_state_version=expected, owner_id=owner.id)
    if mutation == "actor_add":
        return add_character(db, campaign.id, branch_id, {"id": str(uuid4()), "name": "Added actor", "aliases": []}, expected_state_version=expected, owner_id=owner.id)
    if mutation == "actor_remove":
        return remove_profile(db, campaign.id, branch_id, fixture["actor_key"], expected_state_version=expected, owner_id=owner.id)
    if mutation == "rename":
        return rename_campaign(db, campaign.id, branch_id, "Renamed campaign", expected_state_version=expected, owner_id=owner.id)
    if mutation == "archive":
        return archive_campaign(db, campaign.id, branch_id, expected_state_version=expected, owner_id=owner.id)
    if mutation.startswith("memory_create"):
        status = "approved" if mutation.endswith("approved") else "pending"
        return append_memory_version(db, campaign.id, branch_id, "lore", f"New {status} memory", origin="user", expected_state_version=expected, source_revision_ids=[], status=status)
    if mutation == "memory_edit":
        return update_memory(db, campaign.id, branch_id, fixture["approved"].memory_id, expected_state_version=expected, text="Edited memory")
    if mutation == "memory_pin":
        return update_memory(db, campaign.id, branch_id, fixture["approved"].memory_id, expected_state_version=expected, pinned=True)
    if mutation == "memory_approve":
        return approve_memory(db, campaign.id, branch_id, fixture["pending"].memory_id, expected_state_version=expected)
    if mutation == "memory_reject":
        return reject_memory(db, campaign.id, branch_id, fixture["pending"].memory_id, expected_state_version=expected)
    if mutation == "memory_delete":
        return delete_memory(db, campaign.id, branch_id, fixture["approved"].memory_id, expected_state_version=expected)
    checkpoint = load_state_checkpoint(db, campaign.id, branch_id, head.checkpoint_id)
    if mutation == "scene_edit":
        scene = json.loads(db.execute("SELECT data_json FROM scene_versions WHERE id=?", (checkpoint.snapshot["scene_version_id"],)).fetchone()[0])
        scene = {"focus_scene_id": scene.get("focus_scene_id"), "scenes": list(scene.get("scenes", {}).values())}
        return update_scene(db, campaign.id, branch_id, scene, expected_state_version=expected)
    if mutation == "retrieval_policy":
        return set_retrieval_policy(db, campaign.id, branch_id, "disabled", expected_state_version=expected)
    if mutation == "public_checkpoint":
        return create_state_checkpoint(db, campaign.id, branch_id, dict(checkpoint.snapshot), expected)
    if mutation == "public_revision":
        return create_committed_revision(db, campaign.id, branch_id, "Look", "A complete narrative", expected_state_version=expected)
    raise AssertionError(mutation)


@pytest.mark.parametrize("mutation", MUTATIONS)
@pytest.mark.parametrize("phase", ["queued", "running"])
def test_every_story_mutation_is_guarded_for_queued_and_running_generation(tmp_path, mutation, phase):
    fixture = _fixture(tmp_path)
    db, owner, campaign = fixture["db"], fixture["owner"], fixture["campaign"]
    head = get_branch_head(db, campaign.id, fixture["branch_id"])
    job = GenerationService(db, FakeProvider([])).generate(
        owner.id, campaign.id, fixture["branch_id"], "Look", idempotency_key=f"guard-{mutation}-{phase}",
        expected_checkpoint_id=head.checkpoint_id, execute=False,
    )
    if phase == "running":
        db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (job["id"],))
        db.commit()
    before = _snapshot(fixture)
    with pytest.raises(StateConflict):
        _apply(fixture, mutation)
    assert _snapshot(fixture) == before


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_every_story_mutation_has_a_valid_unguarded_success_control(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    before = _snapshot(fixture)
    result = _apply(fixture, mutation)
    assert result is not None
    assert _snapshot(fixture) != before
