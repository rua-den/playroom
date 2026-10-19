"""Privacy-safe chapter-156 scale import test. No private story material is stored."""
from __future__ import annotations

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5, uuid4

from fastapi.testclient import TestClient

from test_legacy_import import synthetic_bundle


def _id(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, "playroom-synthetic-legacy-scale:" + label))


def _scale_bundle():
    source = deepcopy(synthetic_bundle())
    player = source["campaign_create_payload"]["persona"]["id"]
    original = source["campaign_create_payload"]["characters"][0]
    npcs = [{**original, "id": _id(f"npc-{i}"), "name": f"Invented NPC {i}", "key": f"npc-{i}"} for i in range(35)]
    source["campaign_create_payload"]["characters"] = npcs
    source["characters"] = [
        {**source["characters"][0], "id": player},
        *[{**source["characters"][1], "id": n["id"], "key": n["key"], "name": n["name"]} for n in npcs],
    ]
    source["timeline_events"] = [
        {**source["timeline_events"][0], "id": _id(f"event-{i}"), "key": f"event-{i}",
         "order": i + 1, "title": f"Fictional event {i}", "summary": f"Synthetic summary {i}",
         "participant_ids": [player, npcs[i % 35]["id"]]}
        for i in range(31)
    ]
    source["canon_facts"] = [
        {**source["canon_facts"][0], "id": _id(f"fact-{i}"), "key": f"fact-{i}",
         "text": f"Synthetic canon detail {i}.", "related_event_keys": [f"event-{i % 31}"],
         "known_by_entity_ids": [npcs[i % 35]["id"]]}
        for i in range(26)
    ]
    source["relationship_states"] = [
        {**source["relationship_states"][0], "from_id": player,
         "to_id": npcs[i]["id"], "state": f"synthetic relationship {i}"}
        for i in range(11)
    ]
    source["player_source_excerpts_ch137_156"] = [
        {**source["player_source_excerpts_ch137_156"][0],
         "source_id": f"fake-excerpt-{i}", "text": f"Synthetic player excerpt {i}."}
        for i in range(16)
    ]
    source["gaps_and_review_queue"] = [
        {"issue": f"Fictional missing history {i}", "policy": "do not invent"}
        for i in range(13)
    ]
    source["data_integrity"].update(
        last_completed_chapter=156, next_chapter=157, next_chapter_has_been_written=False
    )
    source["resume_checkpoint"].update(
        chapter_last_completed=156, next_chapter_number=157, next_chapter_written=False,
    )
    source["resume_checkpoint"]["focus_scene"]["present_character_ids"] = [player]
    source["resume_checkpoint"]["focus_scene"]["location"] = "fictional private room"
    return source


def test_chapter_156_scale_import_http_review_restart_idempotency(tmp_path):
    """Exercise production HTTP, migrations and checkpoint with private-data-sized fixture."""
    from playroom.app import create_app
    from playroom.auth import create_owner
    from playroom.chatgpt_import import approve_import_review
    from playroom.db import connect, migrate
    from playroom.legacy_import import preview_legacy_bundle
    from playroom.timeline import get_branch_head

    source = _scale_bundle()
    report = preview_legacy_bundle(source)
    assert report["counts"] == {
        "characters": 36, "canon_facts": 26, "relationships": 11,
        "timeline_events": 31, "player_excerpts": 16,
    }
    assert report["checkpoint"]["next_chapter"] == 157
    path = tmp_path / "playroom.sqlite3"
    conn = connect(path)
    migrate(conn)
    owner = create_owner(conn, "fixture-owner@example.test", "test password long enough")
    conn.close()
    headers = {"origin": "http://testserver"}
    app = create_app(database_url=str(path), allowed_hosts={"testserver"},
                     secure_cookies=False, credential_root=str(tmp_path / "keys"))
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={
            "email": owner.email, "password": "test password long enough"
        }, headers=headers).status_code == 200
        preview = client.post("/api/transfers/legacy/preview", json={"bundle": source}, headers=headers)
        assert preview.status_code == 200, preview.text
        key = str(uuid4())
        imported = client.post("/api/transfers/legacy/import", json={
            "bundle": source, "import_key": key
        }, headers=headers)
        assert imported.status_code == 201, imported.text
        saved = imported.json()
        assert saved["turn_count"] == 0
        assert saved["review_required"] is True
        duplicate = client.post("/api/transfers/legacy/import", json={
            "bundle": source, "import_key": key
        }, headers=headers)
        assert duplicate.status_code == 201
        assert duplicate.json()["campaign_id"] == saved["campaign_id"]
        projection = client.get(f"/api/campaigns/{saved['campaign_id']}/projection",
                                params={"branch_id": saved["branch_id"]})
        assert projection.status_code == 200
        assert projection.json()["import_review"]["required"]
        assert projection.json()["transcript"] == []

    # Close/reopen all app resources, ensuring disk storage survives restart.
    app2 = create_app(database_url=str(path), allowed_hosts={"testserver"},
                      secure_cookies=False, credential_root=str(tmp_path / "keys"))
    with TestClient(app2) as client:
        assert client.post("/api/auth/login", json={
            "email": owner.email, "password": "test password long enough"
        }, headers=headers).status_code == 200
        projection = client.get(f"/api/campaigns/{saved['campaign_id']}/projection",
                                params={"branch_id": saved["branch_id"]})
        assert projection.status_code == 200
        assert projection.json()["import_review"]["required"]
        assert projection.json()["transcript"] == []

    db = connect(path)
    migrate(db)
    assert db.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM legacy_import_sources").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM memory_versions WHERE campaign_id=?",
                      (saved["campaign_id"],)).fetchone()[0] >= 68
    head = get_branch_head(db, saved["campaign_id"], saved["branch_id"], owner.id)
    approved = approve_import_review(
        db, owner.id, saved["campaign_id"], saved["branch_id"], head.checkpoint_id,
        {"persona": True, "npc_voice_presence": True,
         "canon_known_by_narrator_only": True, "missing_history": True,
         "provider_data": True},
    )
    assert approved["approved"]
    db.close()
    reopened = connect(path)
    migrate(reopened)
    assert reopened.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 1
    assert reopened.execute("SELECT COUNT(*) FROM legacy_import_sources").fetchone()[0] == 1
    # Review approval must survive another process/restart and promote all
    # imported memories without creating fictional transcript turns.
    from playroom.chatgpt_import import assert_import_review_approved, import_review
    from playroom.memory import list_memory_library, list_memory_proposals

    approved_head = get_branch_head(reopened, saved["campaign_id"], saved["branch_id"], owner.id)
    assert_import_review_approved(reopened, owner.id, saved["campaign_id"], approved_head.checkpoint_id)
    assert import_review(reopened, owner.id, saved["campaign_id"])["required"] is False
    assert len(list_memory_library(
        reopened, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id
    )) == 68
    assert list_memory_proposals(
        reopened, saved["campaign_id"], saved["branch_id"], None, owner_id=owner.id
    ) == []
    assert reopened.execute("SELECT COUNT(*) FROM turns WHERE campaign_id=?",
                            (saved["campaign_id"],)).fetchone()[0] == 0
    reopened.close()

    app3 = create_app(database_url=str(path), allowed_hosts={"testserver"},
                      secure_cookies=False, credential_root=str(tmp_path / "keys"))
    with TestClient(app3) as client:
        assert client.post("/api/auth/login", json={
            "email": owner.email, "password": "test password long enough"
        }, headers=headers).status_code == 200
        projection = client.get(f"/api/campaigns/{saved['campaign_id']}/projection",
                                params={"branch_id": saved["branch_id"]})
        assert projection.status_code == 200, projection.text
        assert projection.json()["import_review"]["required"] is False
        assert projection.json()["transcript"] == []
        duplicate = client.post("/api/transfers/legacy/import", json={
            "bundle": source, "import_key": str(uuid4())
        }, headers=headers)
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["campaign_id"] == saved["campaign_id"]
