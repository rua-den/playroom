"""ChatGPT JSON source-import contract. All fixture text is invented."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.projections import get_campaign_projection


def fixture_conversation():
    def message(role, text, *, recipient="all", hidden=False):
        return {"id": str(uuid4()), "author": {"role": role}, "recipient": recipient,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {"is_visually_hidden_from_conversation": hidden}}
    return {
        "id": "synthetic-thread", "title": "playrooom",
        "mapping": {
            "root": {"id": "root", "parent": None, "message": None},
            "user1": {"id": "user1", "parent": "root", "message": message("user", "*Lan mở hộp gỗ.*")},
            "alt": {"id": "alt", "parent": "user1", "message": message("assistant", "ALT SHOULD NOT IMPORT")},
            "reply1": {"id": "reply1", "parent": "user1", "message": message("assistant", "Vy quan sát chiếc hộp.")},
            "tool": {"id": "tool", "parent": "reply1", "message": message("assistant", "internal", recipient="python")},
            "user2": {"id": "user2", "parent": "tool", "message": message("user", '"Vy, còn tờ giấy xanh?"')},
            "reply2": {"id": "reply2", "parent": "user2", "message": message("assistant", "Vy khẽ lắc đầu. 💙")},
        },
        "current_node": "reply2",
    }


def test_selected_current_path_not_alternate_or_internal_messages():
    from playroom.chatgpt_import import preview_conversation
    parsed = preview_conversation(fixture_conversation())
    assert parsed["conversation_id"] == "synthetic-thread"
    assert parsed["title"] == "playrooom"
    assert [(t["action_text"], t["narrative_text"]) for t in parsed["turns"]] == [
        ("*Lan mở hộp gỗ.*", "Vy quan sát chiếc hộp."),
        ('"Vy, còn tờ giấy xanh?"', "Vy khẽ lắc đầu. 💙"),
    ]
    assert all("ALT" not in t["narrative_text"] for t in parsed["turns"])


def test_cycle_and_missing_node_are_rejected_not_silently_reordered():
    from playroom.chatgpt_import import preview_conversation
    broken = fixture_conversation()
    broken["mapping"]["root"]["parent"] = "reply2"
    with pytest.raises(ValidationError, match="cycle|loop|circular"):
        preview_conversation(broken)
    broken = fixture_conversation()
    broken["mapping"]["user2"]["parent"] = "missing"
    with pytest.raises(ValidationError, match="missing|parent|node"):
        preview_conversation(broken)


def test_import_preserves_selected_story_and_is_idempotent_and_owner_scoped(tmp_path):
    from playroom.chatgpt_import import import_conversation
    path = tmp_path / "import.sqlite3"
    db = connect(path)
    migrate(db)
    owner = create_owner(db, "fixture@example.test", "synthetic strong password")
    other = create_owner(db, "other@example.test", "synthetic strong password")
    source = fixture_conversation()
    config = {"title": "Sân bóng nhập", "world": {"name": "Trường synthetic"},
              "persona": {"name": "Lan"}, "characters": [{"id": str(uuid4()), "name": "Vy", "aliases": []}]}
    key = str(uuid4())
    first = import_conversation(db, owner.id, source, config, key)
    again = import_conversation(db, owner.id, source, config, key)
    assert first["campaign_id"] == again["campaign_id"]
    assert db.execute("SELECT COUNT(*) FROM campaigns WHERE owner_id=?", (owner.id,)).fetchone()[0] == 1
    transcript = get_campaign_projection(db, owner.id, first["campaign_id"], first["branch_id"])["transcript"]
    assert [(t["action_text"], t["narrative_text"]) for t in transcript] == [
        ("*Lan mở hộp gỗ.*", "Vy quan sát chiếc hộp."),
        ('"Vy, còn tờ giấy xanh?"', "Vy khẽ lắc đầu. 💙"),
    ]
    record = db.execute("SELECT selected_source_json FROM chatgpt_import_sources WHERE campaign_id=?", (first["campaign_id"],)).fetchone()
    assert record is not None and "ALT SHOULD NOT IMPORT" in record[0]
    # User isolation: second owner cannot acquire the first owner's import ID/key.
    second = import_conversation(db, other.id, source, config, key)
    assert second["campaign_id"] != first["campaign_id"]
    with pytest.raises(ValidationError, match="key|payload|different"):
        import_conversation(db, owner.id, {**source, "title": "changed"}, config, key)
    db.close()


def test_http_preview_and_import_require_auth_and_reject_empty_story(tmp_path):
    from playroom.app import create_app
    from playroom.chatgpt_import import preview_conversation
    path = tmp_path / "routes.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "preview@example.test", "synthetic strong password")
    db.close()
    app = create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False,
                     credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    src = fixture_conversation()
    assert client.post("/api/transfers/chatgpt/preview", json={"conversation": src},
                       headers={"origin": "https://testserver"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic strong password"},
                       headers={"origin": "https://testserver"}).status_code == 200
    preview = client.post("/api/transfers/chatgpt/preview", json={"conversation": src},
                          headers={"origin": "https://testserver"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["turn_count"] == 2
    incomplete = fixture_conversation()
    incomplete["current_node"] = "user1"
    with pytest.raises(ValidationError, match="complete|pair|no usable"):
        preview_conversation(incomplete)


def test_import_requires_separate_durable_review_before_generation_even_after_restart(tmp_path):
    from playroom.app import create_app
    path = tmp_path / "review-gate.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "gate@example.test", "synthetic strong password")
    db.close()
    app = create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False,
                     credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic strong password"}, headers=headers).status_code == 200
    imported = client.post("/api/transfers/chatgpt/import", json={
        "conversation": fixture_conversation(),
        "config": {"title": "Imported gate", "world": {"name": "Synthetic"}, "persona": {"name": "Lan"}, "characters": []},
        "import_key": str(uuid4()),
    }, headers=headers)
    assert imported.status_code == 201, imported.text
    campaign_id = imported.json()["campaign_id"]
    branch_id = imported.json()["branch_id"]
    projection = client.get(f"/api/campaigns/{campaign_id}/projection?branch_id={branch_id}", headers=headers)
    assert projection.status_code == 200
    assert projection.json()["import_review"]["required"] is True
    payload = {"branch_id": branch_id, "action": "*Lan nhìn quanh.*", "idempotency_key": str(uuid4()), "checkpoint_id": projection.json()["branch"]["checkpoint_id"]}
    blocked = client.post(f"/api/campaigns/{campaign_id}/generate", json=payload, headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert "review" in blocked.text.lower()
    for table in ("generation_jobs", "provider_attempts", "generation_branch_guards", "paid_trial_reservations"):
        assert db_count(path, table) == 0

    # A process restart must retain the fail-closed checkpoint.
    app = create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False,
                     credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic strong password"}, headers=headers).status_code == 200
    blocked_again = client.post(f"/api/campaigns/{campaign_id}/generate", json=payload, headers=headers)
    assert blocked_again.status_code == 409


def db_count(path, table):
    db = connect(path)
    try:
        return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        db.close()


def test_review_http_is_authenticated_owner_scoped_strict_and_stale_safe(tmp_path):
    from playroom.app import create_app
    path = tmp_path / "review-http.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "http-review@example.test", "synthetic strong password")
    other = create_owner(db, "http-other@example.test", "synthetic strong password")
    db.close()
    app = create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic strong password"}, headers=headers).status_code == 200
    imported = client.post("/api/transfers/chatgpt/import", json={"conversation": fixture_conversation(), "config": {"title": "HTTP gate", "world": {"name": "Synthetic"}, "persona": {"name": "Lan"}, "characters": []}, "import_key": str(uuid4())}, headers=headers).json()
    base = {"branch_id": imported["branch_id"], "checkpoint_id": imported["checkpoint_id"], "review": {"persona": True, "npc_voice_presence": True, "canon_known_by_narrator_only": True, "missing_history": True}}
    assert client.post(f"/api/transfers/chatgpt/{imported['campaign_id']}/review", json={**base, "review": {**base["review"], "missing_history": False}}, headers=headers).status_code == 422
    assert client.post(f"/api/transfers/chatgpt/{imported['campaign_id']}/review", json={**base, "checkpoint_id": str(uuid4())}, headers=headers).status_code == 409
    malformed = client.post(f"/api/transfers/chatgpt/{imported['campaign_id']}/review", json=[], headers=headers)
    assert malformed.status_code == 422
    for invalid_review in (
        {**base["review"], "persona": 1},
        {**base["review"], "persona": "true"},
        {**base["review"], "unexpected": True},
    ):
        response = client.post(
            f"/api/transfers/chatgpt/{imported['campaign_id']}/review",
            json={**base, "review": invalid_review},
            headers=headers,
        )
        assert response.status_code == 422
    extra_outer = client.post(
        f"/api/transfers/chatgpt/{imported['campaign_id']}/review",
        json={**base, "unexpected": True},
        headers=headers,
    )
    assert extra_outer.status_code == 422
    assert client.post(f"/api/transfers/chatgpt/{imported['campaign_id']}/review", json=base, headers=headers).status_code == 200
    other_client = TestClient(app, base_url="https://testserver")
    assert other_client.post("/api/auth/login", json={"email": other.email, "password": "synthetic strong password"}, headers=headers).status_code == 200
    assert other_client.post(f"/api/transfers/chatgpt/{imported['campaign_id']}/review", json=base, headers=headers).status_code == 404


def test_migration_backfills_missing_import_review_and_stays_locked(tmp_path):
    from playroom.chatgpt_import import assert_import_review_approved
    path = tmp_path / "review-backfill.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "backfill@example.test", "synthetic strong password")
    imported = __import__("playroom.chatgpt_import", fromlist=["import_conversation"]).import_conversation(db, owner.id, fixture_conversation(), {"title": "Backfill", "world": {"name": "Synthetic"}, "persona": {"name": "Lan"}, "characters": []}, str(uuid4()))
    db.execute("DELETE FROM import_review_checkpoints WHERE campaign_id=?", (imported["campaign_id"],))
    migrate(db)
    checkpoint = db.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (imported["branch_id"],)).fetchone()[0]
    with pytest.raises(Exception, match="review"):
        assert_import_review_approved(db, owner.id, imported["campaign_id"], checkpoint)


def test_preexisting_queued_import_job_fails_closed_during_recovery(tmp_path):
    from playroom.campaigns import create_campaign
    from playroom.generation import GenerationService
    from playroom.provider import FakeProvider
    from playroom.timeline import get_branch_head
    path = tmp_path / "queued-import.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "queued-import@example.test", "synthetic strong password")
    campaign = create_campaign(db, owner.id, "Queued imported", {"name": "Synthetic"}, [], {"name": "Lan"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id)
    service = GenerationService(db, FakeProvider(["must not be called"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "*Lan waits.*", idempotency_key=str(uuid4()), expected_checkpoint_id=head.checkpoint_id, execute=False)
    db.execute("INSERT INTO chatgpt_import_sources(id,owner_id,campaign_id,branch_id,import_key,payload_hash,source_conversation_id,selected_source_json,paired_turns,warnings_json,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner.id, campaign.id, campaign.initial_branch_id, str(uuid4()), str(uuid4()), "legacy", "{}", 1, "[]", "2026-01-01T00:00:00Z"))
    db.execute("DELETE FROM import_review_checkpoints WHERE campaign_id=?", (campaign.id,))
    db.close()
    reopened = connect(path); migrate(reopened)
    recovered_service = GenerationService(reopened, service.provider)
    recovered_service.recover_after_restart()
    recovered = recovered_service.run_queued()[0]
    assert recovered["status"] == "failed"
    assert not service.provider.calls
    assert reopened.execute("SELECT COUNT(*) FROM generation_branch_guards WHERE branch_id=?", (campaign.initial_branch_id,)).fetchone()[0] == 0
    reopened.close()


def test_invocation_gate_rechecks_import_review_inside_dispatch_transaction(tmp_path):
    from playroom.campaigns import create_campaign
    from playroom.generation import GenerationService
    from playroom.provider import FakeProvider
    from playroom.timeline import get_branch_head
    path = tmp_path / "dispatch-import.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "dispatch-import@example.test", "synthetic strong password")
    campaign = create_campaign(db, owner.id, "Dispatch imported", {"name": "Synthetic"}, [], {"name": "Lan"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id)
    db.execute("INSERT INTO chatgpt_import_sources(id,owner_id,campaign_id,branch_id,import_key,payload_hash,source_conversation_id,selected_source_json,paired_turns,warnings_json,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), owner.id, campaign.id, campaign.initial_branch_id, str(uuid4()), str(uuid4()), "legacy", "{}", 1, "[]", "2026-01-01T00:00:00Z"))
    db.execute("INSERT INTO import_review_checkpoints(campaign_id,owner_id,source_checkpoint_id,approved_checkpoint_id,review_json,approved_at,created_at) VALUES(?,?,?,?,?,?,?)", (campaign.id, owner.id, head.checkpoint_id, head.checkpoint_id, '{"persona":true}', "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
    service = GenerationService(db, FakeProvider(["must not be called"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "*Lan waits.*", idempotency_key=str(uuid4()), expected_checkpoint_id=head.checkpoint_id, execute=False)
    db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (job["id"],))
    key = f"{job['id']}:narration"
    db.execute("UPDATE provider_attempts SET status='claimed',claim_epoch=? WHERE stage_key=?", (service._epoch(), key))
    db.execute("DELETE FROM import_review_checkpoints WHERE campaign_id=?", (campaign.id,))
    assert service._invocation_gate(job["id"], key) is False
    assert db.execute("SELECT status FROM provider_attempts WHERE stage_key=?", (key,)).fetchone()[0] == "claimed"
    assert not service.provider.calls


def test_review_is_owner_scoped_idempotent_and_unlocks_fake_send(tmp_path):
    from playroom.chatgpt_import import approve_import_review, import_conversation, import_review
    from playroom.generation import GenerationService
    from playroom.provider import FakeProvider
    from playroom.timeline import get_branch_head
    path = tmp_path / "review-approval.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "approve@example.test", "synthetic strong password")
    other = create_owner(db, "other-approve@example.test", "synthetic strong password")
    config = {"title": "Approved gate", "world": {"name": "Synthetic"}, "persona": {"name": "Lan"}, "characters": []}
    imported = import_conversation(db, owner.id, fixture_conversation(), config, str(uuid4()))
    head = get_branch_head(db, imported["campaign_id"], imported["branch_id"], owner.id)
    review = {"persona": True, "npc_voice_presence": True, "canon_known_by_narrator_only": True, "missing_history": True}
    with pytest.raises(ValidationError, match="review"):
        approve_import_review(db, owner.id, imported["campaign_id"], imported["branch_id"], head.checkpoint_id, {**review, "missing_history": False})
    with pytest.raises(Exception, match="not found|review"):
        approve_import_review(db, other.id, imported["campaign_id"], imported["branch_id"], head.checkpoint_id, review)
    approved = approve_import_review(db, owner.id, imported["campaign_id"], imported["branch_id"], head.checkpoint_id, review)
    assert approved["required"] is False
    assert approve_import_review(db, owner.id, imported["campaign_id"], imported["branch_id"], head.checkpoint_id, review)["approved"] is True
    service = GenerationService(db, FakeProvider(["Vy khẽ gật đầu.", "Vy mỉm cười."]))
    job = service.generate(owner.id, imported["campaign_id"], imported["branch_id"], "*Lan chờ đợi.*", idempotency_key=str(uuid4()), expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "candidate"
    service.commit_candidate(owner.id, job["id"])
    next_head = get_branch_head(db, imported["campaign_id"], imported["branch_id"], owner.id)
    second = service.generate(owner.id, imported["campaign_id"], imported["branch_id"], "*Lan mỉm cười.*", idempotency_key=str(uuid4()), expected_checkpoint_id=next_head.checkpoint_id)
    assert second["status"] == "candidate"
    assert import_review(db, owner.id, imported["campaign_id"])["approved_checkpoint_id"] == head.checkpoint_id
