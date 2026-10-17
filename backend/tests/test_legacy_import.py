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
