from __future__ import annotations

from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner, create_session, session_valid, revoke_session
from playroom.db import connect, migrate
from playroom.campaigns import create_campaign
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def _app(tmp_path, **kwargs):
    path = tmp_path / "auth.sqlite3"
    connection = connect(path)
    migrate(connection)
    create_owner(connection, "owner@example.test", "secret owner password")
    connection.close()
    return create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False, **kwargs)


def test_private_campaign_routes_reject_missing_and_revoked_sessions(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/api/campaigns").status_code == 401

    created = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "secret owner password"}, headers={"origin": "https://testserver"})
    assert created.status_code == 200
    assert client.get("/api/campaigns").status_code == 200
    assert client.post("/api/auth/logout", headers={"origin": "https://testserver"}).status_code == 204
    assert client.get("/api/campaigns").status_code == 401


def test_wrong_password_has_no_session_and_rate_limit_applies(tmp_path):
    app = _app(tmp_path, login_failure_limit=2)
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong"}, headers=headers).status_code == 401
    assert "playroom_session" not in client.cookies
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong"}, headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "secret owner password"}, headers=headers).status_code == 429


def test_origin_and_host_checks_reject_cross_origin_mutations(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app, base_url="https://testserver")
    rejected = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "secret"}, headers={"origin": "https://evil.example"})
    assert rejected.status_code == 403
    wrong_host = TestClient(app, base_url="https://evil.example")
    assert wrong_host.get("/health").status_code == 400


def test_owner_session_is_hashed_revocable_and_campaigns_stay_private(tmp_path):
    database_path = tmp_path / "private.sqlite3"
    connection = connect(database_path)
    migrate(connection)
    owner = create_owner(connection, "owner@example.test", "secret owner password")
    other = create_owner(connection, "other@example.test", "another owner password")
    campaign = create_campaign(connection, owner.id, "Private", {"name": "World"}, [], {"name": "Persona"})
    raw_token = create_session(connection, other.id)
    session_row = connection.execute("SELECT token_hash FROM sessions").fetchone()
    assert raw_token not in session_row["token_hash"]
    assert session_valid(connection, raw_token).id == other.id
    connection.close()

    app = create_app(database_url=f"sqlite:///{database_path}", allowed_hosts={"testserver"}, secure_cookies=False)
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set("playroom_session", raw_token)
    assert client.get(f"/api/campaigns/{campaign.id}").status_code == 404
    connection = connect(database_path)
    revoke_session(connection, raw_token)
    assert session_valid(connection, raw_token) is None
    connection.close()


def test_competing_profile_writes_serialize_and_leave_one_checkpoint(tmp_path):
    database_path = tmp_path / "concurrent.sqlite3"
    connection = connect(database_path)
    migrate(connection)
    owner = create_owner(connection, "owner@example.test", "secret owner password")
    campaign = create_campaign(connection, owner.id, "Concurrent", {"name": "World"}, [], {"name": "Persona"})
    branch_id = campaign.initial_branch_id
    token = create_session(connection, owner.id)
    connection.close()

    app = create_app(database_url=f"sqlite:///{database_path}", allowed_hosts={"testserver"}, secure_cookies=False)
    clients = [TestClient(app, base_url="https://testserver") for _ in range(2)]
    for client in clients:
        client.cookies.set("playroom_session", token)
    barrier = Barrier(3)
    payloads = [
        {"branch_id": branch_id, "expected_state_version": 1, "data": {"name": "One"}},
        {"branch_id": branch_id, "expected_state_version": 1, "data": {"name": "Two"}},
    ]

    def update(client, payload):
        barrier.wait()
        return client.patch(f"/api/campaigns/{campaign.id}/profiles/world", json=payload, headers={"origin": "https://testserver"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, client, payload) for client, payload in zip(clients, payloads)]
        barrier.wait()
        responses = [future.result() for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409], [response.text for response in responses]

    connection = connect(database_path)
    head = connection.execute("SELECT state_version FROM branches WHERE id = ?", (branch_id,)).fetchone()
    checkpoint_count = connection.execute("SELECT COUNT(*) FROM state_checkpoints WHERE branch_id = ?", (branch_id,)).fetchone()[0]
    assert head["state_version"] == 2
    assert checkpoint_count == 2
    connection.close()


def test_authenticated_campaign_and_memory_lifecycle_api(tmp_path):
    client = TestClient(_app(tmp_path), base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "secret owner password"}, headers=headers).status_code == 200
    created = client.post("/api/campaigns", json={"title": "Private", "world": {"name": "World"}, "persona": {"name": "Player"}}, headers=headers)
    assert created.status_code == 201
    campaign = created.json(); branch = campaign["branch_id"]
    invalid_character = client.post(f"/api/campaigns/{campaign['id']}/characters", json={"branch_id": branch, "expected_state_version": 1, "character": {"id": str(uuid4()), "name": "Bad", "aliases": None}}, headers=headers)
    assert invalid_character.status_code == 422
    renamed = client.patch(f"/api/campaigns/{campaign['id']}", json={"branch_id": branch, "expected_state_version": 1, "title": "Renamed"}, headers=headers)
    assert renamed.status_code == 200
    memory = client.post(f"/api/campaigns/{campaign['id']}/memory", json={"branch_id": branch, "expected_state_version": 2, "kind": "event", "text": "Clue", "pinned": True}, headers=headers)
    assert memory.status_code == 201
    memory = memory.json()
    edited = client.patch(f"/api/campaigns/{campaign['id']}/memory/{memory['memory_id']}", json={"branch_id": branch, "expected_state_version": 3, "pinned": False, "entity_ids": [], "known_by": [], "knowledge_scope": "public"}, headers=headers)
    assert edited.status_code == 200 and edited.json()["pinned"] is False and edited.json()["entity_ids"] == []
    assert client.get(f"/api/campaigns/{campaign['id']}/memory?branch_id={branch}").json()[0]["pinned"] is False
    assert len(client.get(f"/api/campaigns/{campaign['id']}/memory/{memory['memory_id']}/history?branch_id={branch}").json()) == 2
    policy = client.put(f"/api/campaigns/{campaign['id']}/retrieval-policy", json={"branch_id": branch, "expected_state_version": 4, "policy": "disabled"}, headers=headers)
    assert policy.status_code == 200
    assert len(client.get(f"/api/campaigns/{campaign['id']}/memory?branch_id={branch}").json()) == 1
    archived = client.post(f"/api/campaigns/{campaign['id']}/archive", json={"branch_id": branch, "expected_state_version": 5}, headers=headers)
    assert archived.status_code == 200
