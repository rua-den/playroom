"""Durable bounded ChatGPT import resume regressions.

All fixture text is synthetic. These tests intentionally exercise restart and
repeated-request recovery without any provider call.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.chatgpt_import import IMPORT_CHUNK_TURNS, import_conversation, import_review
from playroom.db import connect, migrate
from playroom.projections import get_campaign_projection


PAIR_COUNT = 125


def _conversation(pair_count: int = PAIR_COUNT) -> dict:
    mapping: dict[str, dict] = {"root": {"id": "root", "parent": None, "message": None}}
    parent = "root"
    for index in range(pair_count):
        user_id = f"user-{index:03d}"
        assistant_id = f"assistant-{index:03d}"
        mapping[user_id] = {
            "id": user_id,
            "parent": parent,
            "message": {
                "id": user_id,
                "author": {"role": "user"},
                "recipient": "all",
                "content": {"content_type": "text", "parts": [f"Lan action {index:03d}"]},
            },
        }
        mapping[assistant_id] = {
            "id": assistant_id,
            "parent": user_id,
            "message": {
                "id": assistant_id,
                "author": {"role": "assistant"},
                "recipient": "all",
                "content": {"content_type": "text", "parts": [f"Vy response {index:03d}"]},
            },
        }
        parent = assistant_id
    return {
        "id": "resume-thread",
        "title": "Synthetic resumable import",
        "mapping": mapping,
        "current_node": parent,
    }


def _config() -> dict:
    return {
        "title": "Synthetic resumable import",
        "world": {"name": "Synthetic"},
        "persona": {"name": "Lan"},
        "characters": [],
    }


def test_long_import_is_bounded_and_resumes_after_sqlite_restart(tmp_path):
    path = tmp_path / "resume.sqlite3"
    db = connect(path)
    migrate(db)
    owner = create_owner(db, "resume@example.test", "synthetic strong password")
    source = _conversation()
    key = str(uuid4())

    first = import_conversation(db, owner.id, source, _config(), key, chunk_turns=IMPORT_CHUNK_TURNS)
    assert first["turn_count"] == PAIR_COUNT
    assert first["complete"] is False
    assert 0 < first["imported_turns"] < PAIR_COUNT
    campaign_id = first["campaign_id"]
    branch_id = first["branch_id"]

    partial = get_campaign_projection(db, owner.id, campaign_id, branch_id)["transcript"]
    assert len(partial) == first["imported_turns"]
    metadata = import_review(db, owner.id, campaign_id)
    assert metadata["required"] is True
    assert metadata["approved"] is False
    assert metadata["import_status"] == "importing"
    assert metadata["imported_turns"] == first["imported_turns"]
    assert db.execute(
        "SELECT COUNT(*) FROM import_review_checkpoints WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0
    db.close()

    db = connect(path)
    migrate(db)
    previous = first["imported_turns"]
    result = first
    calls = 1
    while not result["complete"]:
        result = import_conversation(db, owner.id, source, _config(), key, chunk_turns=IMPORT_CHUNK_TURNS)
        calls += 1
        assert result["campaign_id"] == campaign_id
        assert result["branch_id"] == branch_id
        assert result["imported_turns"] > previous
        previous = result["imported_turns"]
        assert calls < 20

    assert calls >= 2
    assert result["imported_turns"] == PAIR_COUNT
    transcript = get_campaign_projection(db, owner.id, campaign_id, branch_id)["transcript"]
    assert len(transcript) == PAIR_COUNT
    assert transcript[0]["action_text"] == "Lan action 000"
    assert transcript[-1]["narrative_text"] == "Vy response 124"

    row = db.execute(
        "SELECT import_status, imported_turns, paired_turns FROM chatgpt_import_sources WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()
    assert tuple(row) == ("complete", PAIR_COUNT, PAIR_COUNT)
    assert db.execute(
        "SELECT COUNT(*) FROM import_review_checkpoints WHERE campaign_id=?",
        (campaign_id,),
    ).fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM campaigns WHERE owner_id=?", (owner.id,)).fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0
    db.close()


def test_same_payload_with_new_import_key_resumes_instead_of_creating_duplicate(tmp_path):
    path = tmp_path / "resume-new-key.sqlite3"
    db = connect(path)
    migrate(db)
    owner = create_owner(db, "resume-new-key@example.test", "synthetic strong password")
    source = _conversation()
    first = import_conversation(db, owner.id, source, _config(), str(uuid4()), chunk_turns=IMPORT_CHUNK_TURNS)
    assert first["complete"] is False
    campaign_id = first["campaign_id"]
    imported = first["imported_turns"]
    db.close()

    reopened = connect(path)
    migrate(reopened)
    resumed = import_conversation(reopened, owner.id, source, _config(), str(uuid4()), chunk_turns=IMPORT_CHUNK_TURNS)
    assert resumed["campaign_id"] == campaign_id
    assert resumed["imported_turns"] > imported
    assert reopened.execute("SELECT COUNT(*) FROM campaigns WHERE owner_id=?", (owner.id,)).fetchone()[0] == 1
    assert reopened.execute("SELECT COUNT(*) FROM chatgpt_import_sources WHERE owner_id=?", (owner.id,)).fetchone()[0] == 1
    reopened.close()



def test_http_import_is_bounded_and_repeated_post_finishes_same_campaign(tmp_path):
    from playroom.app import create_app

    path = tmp_path / "resume-http.sqlite3"
    db = connect(path)
    migrate(db)
    owner = create_owner(db, "resume-http@example.test", "synthetic strong password")
    db.close()

    app = create_app(
        database_url=f"sqlite:///{path}",
        allowed_hosts={"testserver"},
        secure_cookies=False,
        credential_root=tmp_path / "secrets",
    )
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post(
        "/api/auth/login",
        json={"email": owner.email, "password": "synthetic strong password"},
        headers=headers,
    ).status_code == 200

    payload = {
        "conversation": _conversation(),
        "config": _config(),
        "import_key": str(uuid4()),
    }
    first = client.post("/api/transfers/chatgpt/import", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["complete"] is False
    assert first_body["imported_turns"] == IMPORT_CHUNK_TURNS
    assert first_body["turn_count"] == PAIR_COUNT
    assert first_body["review_required"] is True
    campaign_id = first_body["campaign_id"]

    second = client.post("/api/transfers/chatgpt/import", json=payload, headers=headers)
    assert second.status_code == 201, second.text
    second_body = second.json()
    assert second_body["campaign_id"] == campaign_id
    assert second_body["complete"] is True
    assert second_body["imported_turns"] == PAIR_COUNT

    replay = client.post("/api/transfers/chatgpt/import", json=payload, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["already_imported"] is True
    assert replay.json()["campaign_id"] == campaign_id

    db = connect(path)
    try:
        assert db.execute("SELECT COUNT(*) FROM campaigns WHERE owner_id=?", (owner.id,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM chatgpt_import_sources WHERE owner_id=?", (owner.id,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM import_review_checkpoints WHERE campaign_id=?", (campaign_id,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0
    finally:
        db.close()
