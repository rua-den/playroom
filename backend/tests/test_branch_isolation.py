"""Checkpoint-accurate branch forks. All fixture text is invented."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.campaigns import create_campaign, get_effective_profile, list_branches, update_profile
from playroom.chatgpt_import import assert_import_review_approved
from playroom.context import build_candidate_pool
from playroom.db import connect, migrate
from playroom.domain import NotFound, StateConflict
from playroom.generation import GenerationService
from playroom.memory import append_memory_version, get_effective_scene, list_effective_memory, list_memory_history, update_memory, update_scene
from playroom.projections import get_campaign_projection
from playroom.provider import FakeProvider
from playroom.timeline import create_committed_revision, fork_branch, get_branch_head, load_state_checkpoint


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "branches.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def owner(db):
    return create_owner(db, "branches@example.test", "synthetic strong password")


def _campaign(db, owner, title="Nhánh"):
    character_id = str(uuid4())
    campaign = create_campaign(
        db,
        owner.id,
        title,
        {"name": "Thị trấn"},
        [{"id": character_id, "name": "Vy"}],
        {"name": "Lan"},
    )
    return campaign, character_id


def _commit(db, campaign, branch_id, action, narrative):
    head = get_branch_head(db, campaign.id, branch_id)
    return create_committed_revision(
        db, campaign.id, branch_id, action, narrative, expected_state_version=head.state_version
    )


def test_fork_inherits_exactly_the_selected_checkpoint_and_continues_numbering(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    turn1, revision1 = _commit(db, campaign, branch_id, "*Lan đặt tờ giấy xuống.*", "Vy nhìn tờ giấy.")
    shared_head = get_branch_head(db, campaign.id, branch_id)
    turn2, _ = _commit(db, campaign, branch_id, "*Lan hỏi về chiếc hộp.*", "Vy lắc đầu.")
    current_head = get_branch_head(db, campaign.id, branch_id)

    fork = fork_branch(
        db,
        campaign.id,
        branch_id,
        shared_head.checkpoint_id,
        expected_state_version=current_head.state_version,
        owner_id=owner.id,
    )

    assert fork["inherited_turns"] == 1
    assert fork["head_turn_id"] == turn1
    assert fork["state_version"] == shared_head.state_version
    child_head = get_branch_head(db, campaign.id, fork["id"], owner.id)
    assert child_head.checkpoint_id == fork["checkpoint_id"]
    child_checkpoint = load_state_checkpoint(db, campaign.id, fork["id"], None, owner.id)
    assert child_checkpoint.snapshot["selected_revision_ids"] == [revision1]
    assert child_checkpoint.snapshot["turn_id"] == turn1

    child_projection = get_campaign_projection(db, owner.id, campaign.id, fork["id"])
    assert [row["turn_id"] for row in child_projection["transcript"]] == [turn1]
    parent_projection = get_campaign_projection(db, owner.id, campaign.id, branch_id)
    assert [row["turn_id"] for row in parent_projection["transcript"]] == [turn1, turn2]
    # The shared checkpoint itself is immutable and still belongs to the source branch.
    unchanged = load_state_checkpoint(db, campaign.id, branch_id, shared_head.checkpoint_id, owner.id)
    assert unchanged.snapshot["selected_revision_ids"] == [revision1]

    turn3, _ = _commit(db, campaign, fork["id"], "*Lan đi ra cửa.*", "Vy nhìn theo.")
    child_projection = get_campaign_projection(db, owner.id, campaign.id, fork["id"])
    assert [row["turn_id"] for row in child_projection["transcript"]] == [turn1, turn3]
    assert child_projection["transcript"][1]["sequence"] == 2
    parent_projection = get_campaign_projection(db, owner.id, campaign.id, branch_id)
    assert [row["turn_id"] for row in parent_projection["transcript"]] == [turn1, turn2]


def test_fork_excludes_profile_memory_and_scene_changes_after_its_checkpoint(db, owner):
    campaign, character_id = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    memory = append_memory_version(
        db,
        campaign.id,
        branch_id,
        "canon",
        "Chiếc hộp gỗ thuộc về Vy.",
        origin="user",
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
        source_revision_ids=[],
    )
    _commit(db, campaign, branch_id, "*Lan mở hộp.*", "Trong hộp có một tờ giấy.")
    fork_point = get_branch_head(db, campaign.id, branch_id)

    update_profile(
        db, campaign.id, branch_id, "world", {"name": "Bến cảng"}, expected_state_version=fork_point.state_version
    )
    update_memory(
        db,
        campaign.id,
        branch_id,
        memory.memory_id,
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
        text="Chiếc hộp gỗ thuộc về Lan.",
        knowledge_scope="narrator_only",
    )
    append_memory_version(
        db,
        campaign.id,
        branch_id,
        "event",
        "Lan đã nhìn thấy tờ giấy.",
        origin="user",
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
        source_revision_ids=[],
    )
    update_scene(
        db,
        campaign.id,
        branch_id,
        {
            "focus_scene_id": None,
            "scenes": [{"id": str(uuid4()), "name": "Cửa hàng", "present_ids": [character_id]}],
        },
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
    )
    current_head = get_branch_head(db, campaign.id, branch_id)

    fork = fork_branch(
        db,
        campaign.id,
        branch_id,
        fork_point.checkpoint_id,
        expected_state_version=current_head.state_version,
        owner_id=owner.id,
    )

    assert [item.text for item in list_effective_memory(db, campaign.id, fork["id"], None, owner_id=owner.id)] == [
        "Chiếc hộp gỗ thuộc về Vy."
    ]
    assert get_effective_profile(db, campaign.id, fork["id"], None, "world", owner.id)["name"] == "Thị trấn"
    assert get_effective_scene(db, campaign.id, fork["id"], None, owner_id=owner.id)["scenes"] == {}
    history = list_memory_history(db, campaign.id, fork["id"], memory.memory_id, None, owner_id=owner.id)
    assert [(item.version, item.text) for item in history] == [(1, "Chiếc hộp gỗ thuộc về Vy.")]
    parent_history = list_memory_history(db, campaign.id, branch_id, memory.memory_id, None, owner_id=owner.id)
    assert [item.version for item in parent_history] == [1, 2]
    assert get_effective_profile(db, campaign.id, branch_id, None, "world", owner.id)["name"] == "Bến cảng"
    assert len(get_effective_scene(db, campaign.id, branch_id, None, owner_id=owner.id)["scenes"]) == 1


def test_fork_history_excludes_memory_versions_written_into_the_parent_future(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    memory = append_memory_version(
        db,
        campaign.id,
        branch_id,
        "canon",
        "Chiếc hộp gỗ thuộc về Vy.",
        origin="user",
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
        source_revision_ids=[],
    )
    _commit(db, campaign, branch_id, "*Lan mở hộp.*", "Trong hộp có một tờ giấy.")
    shared = get_branch_head(db, campaign.id, branch_id)
    fork = fork_branch(db, campaign.id, branch_id, shared.checkpoint_id, expected_state_version=shared.state_version, owner_id=owner.id)

    update_memory(
        db,
        campaign.id,
        branch_id,
        memory.memory_id,
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
        text="Chiếc hộp gỗ đã bị đốt.",
    )
    _commit(db, campaign, branch_id, "*Lan đốt chiếc hộp.*", "Khói bay lên.")
    _commit(db, campaign, fork["id"], "*Lan đẩy hộp.*", "Vy nhìn theo.")
    _commit(db, campaign, fork["id"], "*Lan mở nắp.*", "Bên trong trống.")
    child_head = get_branch_head(db, campaign.id, fork["id"], owner.id)
    assert child_head.state_version > shared.state_version + 1

    assert [item.version for item in list_memory_history(db, campaign.id, fork["id"], memory.memory_id, None, owner_id=owner.id)] == [1]
    assert [item.text for item in list_memory_history(db, campaign.id, fork["id"], memory.memory_id, None, owner_id=owner.id)] == [
        "Chiếc hộp gỗ thuộc về Vy."
    ]
    assert [item.text for item in list_effective_memory(db, campaign.id, fork["id"], None, owner_id=owner.id)] == [
        "Chiếc hộp gỗ thuộc về Vy."
    ]
    assert [item.version for item in list_memory_history(db, campaign.id, branch_id, memory.memory_id, None, owner_id=owner.id)] == [1, 2]


def test_forked_branches_keep_their_own_outcome_and_a_shared_cutoff_has_neither(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    turn1, _ = _commit(db, campaign, branch_id, "*Lan ngồi xuống bàn cờ.*", "Vy chờ nước đi đầu tiên.")
    shared = get_branch_head(db, campaign.id, branch_id)

    wins = fork_branch(db, campaign.id, branch_id, shared.checkpoint_id, expected_state_version=shared.state_version, owner_id=owner.id, name="Thắng")
    loses = fork_branch(db, campaign.id, branch_id, shared.checkpoint_id, expected_state_version=shared.state_version, owner_id=owner.id)
    _commit(db, campaign, wins["id"], "*Lan hạ quân cuối.*", "Lan thắng ván cờ.")
    _commit(db, campaign, loses["id"], "*Lan hạ quân cuối.*", "Lan thua ván cờ.")

    after = get_branch_head(db, campaign.id, branch_id)
    cutoff = fork_branch(
        db, campaign.id, branch_id, shared.checkpoint_id, expected_state_version=after.state_version, owner_id=owner.id
    )

    def narrative(branch):
        return [row["narrative_text"] for row in get_campaign_projection(db, owner.id, campaign.id, branch)["transcript"]]

    assert narrative(wins["id"]) == ["Vy chờ nước đi đầu tiên.", "Lan thắng ván cờ."]
    assert narrative(loses["id"]) == ["Vy chờ nước đi đầu tiên.", "Lan thua ván cờ."]
    assert narrative(cutoff["id"]) == ["Vy chờ nước đi đầu tiên."]
    assert narrative(branch_id) == ["Vy chờ nước đi đầu tiên."]
    assert get_campaign_projection(db, owner.id, campaign.id, wins["id"])["transcript"][1]["sequence"] == 2
    assert get_campaign_projection(db, owner.id, campaign.id, loses["id"])["transcript"][1]["sequence"] == 2
    assert {(row["id"], row["parent_branch_id"]) for row in list_branches(db, campaign.id, owner.id)} == {
        (branch_id, None),
        (wins["id"], branch_id),
        (loses["id"], branch_id),
        (cutoff["id"], branch_id),
    }
    assert wins["name"] == "Thắng"
    assert loses["name"] == "Nhánh 3"


def test_fork_requires_current_source_state_and_no_active_generation(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    head = get_branch_head(db, campaign.id, branch_id)

    with pytest.raises(StateConflict, match="state changed"):
        fork_branch(db, campaign.id, branch_id, head.checkpoint_id, expected_state_version=head.state_version + 1, owner_id=owner.id)

    GenerationService(db, FakeProvider([])).generate(
        owner.id,
        campaign.id,
        branch_id,
        "Đợi một lát.",
        idempotency_key="lock-1",
        expected_checkpoint_id=head.checkpoint_id,
        execute=False,
    )
    with pytest.raises(StateConflict, match="locked"):
        fork_branch(db, campaign.id, branch_id, head.checkpoint_id, expected_state_version=head.state_version, owner_id=owner.id)
    assert len(list_branches(db, campaign.id, owner.id)) == 1


def test_fork_rejects_unknown_foreign_and_unowned_checkpoints(db, owner):
    campaign, _ = _campaign(db, owner)
    other_campaign, _ = _campaign(db, owner, title="Khác")
    other_branch = other_campaign.initial_branch_id
    other_checkpoint = get_branch_head(db, other_campaign.id, other_branch).checkpoint_id
    branch_id = campaign.initial_branch_id
    head = get_branch_head(db, campaign.id, branch_id)

    with pytest.raises(NotFound):
        fork_branch(db, campaign.id, branch_id, other_checkpoint, expected_state_version=head.state_version, owner_id=owner.id)
    with pytest.raises(NotFound):
        fork_branch(db, campaign.id, branch_id, str(uuid4()), expected_state_version=head.state_version, owner_id=owner.id)
    with pytest.raises(NotFound):
        fork_branch(db, campaign.id, branch_id, head.checkpoint_id, expected_state_version=head.state_version, owner_id=str(uuid4()))
    assert len(list_branches(db, campaign.id, owner.id)) == 1
    assert len(list_branches(db, other_campaign.id, owner.id)) == 1


def test_fork_keeps_the_import_review_chain_that_gates_send(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    head = get_branch_head(db, campaign.id, branch_id)
    db.execute(
        "INSERT INTO chatgpt_import_sources(id, owner_id, campaign_id, branch_id, import_key, payload_hash, source_conversation_id, selected_source_json, paired_turns, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid4()), owner.id, campaign.id, branch_id, "import-1", "hash-1", "synthetic-thread", "{}", 1, "2026-10-25T00:00:00Z"),
    )
    db.execute(
        "INSERT INTO import_review_checkpoints(campaign_id, owner_id, source_checkpoint_id, review_json, created_at) VALUES (?, ?, ?, '{}', ?)",
        (campaign.id, owner.id, head.checkpoint_id, "2026-10-25T00:00:00Z"),
    )

    fork = fork_branch(db, campaign.id, branch_id, head.checkpoint_id, expected_state_version=head.state_version, owner_id=owner.id)
    assert load_state_checkpoint(db, campaign.id, fork["id"], None, owner.id).parent_checkpoint_id == head.checkpoint_id
    with pytest.raises(StateConflict, match="review approval"):
        assert_import_review_approved(db, owner.id, campaign.id, fork["checkpoint_id"])

    db.execute(
        "UPDATE import_review_checkpoints SET approved_checkpoint_id = ? WHERE campaign_id = ?",
        (head.checkpoint_id, campaign.id),
    )
    assert_import_review_approved(db, owner.id, campaign.id, fork["checkpoint_id"])


def test_forked_branch_generates_from_inherited_context_and_commits_locally(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    memory = append_memory_version(
        db,
        campaign.id,
        branch_id,
        "canon",
        "Chiếc hộp gỗ thuộc về Vy.",
        origin="user",
        expected_state_version=get_branch_head(db, campaign.id, branch_id).state_version,
        source_revision_ids=[],
    )
    turn1, _ = _commit(db, campaign, branch_id, "*Lan mở hộp.*", "Trong hộp có một tờ giấy.")
    shared = get_branch_head(db, campaign.id, branch_id)
    turn2, _ = _commit(db, campaign, branch_id, "*Lan cất tờ giấy đi.*", "Vy không nhìn thấy tờ giấy.")
    current = get_branch_head(db, campaign.id, branch_id)

    fork = fork_branch(db, campaign.id, branch_id, shared.checkpoint_id, expected_state_version=current.state_version, owner_id=owner.id)
    pool = build_candidate_pool(db, campaign.id, fork["id"], "*Lan đẩy chiếc hộp.*", checkpoint_id=fork["checkpoint_id"], owner_id=owner.id)
    assert [item["turn_id"] for item in pool["recent_context"]] == [turn1]
    candidates = [*pool["mandatory"], *pool["optional"]]
    assert any("Chiếc hộp gỗ thuộc về Vy." in item["text"] for item in candidates)
    inherited_memory = [item for item in candidates if item["text"] == "Chiếc hộp gỗ thuộc về Vy."]
    assert [item["branch_id"] for item in inherited_memory] == [fork["id"]]
    service = GenerationService(db, FakeProvider(["Vy nhìn chiếc hộp rồi quay đi."]))
    job = service.generate(owner.id, campaign.id, fork["id"], "*Lan đẩy chiếc hộp về phía Vy.*", idempotency_key="fork-1", expected_checkpoint_id=fork["checkpoint_id"])
    assert job["status"] == "candidate", job
    service.commit_candidate(owner.id, job["id"])

    transcript = get_campaign_projection(db, owner.id, campaign.id, fork["id"])["transcript"]
    assert transcript[0]["turn_id"] == turn1
    assert [row["sequence"] for row in transcript] == [1, 2]
    assert turn2 not in {row["turn_id"] for row in transcript}
    assert [row["action_text"] for row in transcript] == ["*Lan mở hộp.*", "*Lan đẩy chiếc hộp về phía Vy.*"]

    parent_transcript = get_campaign_projection(db, owner.id, campaign.id, branch_id)["transcript"]
    assert len(parent_transcript) == 2
    assert [item.text for item in list_effective_memory(db, campaign.id, fork["id"], None, owner_id=owner.id)] == [
        "Chiếc hộp gỗ thuộc về Vy."
    ]

    update_memory(
        db,
        campaign.id,
        fork["id"],
        memory.memory_id,
        expected_state_version=get_branch_head(db, campaign.id, fork["id"], owner.id).state_version,
        text="Chiếc hộp gỗ thuộc về Lan.",
    )
    assert [item.text for item in list_effective_memory(db, campaign.id, fork["id"], None, owner_id=owner.id)] == [
        "Chiếc hộp gỗ thuộc về Lan."
    ]
    assert [item.text for item in list_effective_memory(db, campaign.id, branch_id, None, owner_id=owner.id)] == [
        "Chiếc hộp gỗ thuộc về Vy."
    ]
    assert [item.version for item in list_memory_history(db, campaign.id, fork["id"], memory.memory_id, None, owner_id=owner.id)] == [1, 2]


def test_projection_exposes_fork_sources_for_current_and_inherited_turns(db, owner):
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    turn1, _ = _commit(db, campaign, branch_id, "*Lan mở hộp.*", "Trong hộp có một tờ giấy.")
    shared = get_branch_head(db, campaign.id, branch_id)
    _commit(db, campaign, branch_id, "*Lan cất tờ giấy đi.*", "Vy không nhìn thấy tờ giấy.")
    current = get_branch_head(db, campaign.id, branch_id)
    fork = fork_branch(db, campaign.id, branch_id, shared.checkpoint_id, expected_state_version=current.state_version, owner_id=owner.id)
    turn3, _ = _commit(db, campaign, fork["id"], "*Lan đẩy hộp.*", "Vy nhìn theo.")

    transcript = get_campaign_projection(db, owner.id, campaign.id, fork["id"])["transcript"]
    inherited, local = transcript
    assert inherited["turn_id"] == turn1
    assert inherited["turn_branch_id"] == branch_id
    assert inherited["turn_checkpoint_id"] == shared.checkpoint_id
    assert local["turn_id"] == turn3
    assert local["turn_branch_id"] == fork["id"]
    assert local["turn_checkpoint_id"] not in {None, fork["checkpoint_id"], shared.checkpoint_id}

    parent_head = get_branch_head(db, campaign.id, branch_id, owner.id)
    nested = fork_branch(
        db,
        campaign.id,
        inherited["turn_branch_id"],
        inherited["turn_checkpoint_id"],
        expected_state_version=parent_head.state_version,
        owner_id=owner.id,
    )
    assert nested["inherited_turns"] == 1
    nested_transcript = get_campaign_projection(db, owner.id, campaign.id, nested["id"])["transcript"]
    assert [row["turn_id"] for row in nested_transcript] == [turn1]

    listed = {item["id"]: item for item in list_branches(db, campaign.id, owner.id)}
    assert listed[fork["id"]]["fork_turn_sequence"] == 1
    assert listed[branch_id]["fork_turn_sequence"] is None


def test_candidate_reroll_on_one_branch_commits_only_the_chosen_version(tmp_path):
    db = connect(tmp_path / "reroll.sqlite3")
    migrate(db)
    owner = create_owner(db, "reroll@example.test", "synthetic strong password")
    campaign, _ = _campaign(db, owner)
    branch_id = campaign.initial_branch_id
    head = get_branch_head(db, campaign.id, branch_id)
    service = GenerationService(db, FakeProvider(["Bản nháp đầu.", "Bản nháp thứ hai."]))

    first = service.generate(owner.id, campaign.id, branch_id, "Nhìn ra cửa.", idempotency_key="reroll-1", expected_checkpoint_id=head.checkpoint_id)
    second = service.generate(owner.id, campaign.id, branch_id, "Nhìn ra cửa.", idempotency_key="reroll-2", expected_checkpoint_id=head.checkpoint_id)
    assert (first["status"], second["status"]) == ("candidate", "candidate")
    assert get_campaign_projection(db, owner.id, campaign.id, branch_id)["transcript"] == []

    service.commit_candidate(owner.id, second["id"])
    projection = get_campaign_projection(db, owner.id, campaign.id, branch_id)
    assert [row["narrative_text"] for row in projection["transcript"]] == ["Bản nháp thứ hai."]
    assert service.get_job(owner.id, first["id"])["status"] == "candidate"
    db.close()


def test_branch_http_is_authenticated_owner_scoped_and_lists_forks(tmp_path):
    from playroom.app import create_app

    path = tmp_path / "branches-http.sqlite3"
    db = connect(path)
    migrate(db)
    owner = create_owner(db, "branches-http@example.test", "synthetic strong password")
    stranger = create_owner(db, "stranger@example.test", "synthetic strong password")
    db.close()
    app = create_app(
        database_url=f"sqlite:///{path}",
        allowed_hosts={"testserver"},
        secure_cookies=False,
        credential_root=tmp_path / "secrets",
    )
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    anonymous = {"source_branch_id": "unused", "checkpoint_id": "unused", "expected_state_version": 1}
    campaign_placeholder = str(uuid4())
    assert client.post(f"/api/campaigns/{campaign_placeholder}/branches", json=anonymous, headers=headers).status_code == 401
    assert client.get(f"/api/campaigns/{campaign_placeholder}/branches").status_code == 401
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic strong password"}, headers=headers).status_code == 200
    created = client.post(
        "/api/campaigns",
        json={"title": "Truyện", "world": {"name": "Thị trấn"}, "persona": {"name": "Lan"}},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    campaign_id, branch_id = created.json()["id"], created.json()["branch_id"]
    details = client.get(f"/api/campaigns/{campaign_id}").json()
    payload = {
        "source_branch_id": branch_id,
        "checkpoint_id": details["checkpoint_id"],
        "expected_state_version": details["state_version"],
    }

    forked = client.post(f"/api/campaigns/{campaign_id}/branches", json=payload, headers=headers)
    assert forked.status_code == 201, forked.text
    body = forked.json()
    assert body["parent_branch_id"] == branch_id
    assert body["checkpoint_id"] and body["inherited_turns"] == 0
    listed = client.get(f"/api/campaigns/{campaign_id}/branches", headers=headers).json()["branches"]
    assert {item["id"] for item in listed} == {branch_id, body["id"]}
    assert [item["is_root"] for item in listed if item["id"] == branch_id] == [True]

    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.post("/api/auth/login", json={"email": stranger.email, "password": "synthetic strong password"}, headers=headers).status_code == 200
    assert client.get(f"/api/campaigns/{campaign_id}/branches").status_code == 404
    assert client.post(f"/api/campaigns/{campaign_id}/branches", json=payload, headers=headers).status_code == 404
    assert client.get(f"/api/campaigns/{campaign_id}/branches").status_code == 404
