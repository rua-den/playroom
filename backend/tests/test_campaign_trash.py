from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner, create_session
from playroom.campaigns import create_campaign, get_campaign, list_campaigns, trash_campaign
from playroom.db import connect, migrate
from playroom.domain import NotFound, StateConflict
from playroom.timeline import create_committed_revision, get_branch_head
from playroom.memory import append_memory_version, update_scene
from playroom.generation import GenerationService
from playroom.provider import FakeProvider
from playroom.settings import DEFAULT_TEST_CONTEXT_PROFILE


def _client(tmp_path, *, email="owner@example.test", password="secret owner password", generation_provider=None):
    path = tmp_path / "trash.sqlite3"
    connection = connect(path)
    migrate(connection)
    owner = create_owner(connection, email, password)
    token = create_session(connection, owner.id)
    connection.close()
    app = create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=generation_provider, context_model_profiles={DEFAULT_TEST_CONTEXT_PROFILE["profile_id"]: dict(DEFAULT_TEST_CONTEXT_PROFILE)})
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set("playroom_session", token)
    return client, path, owner


def _campaign(connection, owner, title="Synthetic story"):
    return create_campaign(connection, owner.id, title, {"name": "World"}, [], {"name": "Player"})


def test_trash_list_restore_is_durable_and_preserves_archive_and_history(tmp_path):
    client, path, owner = _client(tmp_path)
    connection = connect(path)
    campaign = _campaign(connection, owner)
    branch = campaign.initial_branch_id
    initial = get_branch_head(connection, campaign.id, branch)
    turn_id, revision_id = create_committed_revision(connection, campaign.id, branch, "Open the door", "Rain fills the street.", expected_state_version=initial.state_version)
    after_turn = get_branch_head(connection, campaign.id, branch)
    memory = append_memory_version(connection, campaign.id, branch, "event", "The street is wet", origin="user", expected_state_version=after_turn.state_version, source_revision_ids=[revision_id])
    after_memory = get_branch_head(connection, campaign.id, branch)
    scene_id = str(uuid4())
    scene_head = update_scene(connection, campaign.id, branch, {"focus_scene_id": scene_id, "scenes": [{"id": scene_id, "present_ids": []}]}, expected_state_version=after_memory.state_version)
    connection.execute("UPDATE campaigns SET archived_at=? WHERE id=?", ("2026-10-20T00:00:00Z", campaign.id))
    head = get_branch_head(connection, campaign.id, branch)
    before_rows = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE campaign_id=?", (campaign.id,)).fetchone()[0] for table in ("profile_versions", "memory_versions", "scene_versions", "turns", "state_checkpoints")}
    before_rows["turn_revisions"] = connection.execute("SELECT COUNT(*) FROM turn_revisions tr JOIN turns t ON t.id=tr.turn_id WHERE t.campaign_id=?", (campaign.id,)).fetchone()[0]
    before_ids = {"turn": turn_id, "revision": revision_id, "memory": memory.memory_id, "scene": scene_head.snapshot["scene_version_id"]}
    checkpoint_count = before_rows["state_checkpoints"]
    connection.close()

    headers = {"origin": "https://testserver"}
    deleted = client.delete(f"/api/campaigns/{campaign.id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"]
    assert deleted.json()["archived_at"] == "2026-10-20T00:00:00Z"
    assert client.get("/api/campaigns").json() == []
    assert client.get("/api/campaigns?trashed=true").json()[0]["id"] == campaign.id
    assert client.get(f"/api/campaigns/{campaign.id}").status_code == 404
    repeated_delete = client.delete(f"/api/campaigns/{campaign.id}", headers=headers).json()
    assert repeated_delete["deleted_at"] == deleted.json()["deleted_at"]

    reopened = connect(path)
    migrate(reopened)
    assert list_campaigns(reopened, owner.id, trashed=True)[0]["deleted_at"]
    reopened.close()

    restored = client.post(f"/api/campaigns/{campaign.id}/restore", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert restored.json()["archived_at"] == "2026-10-20T00:00:00Z"
    repeated_restore = client.post(f"/api/campaigns/{campaign.id}/restore", headers=headers).json()
    assert repeated_restore == restored.json()
    assert client.get("/api/campaigns").json()[0]["id"] == campaign.id
    connection = connect(path)
    assert get_branch_head(connection, campaign.id, branch).checkpoint_id == head.checkpoint_id
    assert connection.execute("SELECT COUNT(*) FROM state_checkpoints WHERE campaign_id=?", (campaign.id,)).fetchone()[0] == checkpoint_count
    after_rows = {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE campaign_id=?", (campaign.id,)).fetchone()[0] for table in ("profile_versions", "memory_versions", "scene_versions", "turns", "state_checkpoints")}
    after_rows["turn_revisions"] = connection.execute("SELECT COUNT(*) FROM turn_revisions tr JOIN turns t ON t.id=tr.turn_id WHERE t.campaign_id=?", (campaign.id,)).fetchone()[0]
    assert after_rows == before_rows
    assert connection.execute("SELECT id FROM turns WHERE id=?", (before_ids["turn"],)).fetchone()[0] == before_ids["turn"]
    assert connection.execute("SELECT id FROM turn_revisions WHERE id=? AND narrative_text=?", (before_ids["revision"], "Rain fills the street.")).fetchone()[0] == before_ids["revision"]
    assert connection.execute("SELECT id FROM memory_items WHERE id=?", (before_ids["memory"],)).fetchone()[0] == before_ids["memory"]
    assert connection.execute("SELECT id FROM scene_versions WHERE id=?", (before_ids["scene"],)).fetchone()[0] == before_ids["scene"]
    connection.close()


def test_trash_is_owner_scoped_and_requires_same_origin(tmp_path):
    client, path, owner = _client(tmp_path)
    connection = connect(path)
    campaign = _campaign(connection, owner)
    other = create_owner(connection, "other@example.test", "other password")
    other_token = create_session(connection, other.id)
    connection.close()
    headers = {"origin": "https://testserver"}

    assert client.delete(f"/api/campaigns/{campaign.id}", headers={"origin": "https://evil.example"}).status_code == 403
    foreign = TestClient(client.app, base_url="https://testserver")
    foreign.cookies.set("playroom_session", other_token)
    assert foreign.delete(f"/api/campaigns/{campaign.id}", headers=headers).status_code == 404
    assert foreign.get("/api/campaigns?trashed=true").json() == []
    assert client.delete(f"/api/campaigns/{campaign.id}", headers=headers).status_code == 200
    assert client.post(f"/api/campaigns/{campaign.id}/restore", headers={"origin": "https://evil.example"}).status_code == 403
    unauth = TestClient(client.app, base_url="https://testserver")
    assert unauth.post(f"/api/campaigns/{campaign.id}/restore", headers=headers).status_code == 401
    assert foreign.post(f"/api/campaigns/{campaign.id}/restore", headers=headers).status_code == 404


@pytest.mark.parametrize("status", ["queued", "running", "cancelling", "interrupted", "candidate"])
def test_trash_rejects_any_branch_guard_or_nonterminal_job(tmp_path, status):
    connection = connect(tmp_path / "guard.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "owner@example.test", "long enough password")
    campaign = _campaign(connection, owner)
    branch = campaign.initial_branch_id
    second_branch = str(uuid4())
    head = get_branch_head(connection, campaign.id, branch)
    connection.execute(
        "INSERT INTO branches(id,campaign_id,name,parent_branch_id,fork_checkpoint_id,state_version,head_checkpoint_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (second_branch, campaign.id, "alternate", branch, head.checkpoint_id, head.state_version, head.checkpoint_id, "2026-10-20T00:00:00Z"),
    )
    job_id = str(uuid4())
    connection.execute(
        "INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (job_id, owner.id, campaign.id, second_branch, "generation", "key", "hash", head.checkpoint_id, status, "2026-10-20T00:00:00Z"),
    )
    connection.execute("INSERT INTO generation_branch_guards(branch_id,generation_job_id,acquired_at) VALUES (?,?,?)", (second_branch, job_id, "2026-10-20T00:00:00Z"))
    with pytest.raises(StateConflict, match="generation"):
        trash_campaign(connection, campaign.id, owner.id)
    assert connection.execute("SELECT deleted_at FROM campaigns WHERE id=?", (campaign.id,)).fetchone()["deleted_at"] is None
    connection.close()


def test_stale_preview_after_trash_cannot_create_a_generation_job(tmp_path):
    client, path, _owner = _client(tmp_path, generation_provider=FakeProvider([]))
    headers = {"origin": "https://testserver"}
    created = client.post("/api/campaigns", json={"title": "Preview story", "world": {"name": "World"}, "persona": {"name": "Player"}}, headers=headers).json()
    detail = client.get(f"/api/campaigns/{created['id']}").json()
    preview = client.post(
        f"/api/campaigns/{created['id']}/context/previews",
        json={"branch_id": created["branch_id"], "action": "Look around", "profile_id": "fake-context-test"},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    assert client.delete(f"/api/campaigns/{created['id']}", headers=headers).status_code == 200
    generated = client.post(
        f"/api/campaigns/{created['id']}/generate",
        json={"branch_id": created["branch_id"], "action": "Look around", "idempotency_key": "stale-trash", "checkpoint_id": detail["checkpoint_id"], "preview_id": preview.json()["id"]},
        headers=headers,
    )
    assert generated.status_code in {404, 409}
    connection = connect(path)
    assert connection.execute("SELECT COUNT(*) FROM generation_jobs WHERE campaign_id=?", (created["id"],)).fetchone()[0] == 0
    connection.close()


def test_exact_and_new_idempotency_replay_after_trash_are_404_without_new_jobs(tmp_path):
    provider = FakeProvider([])
    client, path, _owner = _client(tmp_path, generation_provider=provider)
    headers = {"origin": "https://testserver"}
    created = client.post("/api/campaigns", json={"title": "Replay story", "world": {"name": "World"}, "persona": {"name": "Player"}}, headers=headers).json()
    detail = client.get(f"/api/campaigns/{created['id']}").json()
    body = {"branch_id": created["branch_id"], "action": "Wait", "idempotency_key": "exact-replay", "checkpoint_id": detail["checkpoint_id"]}
    first = client.post(f"/api/campaigns/{created['id']}/generate", json=body, headers=headers)
    assert first.status_code == 201, first.text
    connection = connect(path)
    connection.execute("UPDATE generation_jobs SET status='committed' WHERE id=?", (first.json()["id"],))
    connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (first.json()["id"],))
    connection.commit()
    assert client.delete(f"/api/campaigns/{created['id']}", headers=headers).status_code == 200
    jobs_before = connection.execute("SELECT COUNT(*) FROM generation_jobs WHERE campaign_id=?", (created["id"],)).fetchone()[0]
    calls_before = len(provider.calls)
    assert client.post(f"/api/campaigns/{created['id']}/generate", json=body, headers=headers).status_code == 404
    new_body = {**body, "idempotency_key": "new-after-trash"}
    assert client.post(f"/api/campaigns/{created['id']}/generate", json=new_body, headers=headers).status_code == 404
    assert connection.execute("SELECT COUNT(*) FROM generation_jobs WHERE campaign_id=?", (created["id"],)).fetchone()[0] == jobs_before
    assert len(provider.calls) == calls_before
    connection.close()


@pytest.mark.parametrize("status", ["committed", "failed", "cancelled"])
def test_terminal_job_history_remains_readable_but_trash_blocks_mutations(tmp_path, status):
    connection = connect(tmp_path / "terminal.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "owner@example.test", "long enough password")
    campaign = _campaign(connection, owner)
    branch = campaign.initial_branch_id
    checkpoint = get_branch_head(connection, campaign.id, branch).checkpoint_id
    job_id = str(uuid4())
    connection.execute(
        "INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,status,created_at,draft) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, owner.id, campaign.id, branch, "generation", "terminal-key", "terminal-hash", checkpoint, status, "2026-10-20T00:00:00Z", "finished draft"),
    )
    connection.execute("INSERT INTO generation_events(generation_job_id,event_type,created_at) VALUES (?,?,?)", (job_id, "committed", "2026-10-20T00:00:00Z"))
    trash_campaign(connection, campaign.id, owner.id)
    service = GenerationService(connection, FakeProvider([]))
    assert service.get_job(owner.id, job_id)["status"] == status
    assert len(service.content(owner.id, job_id)["draft"]) > 0
    assert len(service.events(owner.id, job_id)) == 1
    before = connection.execute("SELECT draft FROM generation_jobs WHERE id=?", (job_id,)).fetchone()["draft"]
    before_events = connection.execute("SELECT COUNT(*) FROM generation_events WHERE generation_job_id=?", (job_id,)).fetchone()[0]
    with pytest.raises(NotFound):
        service.cancel(owner.id, job_id)
    with pytest.raises(NotFound):
        service.edit_draft(owner.id, job_id, "changed")
    with pytest.raises(NotFound):
        service.commit_candidate(owner.id, job_id)
    assert connection.execute("SELECT draft FROM generation_jobs WHERE id=?", (job_id,)).fetchone()["draft"] == before
    assert connection.execute("SELECT COUNT(*) FROM generation_events WHERE generation_job_id=?", (job_id,)).fetchone()[0] == before_events
    connection.close()


def test_projection_and_generation_job_index_reject_trashed_campaign(tmp_path):
    connection = connect(tmp_path / "projection-trash.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "owner@example.test", "long enough password")
    campaign = _campaign(connection, owner)
    branch = campaign.initial_branch_id
    trash_campaign(connection, campaign.id, owner.id)
    from playroom.projections import get_campaign_projection, list_owned_generation_jobs
    with pytest.raises(NotFound):
        get_campaign_projection(connection, owner.id, campaign.id, branch)
    with pytest.raises(NotFound):
        list_owned_generation_jobs(connection, owner.id, campaign.id, branch)
    connection.close()


def test_old_database_gets_deleted_at_column_idempotently(tmp_path):
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript((__import__("pathlib").Path(__file__).parents[1] / "playroom/migrations/001_initial.sql").read_text(encoding="utf-8"))
    connection.close()
    migrated = connect(path)
    migrate(migrated)
    assert "deleted_at" in {row[1] for row in migrated.execute("PRAGMA table_info(campaigns)")}
    migrate(migrated)
    migrated.close()
