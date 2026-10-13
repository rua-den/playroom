from __future__ import annotations

import json
from uuid import uuid4

import pytest

import playroom.projections as projections
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.domain import NotFound
from playroom.projections import get_campaign_projection, list_owned_generation_jobs


def _story(tmp_path):
    db = connect(tmp_path / "projection.sqlite3")
    migrate(db)
    owner = create_owner(db, "owner@example.test", "secret owner password")
    campaign = create_campaign(db, owner.id, "Projection", {"name": "World"}, [{"id": str(uuid4()), "name": "Hero", "aliases": []}], {"name": "Persona"})
    return db, owner, campaign


def test_projection_preserves_checkpoint_selected_revision_order_with_inherited_and_duplicate_sequences(tmp_path):
    db, owner, campaign = _story(tmp_path)
    parent_branch = campaign.initial_branch_id
    parent_checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (parent_branch,)).fetchone()[0]
    child_branch = str(uuid4())
    child_checkpoint = str(uuid4())
    turn_a, turn_b = str(uuid4()), str(uuid4())
    revision_a, revision_b = str(uuid4()), str(uuid4())
    now = "2026-01-01T00:00:00Z"
    db.execute("INSERT INTO branches(id,campaign_id,name,parent_branch_id,fork_checkpoint_id,state_version,head_checkpoint_id,created_at) VALUES (?,?,?,?,?,?,?,?)", (child_branch, campaign.id, "child", parent_branch, parent_checkpoint, 2, child_checkpoint, now))
    db.execute("INSERT INTO turns(id,campaign_id,branch_id,sequence,action_text,created_at) VALUES (?,?,?,?,?,?)", (turn_a, campaign.id, parent_branch, 1, "A", now))
    db.execute("INSERT INTO turns(id,campaign_id,branch_id,sequence,action_text,created_at) VALUES (?,?,?,?,?,?)", (turn_b, campaign.id, child_branch, 1, "B", now))
    db.execute("INSERT INTO turn_revisions(id,turn_id,revision,narrative_text,complete,selected,created_at) VALUES (?,?,?,?,?,?,?)", (revision_a, turn_a, 1, "Narrative A", 1, 1, now))
    db.execute("INSERT INTO turn_revisions(id,turn_id,revision,narrative_text,complete,selected,created_at) VALUES (?,?,?,?,?,?,?)", (revision_b, turn_b, 1, "Narrative B", 1, 1, now))
    db.execute("INSERT INTO selected_revisions(branch_id,turn_id,revision_id) VALUES (?,?,?)", (parent_branch, turn_a, revision_a))
    db.execute("INSERT INTO selected_revisions(branch_id,turn_id,revision_id) VALUES (?,?,?)", (child_branch, turn_b, revision_b))
    parent_snapshot = json.loads(db.execute("SELECT snapshot_json FROM state_checkpoints WHERE id=?", (parent_checkpoint,)).fetchone()[0])
    parent_snapshot["selected_revision_ids"] = [revision_b, revision_a]
    db.execute("INSERT INTO state_checkpoints(id,campaign_id,branch_id,state_version,parent_checkpoint_id,snapshot_json,created_at) VALUES (?,?,?,?,?,?,?)", (child_checkpoint, campaign.id, child_branch, 2, parent_checkpoint, json.dumps(parent_snapshot), now))

    projection = get_campaign_projection(db, owner.id, campaign.id, child_branch)

    assert projection["branch"]["state_version"] == 2
    assert projection["checkpoint"]["id"] == child_checkpoint
    assert [item["revision_id"] for item in projection["transcript"]] == [revision_b, revision_a]
    assert [item["narrative_text"] for item in projection["transcript"]] == ["Narrative B", "Narrative A"]
    assert projection["profiles"]["world"]["data"] == {"name": "World"}
    assert projection["profiles"]["persona"]["data"] == {"name": "Persona"}
    db.close()


def test_projection_rejects_foreign_campaign_and_branch(tmp_path):
    db, owner, campaign = _story(tmp_path)
    other = create_owner(db, "other@example.test", "other secret password")
    foreign_campaign = create_campaign(db, other.id, "Other", {"name": "Other World"}, [], {"name": "Other Persona"})

    with pytest.raises(NotFound):
        get_campaign_projection(db, owner.id, foreign_campaign.id, foreign_campaign.initial_branch_id)
    with pytest.raises(NotFound):
        get_campaign_projection(db, owner.id, campaign.id, foreign_campaign.initial_branch_id)
    db.close()


def test_projection_uses_one_observed_branch_head(tmp_path, monkeypatch):
    db, owner, campaign = _story(tmp_path)
    branch = campaign.initial_branch_id
    old_checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (branch,)).fetchone()[0]
    old_snapshot = db.execute("SELECT snapshot_json FROM state_checkpoints WHERE id=?", (old_checkpoint,)).fetchone()[0]
    new_checkpoint = str(uuid4())
    db.execute("INSERT INTO state_checkpoints(id,campaign_id,branch_id,state_version,parent_checkpoint_id,snapshot_json,created_at) VALUES (?,?,?,?,?,?,?)", (new_checkpoint, campaign.id, branch, 2, old_checkpoint, old_snapshot, "2026-01-01T00:00:00Z"))
    original = projections._owned_branch

    def advance_after_observe(connection, owner_id, campaign_id, branch_id):
        row = original(connection, owner_id, campaign_id, branch_id)
        connection.execute("UPDATE branches SET state_version=2, head_checkpoint_id=? WHERE id=?", (new_checkpoint, branch_id))
        return row

    monkeypatch.setattr(projections, "_owned_branch", advance_after_observe)
    projection = projections.get_campaign_projection(db, owner.id, campaign.id, branch)

    assert projection["branch"]["state_version"] == 1
    assert projection["branch"]["checkpoint_id"] == old_checkpoint
    assert projection["checkpoint"]["state_version"] == projection["branch"]["state_version"]
    assert projection["checkpoint"]["id"] == projection["branch"]["checkpoint_id"]
    db.close()


def test_job_index_finds_owned_active_and_candidate_after_client_key_is_gone(tmp_path):
    db, owner, campaign = _story(tmp_path)
    branch = campaign.initial_branch_id
    checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (branch,)).fetchone()[0]
    for status in ("queued", "running", "cancelling", "interrupted", "candidate", "committed", "failed", "cancelled"):
        db.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner.id, campaign.id, branch, "generation", f"private-{status}", "hash", checkpoint, status, "2026-01-01T00:00:00Z"))

    jobs = list_owned_generation_jobs(db, owner.id, campaign.id, branch)

    assert {job["status"] for job in jobs} == {"queued", "running", "cancelling", "interrupted", "candidate", "committed", "failed", "cancelled"}
    assert all("idempotency_key" not in job for job in jobs)
    db.close()


def test_job_index_is_bounded_and_redacts_internal_fields(tmp_path):
    db, owner, campaign = _story(tmp_path)
    branch = campaign.initial_branch_id
    checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (branch,)).fetchone()[0]
    for index in range(30):
        db.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at,profile_snapshot_json,settings_snapshot_json,credential_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner.id, campaign.id, branch, "generation", f"private-{index}", "request-secret", checkpoint, "queued", f"2026-01-01T00:00:{index:02d}Z", '{"secret":"profile"}', '{"secret":"settings"}', "credential-secret"))

    jobs = list_owned_generation_jobs(db, owner.id, campaign.id, branch)

    assert len(jobs) <= 20
    assert all(set(job) <= {"id", "campaign_id", "branch_id", "checkpoint_id", "status", "mode", "action", "created_at", "cancel_requested"} for job in jobs)
    assert all("request_hash" not in job and "profile_snapshot" not in job and "credential_version" not in job for job in jobs)
    db.close()


def test_job_index_rejects_foreign_owner_and_branch(tmp_path):
    db, owner, campaign = _story(tmp_path)
    other = create_owner(db, "other@example.test", "other secret password")
    other_campaign = create_campaign(db, other.id, "Other", {"name": "Other World"}, [], {"name": "Other Persona"})

    with pytest.raises(NotFound):
        list_owned_generation_jobs(db, owner.id, campaign.id, other_campaign.initial_branch_id)
    with pytest.raises(NotFound):
        list_owned_generation_jobs(db, other.id, campaign.id, campaign.initial_branch_id)
    db.close()


def test_job_index_excludes_non_generation_operations(tmp_path):
    db, owner, campaign = _story(tmp_path)
    branch = campaign.initial_branch_id
    checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (branch,)).fetchone()[0]
    db.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner.id, campaign.id, branch, "consolidation", "internal", "secret", checkpoint, "queued", "2026-01-01T00:00:00Z"))

    assert list_owned_generation_jobs(db, owner.id, campaign.id, branch) == []
    db.close()


def test_job_index_prioritizes_recoverable_work_over_newer_terminal_rows(tmp_path):
    db, owner, campaign = _story(tmp_path)
    branch = campaign.initial_branch_id
    checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (branch,)).fetchone()[0]
    active_id = str(uuid4())
    db.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (active_id, owner.id, campaign.id, branch, "generation", "old-active", "hash", checkpoint, "running", "2026-01-01T00:00:00Z"))
    for index in range(25):
        db.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner.id, campaign.id, branch, "generation", f"terminal-{index}", "hash", checkpoint, "committed", f"2026-01-01T00:01:{index:02d}Z"))

    jobs = list_owned_generation_jobs(db, owner.id, campaign.id, branch)

    assert len(jobs) == 20
    assert active_id in {job["id"] for job in jobs}
    assert jobs[0]["status"] == "running"
    db.close()
