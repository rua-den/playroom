"""Synthetic tests for Issue 29 legacy story bundle preview."""
from __future__ import annotations

import pytest
from playroom.domain import ValidationError


def synthetic_bundle():
    player = "11111111-1111-4111-8111-111111111111"
    npc = "22222222-2222-4222-8222-222222222222"
    return {
        "format": "playroom_legacy_story_bundle",
        "schema_version": "1.0.0",
        "title": "Fictional lanterns",
        "is_app_export": False,
        "can_roundtrip_app_export": False,
        "data_integrity": {"last_completed_chapter": 4, "next_chapter": 5, "next_chapter_has_been_written": False},
        "campaign_create_payload": {
            "title": "Lanterns", "world": {"name": "Invented City"},
            "persona": {"id": player, "name": "Lan", "player_controlled": True},
            "characters": [{"id": npc, "key": "vy", "name": "Vy", "aliases": []}],
            "style": {"language": "vi"},
        },
        "characters": [{"id": player, "key": "lan", "name": "Lan"}, {"id": npc, "key": "vy", "name": "Vy"}],
        "canon_facts": [{"id": "33333333-3333-4333-8333-333333333333", "key": "note", "text": "A blue note exists.", "knowledge_scope": "known_by", "known_by_entity_ids": [npc], "related_event_keys": ["market"]}],
        "relationship_states": [{"from_id": player, "to_id": npc, "state": "friends"}],
        "timeline_events": [{"id": "44444444-4444-4444-8444-444444444444", "key": "market", "order": 1, "title": "A note", "summary": "A note arrived.", "participant_ids": [npc, player]}],
        "player_source_excerpts_ch137_156": [{"source_id": "synthetic-04", "actor_role": "player", "source_type": "verbatim_user_message_excerpt", "completeness": "user_excerpt_only", "text": "Lan waits."}],
        "resume_checkpoint": {"chapter_last_completed": 4, "next_chapter_number": 5, "next_chapter_written": False, "focus_scene": {"scene_id": "55555555-5555-4555-8555-555555555555", "location": "market", "present_character_ids": [player, npc]}},
        "gaps_and_review_queue": [{"issue": "chapter not present", "policy": "do not invent"}],
    }


def test_legacy_preview_is_metadata_only_and_not_transcript():
    from playroom.legacy_import import preview_legacy_bundle
    report = preview_legacy_bundle(synthetic_bundle())
    assert report["turn_count"] == 0
    assert report["counts"]["canon_facts"] == 1
    assert report["checkpoint"]["next_chapter"] == 5
    assert report["missing_history"] is True
    assert "Lan waits." not in repr(report)


def test_invalid_references_are_rejected():
    from playroom.legacy_import import preview_legacy_bundle
    source = synthetic_bundle()
    source["timeline_events"][0]["participant_ids"] = ["unknown"]
    with pytest.raises(ValidationError):
        preview_legacy_bundle(source)


@pytest.mark.parametrize("change", [
    "format", "schema_version", "app_export", "duplicate_npc", "bad_scope",
    "bad_known_by", "duplicate_events", "future_written", "bad_player_role",
    "unknown_relationship", "unknown_scene_presence",
])
def test_legacy_preview_rejects_untrusted_shapes(change):
    from playroom.legacy_import import preview_legacy_bundle
    data = synthetic_bundle()
    if change == "format":
        data["format"] = "conversations.json"
    elif change == "schema_version":
        data["schema_version"] = "9.9.9"
    elif change == "app_export":
        data["is_app_export"] = True
    elif change == "duplicate_npc":
        data["campaign_create_payload"]["characters"].append(dict(data["campaign_create_payload"]["characters"][0]))
    elif change == "bad_scope":
        data["canon_facts"][0]["knowledge_scope"] = "everyone"
    elif change == "bad_known_by":
        data["canon_facts"][0]["known_by_entity_ids"] = ["99999999-9999-4999-8999-999999999999"]
    elif change == "duplicate_events":
        data["timeline_events"].append(dict(data["timeline_events"][0]))
    elif change == "future_written":
        data["resume_checkpoint"]["next_chapter_written"] = True
    elif change == "bad_player_role":
        data["player_source_excerpts_ch137_156"][0]["actor_role"] = "assistant"
    elif change == "unknown_relationship":
        data["relationship_states"][0]["to_id"] = "unknown"
    elif change == "unknown_scene_presence":
        data["resume_checkpoint"]["focus_scene"]["present_character_ids"] = ["unknown"]
    with pytest.raises(ValidationError):
        preview_legacy_bundle(data)


def test_legacy_preview_enforces_byte_limit():
    from playroom.legacy_import import preview_legacy_bundle
    data = synthetic_bundle()
    data["extra_untrusted_text"] = "x" * (20 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match="20 MiB"):
        preview_legacy_bundle(data)


def test_legacy_preview_http_requires_owner_and_creates_no_campaign(tmp_path):
    from fastapi.testclient import TestClient
    from playroom.app import create_app
    from playroom.auth import create_owner
    from playroom.db import connect, migrate

    database = tmp_path / "preview.sqlite3"
    connection = connect(database)
    migrate(connection)
    owner = create_owner(connection, "preview-legacy@example.test", "synthetic long password")
    app = create_app(
        database_url=str(database),
        allowed_hosts={"testserver"},
        secure_cookies=False,
        credential_root=str(tmp_path / "credentials"),
    )
    client = TestClient(app)
    headers = {"origin": "http://testserver"}
    assert client.post("/api/transfers/legacy/preview", json={"bundle": synthetic_bundle()}, headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic long password"}, headers=headers).status_code == 200
    response = client.post("/api/transfers/legacy/preview", json={"bundle": synthetic_bundle()}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["turn_count"] == 0
    assert "Lan waits." not in response.text
    assert connection.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 0
    wrong = client.post("/api/transfers/legacy/preview", json={"conversation": synthetic_bundle()}, headers=headers)
    assert wrong.status_code == 422


def test_legacy_staging_is_atomic_durable_nonreplayable_and_review_locked(tmp_path):
    from uuid import uuid4
    from playroom.auth import create_owner
    from playroom.chatgpt_import import import_review, assert_import_review_approved, approve_import_review
    from playroom.db import connect, migrate
    from playroom.domain import StateConflict
    from playroom.legacy_import import import_legacy_bundle
    from playroom.memory import get_effective_scene, list_memory_library, list_memory_proposals
    from playroom.timeline import get_branch_head

    path = tmp_path / "import.sqlite3"
    conn = connect(path); migrate(conn)
    owner = create_owner(conn, "owner-legacy@example.test", "synthetic long password")
    second_owner = create_owner(conn, "second-legacy@example.test", "synthetic long password")
    source = synthetic_bundle()
    key = str(uuid4())
    saved = import_legacy_bundle(conn, owner.id, source, key)
    assert saved["turn_count"] == 0 and saved["review_required"] is True
    assert saved["pending_memories"] == 3
    again = import_legacy_bundle(conn, owner.id, source, key)
    assert again["campaign_id"] == saved["campaign_id"]
    assert conn.execute("SELECT COUNT(*) FROM turns WHERE campaign_id=?", (saved["campaign_id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM legacy_import_sources WHERE campaign_id=?", (saved["campaign_id"],)).fetchone()[0] == 1
    head = get_branch_head(conn, saved["campaign_id"], saved["branch_id"], owner.id)
    assert head.checkpoint_id == saved["checkpoint_id"]
    assert import_review(conn, owner.id, saved["campaign_id"])["required"]
    assert len(list_memory_library(conn, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id)) == 0
    proposals = list_memory_proposals(conn, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id)
    assert len(proposals) == 3 and all(x.status == "pending" for x in proposals)
    scene = get_effective_scene(conn, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id)
    assert scene["scenes"][scene["focus_scene_id"]]["present_ids"] == [source["campaign_create_payload"]["persona"]["id"], source["campaign_create_payload"]["characters"][0]["id"]]
    with pytest.raises(StateConflict, match="review"):
        assert_import_review_approved(conn, owner.id, saved["campaign_id"], head.checkpoint_id)
    with pytest.raises(Exception, match="not found|review"):
        approve_import_review(conn, second_owner.id, saved["campaign_id"], saved["branch_id"], head.checkpoint_id, dict(persona=True, npc_voice_presence=True, canon_known_by_narrator_only=True, missing_history=True, provider_data=True))

    # Reopened database remains locked until a separate user review approval.
    conn.close()
    reopened = connect(path); migrate(reopened)
    with pytest.raises(StateConflict, match="review"):
        assert_import_review_approved(reopened, owner.id, saved["campaign_id"], head.checkpoint_id)
    approved = approve_import_review(reopened, owner.id, saved["campaign_id"], saved["branch_id"], head.checkpoint_id, dict(persona=True, npc_voice_presence=True, canon_known_by_narrator_only=True, missing_history=True, provider_data=True))
    assert approved["approved"]
    new_head = get_branch_head(reopened, saved["campaign_id"], saved["branch_id"], owner.id)
    assert_import_review_approved(reopened, owner.id, saved["campaign_id"], new_head.checkpoint_id)
    assert len(list_memory_proposals(reopened, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id)) == 0
    memories = list_memory_library(reopened, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id)
    assert len(memories) == 3 and all(x.status == "approved" and x.origin == "import" for x in memories)
    assert [m for m in memories if m.knowledge_scope == "known_by"][0].known_by == (source["campaign_create_payload"]["characters"][0]["id"],)
    assert reopened.execute("SELECT COUNT(*) FROM turns WHERE campaign_id=?", (saved["campaign_id"],)).fetchone()[0] == 0


def test_legacy_import_invalid_payload_and_idempotency_do_not_duplicate_campaign(tmp_path):
    from uuid import uuid4
    from playroom.auth import create_owner
    from playroom.db import connect, migrate
    from playroom.legacy_import import import_legacy_bundle

    conn = connect(tmp_path / "atomic.sqlite3"); migrate(conn)
    owner = create_owner(conn, "atomic-legacy@example.test", "synthetic long password")
    source = synthetic_bundle()
    key = str(uuid4())
    invalid = synthetic_bundle()
    invalid["canon_facts"][0]["known_by_entity_ids"] = ["unknown"]
    with pytest.raises(ValidationError):
        import_legacy_bundle(conn, owner.id, invalid, key)
    assert conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 0
    created = import_legacy_bundle(conn, owner.id, source, key)
    assert import_legacy_bundle(conn, owner.id, source, str(uuid4()))["campaign_id"] == created["campaign_id"]
    changed = synthetic_bundle()
    changed["canon_facts"][0]["text"] = "Different invented text"
    with pytest.raises(ValidationError, match="key"):
        import_legacy_bundle(conn, owner.id, changed, key)
    assert conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 1


def test_legacy_http_import_is_owner_only_and_returns_locked_checkpoint(tmp_path):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from playroom.app import create_app
    from playroom.auth import create_owner
    from playroom.db import connect, migrate

    path = tmp_path / "legacy-routes.sqlite3"
    db = connect(path); migrate(db)
    owner = create_owner(db, "routes-legacy@example.test", "synthetic long password")
    app = create_app(database_url=str(path), allowed_hosts={"testserver"}, secure_cookies=False, credential_root=str(tmp_path / "credential-root"))
    client = TestClient(app); headers = {"origin": "http://testserver"}
    payload = {"bundle": synthetic_bundle(), "import_key": str(uuid4())}
    assert client.post("/api/transfers/legacy/import", json=payload, headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "synthetic long password"}, headers=headers).status_code == 200
    first = client.post("/api/transfers/legacy/import", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["review_required"] is True
    again = client.post("/api/transfers/legacy/import", json=payload, headers=headers)
    assert again.status_code == 201 and again.json()["campaign_id"] == first.json()["campaign_id"]
    projection = client.get(f"/api/campaigns/{first.json()['campaign_id']}/projection", params={"branch_id": first.json()["branch_id"]})
    assert projection.status_code == 200, projection.text
    assert projection.json()["import_review"]["required"] is True
    assert projection.json()["transcript"] == []
