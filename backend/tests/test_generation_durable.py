from __future__ import annotations

import json
import http.client
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.context import build_candidate_pool
from playroom.memory import append_memory_version
from playroom.db import connect, migrate
from playroom.domain import StateConflict
from playroom.generation import DEFAULT_PROFILE, GenerationRuntime, GenerationService
from playroom.attempt_runtime import PhysicalAttemptRegistry
from playroom.campaigns import update_profile
from playroom.provider import FakeProvider, ProviderAdapter, ProviderFailure, ProviderResult
from playroom.timeline import get_branch_head
from playroom.app import create_app


def _story(tmp_path):
    db = connect(tmp_path / "durable.sqlite3")
    migrate(db)
    owner = create_owner(db, "durable@example.test", "durable password")
    campaign = create_campaign(db, owner.id, "Durable", {"name": "World"}, [], {"name": "Player"})
    return db, owner, campaign


def _start_local_http(app):
    """Run the ASGI app on an ephemeral loopback port for streaming tests."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False, lifespan="on")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="playroom-test-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started and server.servers
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


def _stop_local_http(server, thread):
    server.should_exit = True
    thread.join(5)
    assert not thread.is_alive()


def _http_request(connection, method, path, *, cookie=None, body=None):
    headers = {"Host": "127.0.0.1", "Origin": "http://127.0.0.1"}
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    value = json.loads(raw.decode("utf-8")) if raw else None
    return response.status, response.getheaders(), value


def test_quality_dispatches_real_director_then_narrator_and_saves_context_run(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
    plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
    provider = FakeProvider([json.dumps(plan), "Narrator output."])
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="quality-1", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "candidate"
    assert job["attempts"] == ["context", "narration"]
    assert provider.stage_counts == {"context": 1, "narration": 1}
    assert db.execute("SELECT COUNT(*) FROM context_runs").fetchone()[0] == 1
    attempts = db.execute("SELECT stage, status, output_text, usage_json FROM provider_attempts WHERE generation_job_id=? ORDER BY stage", (job["id"],)).fetchall()
    assert [(row["stage"], row["status"]) for row in attempts] == [("context", "completed"), ("narration", "completed")]
    assert json.loads(attempts[0]["output_text"])["selected_memory_ids"] == []
    assert json.loads(attempts[0]["usage_json"])
    assert db.execute("SELECT COUNT(*) FROM provider_attempts WHERE status='dispatched'").fetchone()[0] == 0


def test_multiple_quality_jobs_release_all_global_capacity(tmp_path):
    db, owner, _ = _story(tmp_path)
    for index in range(3):
        campaign = create_campaign(db, owner.id, f"Quality {index}", {"name": "World"}, [], {"name": "Player"})
        head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
        pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
        plan = {
            "checkpoint_id": pool["checkpoint_id"],
            "action_hash": pool["action_hash"],
            "selected_memory_ids": [],
            "reasons": {},
            "reason_sources": {},
            "scene_ids": pool["scene_ids"],
            "conflict_flags": [],
        }
        provider = FakeProvider([json.dumps(plan), f"Narrator output {index}."])
        service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": f"director-{index}"}, "narrator": DEFAULT_PROFILE}})
        job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key=f"quality-capacity-{index}", expected_checkpoint_id=head.checkpoint_id, mode="quality")
        assert job["status"] == "candidate"
        assert [attempt["status"] for attempt in job["attempt_details"]] == ["completed", "completed"]
    assert db.execute("SELECT COUNT(*) FROM provider_attempts WHERE status='dispatched'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM generation_branch_guards").fetchone()[0] == 0


def test_quality_schema_failure_never_calls_narrator(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["not json", "must not run"])
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="quality-2", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "failed"
    assert job["failure"]["code"] == "SCHEMA_INVALID"
    assert provider.stage_counts == {"context": 1}


def test_quality_narrator_wire_uses_only_validated_director_selection(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    append_memory_version(db, campaign.id, campaign.initial_branch_id, "lore", "OPTIONAL LIGHTHOUSE MEMORY", origin="user", expected_state_version=head.state_version, source_revision_ids=[], status="approved")
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "lighthouse", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
    plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
    provider = FakeProvider([json.dumps(plan), "Narrator output."])
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "lighthouse", idempotency_key="quality-pack", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    director_wire = json.dumps(provider.calls[0], ensure_ascii=False)
    wire = json.dumps(provider.calls[-1], ensure_ascii=False)
    assert job["status"] == "candidate"
    assert pool["action_hash"] in director_wire
    assert "OPTIONAL LIGHTHOUSE MEMORY" not in wire


def test_free_only_rejects_paid_profile_before_provider_call(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {**DEFAULT_PROFILE, "credential_tier": "paid", "is_test_profile": False, "pricing": {"prompt": "0.000003", "completion": "0.000015"}}
    provider = FakeProvider(["must not dispatch"])
    service = GenerationService(db, provider, profile=profile)
    with pytest.raises(Exception, match="free"):
        service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="paid-free", expected_checkpoint_id=head.checkpoint_id)
    assert provider.calls == []


def test_existing_key_recovery_ignores_live_settings_revision(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["one response"])
    service = GenerationService(db, provider, settings={"settings_revision": 1})
    first = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="lost-response", expected_checkpoint_id=head.checkpoint_id)
    service.settings = {"settings_revision": 2, "mode": "quality"}
    recovered = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="lost-response", expected_checkpoint_id=head.checkpoint_id)
    assert recovered["id"] == first["id"]
    assert len(provider.calls) == 1


def test_partial_output_is_draft_and_offsets_are_unicode_safe(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider([{"events": ["Xin ", "chào 👋"], "finish_reason": "length"}])
    service = GenerationService(db, provider)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="partial-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "failed"
    assert job["draft"] == "Xin chào 👋"
    assert job["attempt_details"][0]["output_offset"] == len("Xin chào 👋".encode("utf-16-le")) // 2
    assert [event["event_type"] for event in job["events"]].count("delta") == 2
    with pytest.raises(Exception):
        service.commit_candidate(owner.id, job["id"])


def test_restart_before_dispatch_recovers_queued_job_without_replay(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    reserved = GenerationService(db, FakeProvider(["unused"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="restart-queued", expected_checkpoint_id=head.checkpoint_id, execute=False)
    assert reserved["status"] == "queued"
    provider = FakeProvider(["recovered candidate"])
    recovered_service = GenerationService(db, provider)
    recovered_service.recover_after_restart()
    job = recovered_service.run(reserved["id"])
    assert job["status"] == "candidate"
    assert len(provider.calls) == 1
    assert recovered_service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="restart-queued", expected_checkpoint_id=head.checkpoint_id)["id"] == reserved["id"]


def test_same_branch_reservation_is_serialized_across_connections(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    first_db = connect(tmp_path / "durable.sqlite3")
    second_db = connect(tmp_path / "durable.sqlite3")
    services = [GenerationService(first_db, FakeProvider([])), GenerationService(second_db, FakeProvider([]))]
    barrier = threading.Barrier(2)
    results, errors = [], []

    def reserve(service, key):
        barrier.wait()
        try:
            results.append(service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key=key, expected_checkpoint_id=head.checkpoint_id, execute=False))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve, args=(services[0], "race-one")), threading.Thread(target=reserve, args=(services[1], "race-two"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert len(results) == 1
    assert len(errors) == 1 and isinstance(errors[0], StateConflict)
    first_db.close()
    second_db.close()


def test_concurrent_candidate_commit_creates_one_revision(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    candidate = GenerationService(db, FakeProvider(["candidate"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="commit-race", expected_checkpoint_id=head.checkpoint_id)
    before = db.execute("SELECT COUNT(*) FROM turn_revisions").fetchone()[0]
    first_db = connect(tmp_path / "durable.sqlite3")
    second_db = connect(tmp_path / "durable.sqlite3")
    barrier = threading.Barrier(2)
    results, errors = [], []

    def commit(connection):
        barrier.wait()
        try:
            results.append(GenerationService(connection, FakeProvider([])).commit_candidate(owner.id, candidate["id"]))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=commit, args=(first_db,)), threading.Thread(target=commit, args=(second_db,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert len(results) + len(errors) == 2
    assert all(isinstance(error, StateConflict) for error in errors)
    assert db.execute("SELECT COUNT(*) FROM turn_revisions").fetchone()[0] == before + 1
    first_db.close()
    second_db.close()


def test_complete_candidate_can_become_stale_after_effective_story_mutation(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    service = GenerationService(db, FakeProvider(["candidate"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="guard-1", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "candidate"
    update_profile(db, campaign.id, campaign.initial_branch_id, "world", {"name": "changed"}, expected_state_version=head.state_version, owner_id=owner.id)
    with pytest.raises(StateConflict, match="stale"):
        service.commit_candidate(owner.id, job["id"])


def test_http_request_only_reserves_and_runtime_finishes_without_request_lifetime(tmp_path):
    database = tmp_path / "http.sqlite3"
    db = connect(database)
    migrate(db)
    owner, campaign = create_owner(db, "httpdurable@example.test", "http durable password"), None
    campaign = create_campaign(db, owner.id, "HTTP", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["HTTP candidate"])
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    app.state.generation_provider = provider
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post("/api/auth/login", json={"email": owner.email, "password": "http durable password"}, headers={"origin": "https://testserver"})
        assert login.status_code == 200
        response = client.post(f"/api/campaigns/{campaign.id}/generate", json={"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "http-1", "checkpoint_id": head.checkpoint_id}, headers={"origin": "https://testserver"})
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        assert response.json()["status"] in {"queued", "running", "candidate"}
        for _ in range(20):
            status = client.get(f"/api/generation/jobs/{job_id}")
            if status.json()["status"] == "candidate":
                break
            time.sleep(0.05)
        assert status.json()["status"] == "candidate"
        assert len(provider.calls) == 1
        lookup = client.get(f"/api/generation/jobs/by-key?branch_id={campaign.initial_branch_id}&idempotency_key=http-1")
        assert lookup.status_code == 200
        assert lookup.json()["id"] == job_id


@pytest.mark.parametrize("mode", ["economy", "quality"])
def test_local_http_lost_response_runs_each_mode_once(tmp_path, mode):
    database = tmp_path / f"lost-{mode}.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, f"lost-{mode}@example.test", "lost response password")
    campaign = create_campaign(db, owner.id, f"Lost {mode}", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    if mode == "quality":
        pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
        plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
        provider = FakeProvider([json.dumps(plan), "HTTP quality result"])
    else:
        provider = FakeProvider(["HTTP economy result"])
    app = create_app(database_url=str(database), allowed_hosts={"127.0.0.1"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    server, server_thread, port = _start_local_http(app)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        status, headers, _ = _http_request(connection, "POST", "/api/auth/login", body={"email": owner.email, "password": "lost response password"})
        assert status == 200
        cookie = next(value.split(";", 1)[0] for key, value in headers if key.casefold() == "set-cookie")
        connection.close()

        dropped = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        request_body = {"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": f"lost-{mode}", "checkpoint_id": head.checkpoint_id, "mode": mode}
        dropped.request("POST", f"/api/campaigns/{campaign.id}/generate", body=json.dumps(request_body).encode(), headers={"Host": "127.0.0.1", "Origin": "http://127.0.0.1", "Cookie": cookie, "Content-Type": "application/json"})
        response = dropped.getresponse()
        assert response.status == 201
        response.close()
        dropped.close()

        current = None
        for _ in range(100):
            poll = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            status, _, current = _http_request(poll, "GET", f"/api/generation/jobs/by-key?branch_id={campaign.initial_branch_id}&idempotency_key=lost-{mode}", cookie=cookie)
            poll.close()
            if status == 200 and current["status"] == "candidate":
                break
            time.sleep(0.05)
        assert current and current["status"] == "candidate"
        assert provider.stage_counts == ({"narration": 1} if mode == "economy" else {"context": 1, "narration": 1})
    finally:
        _stop_local_http(server, server_thread)


class _BlockingDirector(ProviderAdapter):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0
        self.request = None

    def capabilities_for(self, profile):
        return None

    def generate_structured(self, request, schema):
        self.calls += 1
        self.request = request
        self.started.set()
        self.release.wait(5)
        return ProviderFailure("CANCELLED", "blocked fixture released")


def test_http_cancel_signals_the_runtime_attempt_and_retains_physical_work(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingDirector()
    service = GenerationService(db, provider, profile={"roles": {"context": {**DEFAULT_PROFILE, "id": "director"}, "narrator": DEFAULT_PROFILE}}, timeout_seconds=10)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("job", service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="blocking", expected_checkpoint_id=head.checkpoint_id, mode="quality")))
    thread.start()
    assert provider.started.wait(2)
    second_connection = connect(tmp_path / "durable.sqlite3")
    second = GenerationService(second_connection, provider, attempt_registry=service.attempt_registry)
    cancelled = second.cancel(owner.id, result.get("job", {}).get("id") or db.execute("SELECT id FROM generation_jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0])
    assert cancelled["status"] == "cancelling"
    assert provider.request["cancel_event"].is_set()
    assert provider.release.is_set() is False
    provider.release.set()
    thread.join(3)
    assert not thread.is_alive()
    second_connection.close()


def _http_login(client, owner):
    response = client.post("/api/auth/login", json={"email": owner.email, "password": "durable password"}, headers={"origin": "https://testserver"})
    assert response.status_code == 200, response.text


def test_http_cancel_blocking_director_cannot_save_late_context(tmp_path):
    db, owner, campaign = _story(tmp_path)
    database = tmp_path / "durable.sqlite3"
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingDirector()
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    with TestClient(app, base_url="https://testserver") as client:
        _http_login(client, owner)
        response = client.post(f"/api/campaigns/{campaign.id}/generate", json={"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "http-director-cancel", "checkpoint_id": head.checkpoint_id, "mode": "quality"}, headers={"origin": "https://testserver"})
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        assert provider.started.wait(2)
        cancelled = client.post(f"/api/generation/jobs/{job_id}/cancel", headers={"origin": "https://testserver"})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelling"
        assert provider.request["cancel_event"].is_set()
        provider.release.set()
        for _ in range(30):
            current = client.get(f"/api/generation/jobs/{job_id}").json()
            if current["status"] in {"cancelled", "failed"}:
                break
            time.sleep(0.05)
        assert current["status"] == "cancelled"
        assert current["final_context_json"] is None
        assert all(attempt["status"] != "completed" for attempt in current["attempt_details"])


class _BlockingNarrator(ProviderAdapter):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0

    def capabilities_for(self, profile):
        return None

    def generate_text(self, request):
        self.calls += 1
        self.started.set()
        try:
            self.release.wait(5)
            yield ProviderResult(text="late narrator", usage={"status": "unknown"}, finish_reason="stop")
        finally:
            self.finished.set()


def test_http_cancel_blocking_narrator_cannot_create_candidate_from_late_result(tmp_path):
    db, owner, campaign = _story(tmp_path)
    database = tmp_path / "durable.sqlite3"
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingNarrator()
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    with TestClient(app, base_url="https://testserver") as client:
        _http_login(client, owner)
        response = client.post(f"/api/campaigns/{campaign.id}/generate", json={"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "http-narrator-cancel", "checkpoint_id": head.checkpoint_id}, headers={"origin": "https://testserver"})
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        assert provider.started.wait(2)
        cancelled = client.post(f"/api/generation/jobs/{job_id}/cancel", headers={"origin": "https://testserver"})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelling"
        provider.release.set()
        for _ in range(30):
            current = client.get(f"/api/generation/jobs/{job_id}").json()
            if current["status"] in {"cancelled", "failed"}:
                break
            time.sleep(0.05)
        assert current["status"] == "cancelled"
        assert current["draft"] == ""
        assert all(attempt["status"] != "completed" for attempt in current["attempt_details"])


def test_restart_interrupts_dispatched_stage_and_changes_execution_epoch(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    reserved = GenerationService(db, FakeProvider(["unused"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="restart-dispatched", expected_checkpoint_id=head.checkpoint_id, execute=False)
    old_epoch = reserved["execution_epoch"]
    db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (reserved["id"],))
    db.execute("UPDATE provider_attempts SET status='dispatched',claim_epoch=? WHERE generation_job_id=?", (old_epoch, reserved["id"]))
    db.commit()
    restarted = GenerationService(db, FakeProvider([]))
    restarted.recover_after_restart()
    current = restarted._job(reserved["id"])
    assert current["status"] == "interrupted"
    assert current["execution_epoch"] == old_epoch
    assert current["attempt_details"][0]["status"] == "interrupted"
    assert db.execute("SELECT 1 FROM generation_branch_guards WHERE generation_job_id=?", (reserved["id"],)).fetchone() is None


def test_completed_director_restart_resumes_only_queued_narrator(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    reserved = GenerationService(db, FakeProvider([])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="restart-director", expected_checkpoint_id=head.checkpoint_id, mode="quality", execute=False)
    preview = db.execute("SELECT preview_snapshot_json FROM generation_jobs WHERE id=?", (reserved["id"],)).fetchone()[0]
    db.execute("UPDATE generation_jobs SET status='running',final_context_json=? WHERE id=?", (preview, reserved["id"]))
    db.execute("UPDATE provider_attempts SET status='completed',output_text='{}',usage_json='{}' WHERE generation_job_id=? AND stage='context'", (reserved["id"],))
    db.commit()
    provider = FakeProvider(["resumed narrator"])
    restarted = GenerationService(db, provider)
    restarted.recover_after_restart()
    queued = restarted._job(reserved["id"])
    assert queued["status"] == "queued"
    assert [attempt["status"] for attempt in queued["attempt_details"]] == ["completed", "queued"]
    result = restarted.run(reserved["id"])
    assert result["status"] == "candidate"
    assert [call["stage"] for call in provider.calls] == ["narration"]


class _PartialBlockingNarrator(ProviderAdapter):
    def __init__(self):
        self.partial = threading.Event()
        self.release = threading.Event()

    def capabilities_for(self, profile):
        return None

    def generate_text(self, request):
        yield "partial 👋"
        self.partial.set()
        self.release.wait(5)
        yield ProviderResult(text="", usage={"status": "unknown"}, finish_reason="stop")


def test_restart_during_partial_narration_preserves_partial_and_blocks_late_candidate(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _PartialBlockingNarrator()
    service = GenerationService(db, provider, timeout_seconds=10)
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("job", service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="restart-partial", expected_checkpoint_id=head.checkpoint_id)))
    thread.start()
    assert provider.partial.wait(2)
    job_id = db.execute("SELECT id FROM generation_jobs WHERE idempotency_key='restart-partial'").fetchone()[0]
    restart_db = connect(tmp_path / "durable.sqlite3")
    restarted = GenerationService(restart_db, FakeProvider([]))
    restarted.recover_after_restart()
    provider.release.set()
    thread.join(3)
    assert not thread.is_alive()
    current = restarted._job(job_id)
    assert current["status"] == "interrupted"
    assert current["draft"] == "partial 👋"
    assert all(attempt["status"] != "completed" for attempt in current["attempt_details"])
    restart_db.close()


def test_runtime_shutdown_keeps_connection_open_while_provider_is_blocked(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingNarrator()
    seed = GenerationService(db, provider)
    seed.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="shutdown-blocked", expected_checkpoint_id=head.checkpoint_id, execute=False)
    runtime = GenerationRuntime(str(tmp_path / "durable.sqlite3"), provider, poll_seconds=0.01)
    runtime.start()
    assert provider.started.wait(2)
    assert runtime.stop() is False
    assert runtime.connection.execute("SELECT 1").fetchone()[0] == 1
    provider.release.set()
    assert provider.finished.wait(2)
    assert runtime._thread is not None
    runtime._thread.join(2)
    assert runtime.stop() is True


def test_commit_rejects_competing_branch_guard(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    first = GenerationService(db, FakeProvider(["first"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="first", expected_checkpoint_id=head.checkpoint_id)
    second = GenerationService(db, FakeProvider(["second"])).generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="second", expected_checkpoint_id=head.checkpoint_id, execute=False)
    assert second["status"] == "queued"
    with pytest.raises(StateConflict, match="active generation"):
        GenerationService(db, FakeProvider([])).commit_candidate(owner.id, first["id"])


def test_commit_event_uses_utf16_offset(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    service = GenerationService(db, FakeProvider(["Xin chào 👋"]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="commit-unicode", expected_checkpoint_id=head.checkpoint_id)
    committed = service.commit_candidate(owner.id, job["id"])
    event = next(item for item in committed["events"] if item["event_type"] == "committed")
    assert event["offset"] == len("Xin chào 👋".encode("utf-16-le")) // 2
    assert event["payload"]["offset_unit"] == "utf16_code_units"


def test_app_keeps_credential_resolver_for_factory_dispatch(tmp_path):
    app = create_app(database_url=str(tmp_path / "factory.sqlite3"), credential_root=tmp_path / "secrets", generation_provider_factory=lambda **kwargs: FakeProvider(["ok"]))
    assert callable(app.state.generation_credential_resolver)


def test_factory_resolves_distinct_role_profiles_and_pinned_credentials(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    context_profile = {**DEFAULT_PROFILE, "id": "director", "version": 2, "profile_hash": "director-hash", "secret_version": "context-key"}
    narrator_profile = {**DEFAULT_PROFILE, "id": "narrator", "version": 3, "profile_hash": "narrator-hash", "secret_version": "narrator-key"}
    plan = {"checkpoint_id": head.checkpoint_id, "action_hash": "", "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": [], "conflict_flags": []}
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeProvider([json.dumps({**plan, "action_hash": kwargs["profile"].get("expected_action_hash", "")})] if kwargs["stage"] == "context" else ["factory narrative"])

    # The director fixture is filled with the pool hash by the provider below.
    class RoleProvider(FakeProvider):
        def generate_structured(self, request, schema):
            return ProviderResult(text=json.dumps({**plan, "action_hash": request["action_hash"]}), usage={"status": "unknown"})

    def role_factory(**kwargs):
        calls.append(kwargs)
        return RoleProvider([]) if kwargs["stage"] == "context" else FakeProvider(["factory narrative"])

    service = GenerationService(db, FakeProvider([]), profile={"roles": {"context": context_profile, "narrator": narrator_profile}}, provider_factory=role_factory, credential_resolver=lambda owner_id, version: {"context-key": "context-secret", "narrator-key": "narrator-secret"}[version])
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="factory-roles", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "candidate"
    assert [(call["stage"], call["profile"]["id"], call["credential"]) for call in calls] == [("context", "director", "context-secret"), ("narration", "narrator", "narrator-secret")]


def test_missing_pinned_credential_stops_before_provider_invocation(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {**DEFAULT_PROFILE, "secret_version": "revoked-key"}
    calls = []
    service = GenerationService(db, FakeProvider(["must not run"]), profile=profile, provider_factory=lambda **kwargs: calls.append(kwargs) or FakeProvider(["wrong"]), credential_resolver=lambda owner_id, version: (_ for _ in ()).throw(ValueError("revoked")))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="missing-key", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "failed"
    assert job["failure"]["code"] == "CREDENTIAL_UNAVAILABLE"
    assert calls == []


def test_physical_slot_survives_logical_timeout_until_provider_stops():
    class BlockingNarrator(ProviderAdapter):
        def __init__(self):
            self.release = threading.Event()
            self.finished = threading.Event()
        def capabilities_for(self, profile):
            return None
        def generate_text(self, request):
            self.release.wait(3)
            self.finished.set()
            yield ProviderResult(text="done")

    provider = BlockingNarrator()
    registry = PhysicalAttemptRegistry(limit=2)
    stream = registry.stream("job:narration", provider, {}, timeout=0.05)
    with pytest.raises(TimeoutError):
        next(stream)
    assert registry.active() == 1
    provider.release.set()
    assert provider.finished.wait(1)
    assert registry.active() == 0


def test_zero_row_dispatch_claim_never_invokes_provider(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["must not run"])
    service = GenerationService(db, provider)
    reserved = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="claim-race", expected_checkpoint_id=head.checkpoint_id, execute=False)
    service._mark_dispatched = lambda key: False
    finished = service.run(reserved["id"])
    assert finished["status"] == "cancelled"
    assert provider.calls == []


class _BlockingStructured(ProviderAdapter):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0

    def capabilities_for(self, profile):
        return None

    def generate_structured(self, request, schema):
        self.calls += 1
        self.started.set()
        try:
            self.release.wait(5)
            return ProviderFailure("CANCELLED", "released blocker")
        finally:
            self.finished.set()


def _run_blocking_structured(registry, key, provider, finished):
    try:
        registry.structured(key, provider, {}, {}, 5)
    except Exception:
        pass
    finally:
        finished.set()


def test_waiting_attempt_can_cancel_before_a_slot_and_never_invokes(tmp_path):
    registry = PhysicalAttemptRegistry(limit=2)
    first, second, waiting = _BlockingStructured(), _BlockingStructured(), _BlockingStructured()
    done1, done2, done3 = threading.Event(), threading.Event(), threading.Event()
    threading.Thread(target=_run_blocking_structured, args=(registry, "one:context", first, done1), daemon=True).start()
    threading.Thread(target=_run_blocking_structured, args=(registry, "two:context", second, done2), daemon=True).start()
    assert first.started.wait(1) and second.started.wait(1)
    waiter = threading.Thread(target=_run_blocking_structured, args=(registry, "three:context", waiting, done3), daemon=True)
    waiter.start()
    assert registry.wait_registered("three:context", 1)
    registry.cancel("three")
    assert done3.wait(1)
    first.release.set()
    second.release.set()
    assert done1.wait(1) and done2.wait(1)
    assert waiting.calls == 0


def test_waiting_attempt_deadline_expires_before_slot_and_never_invokes():
    registry = PhysicalAttemptRegistry(limit=2)
    first, second, waiting = _BlockingStructured(), _BlockingStructured(), _BlockingStructured()
    done1, done2 = threading.Event(), threading.Event()
    threading.Thread(target=_run_blocking_structured, args=(registry, "one:context", first, done1), daemon=True).start()
    threading.Thread(target=_run_blocking_structured, args=(registry, "two:context", second, done2), daemon=True).start()
    assert first.started.wait(1) and second.started.wait(1)
    result = {}
    def waiting_call():
        try:
            result["value"] = registry.structured("three:context", waiting, {}, {}, 0.05)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=waiting_call, daemon=True)
    thread.start()
    assert registry.wait_registered("three:context", 1)
    thread.join(1)
    assert not thread.is_alive()
    assert isinstance(result.get("error"), TimeoutError)
    first.release.set()
    second.release.set()
    assert done1.wait(1) and done2.wait(1)
    assert waiting.calls == 0


def test_two_logically_timed_out_calls_retain_slots_against_third_invocation():
    registry = PhysicalAttemptRegistry(limit=2)
    first, second, third = _BlockingStructured(), _BlockingStructured(), _BlockingStructured()
    done1, done2, done3 = threading.Event(), threading.Event(), threading.Event()

    def timed_out(key, provider, done):
        try:
            registry.structured(key, provider, {}, {}, 0.05)
        except TimeoutError:
            pass
        finally:
            done.set()

    threading.Thread(target=timed_out, args=("one:context", first, done1), daemon=True).start()
    threading.Thread(target=timed_out, args=("two:context", second, done2), daemon=True).start()
    assert first.started.wait(1) and second.started.wait(1)
    assert done1.wait(1) and done2.wait(1)
    assert registry.active() == 2
    threading.Thread(target=_run_blocking_structured, args=(registry, "three:context", third, done3), daemon=True).start()
    assert registry.wait_registered("three:context", 1)
    registry.cancel("three")
    assert done3.wait(1)
    first.release.set()
    second.release.set()
    assert first.finished.wait(1) and second.finished.wait(1)
    assert registry.active() == 0
    assert third.calls == 0


def test_waiting_attempt_resolves_pinned_key_only_after_slot_and_rejects_revoked_version():
    registry = PhysicalAttemptRegistry(limit=2)
    first, second = _BlockingStructured(), _BlockingStructured()
    done1, done2, done3 = threading.Event(), threading.Event(), threading.Event()
    threading.Thread(target=_run_blocking_structured, args=(registry, "one:context", first, done1), daemon=True).start()
    threading.Thread(target=_run_blocking_structured, args=(registry, "two:context", second, done2), daemon=True).start()
    assert first.started.wait(1) and second.started.wait(1)
    factory_called = threading.Event()
    revoked = threading.Event()
    calls = []

    def resolve_then_call(handle):
        factory_called.set()
        if revoked.is_set():
            return ProviderFailure("CREDENTIAL_UNAVAILABLE", "revoked")
        calls.append("provider")
        return _BlockingStructured()

    result = {}
    def waiting_call():
        result["value"] = registry.structured("three:context", None, {}, {}, 2, provider_factory=resolve_then_call)
        done3.set()

    thread = threading.Thread(target=waiting_call, daemon=True)
    thread.start()
    assert registry.wait_registered("three:context", 1)
    assert not factory_called.is_set()
    revoked.set()
    first.release.set()
    second.release.set()
    assert done1.wait(1) and done2.wait(1) and done3.wait(1)
    assert factory_called.is_set()
    assert result["value"].code == "CREDENTIAL_UNAVAILABLE"
    assert calls == []


def test_http_raw_identity_recovers_omitted_choices_after_settings_change(tmp_path):
    from playroom.model_profiles import persist_model_profile
    from playroom.settings import save_owner_settings

    database = tmp_path / "raw-http.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "raw@example.test", "raw identity password")
    campaign = create_campaign(db, owner.id, "Raw", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["raw candidate"])
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    with TestClient(app, base_url="https://testserver") as client:
        headers = {"origin": "https://testserver"}
        assert client.post("/api/auth/login", json={"email": owner.email, "password": "raw identity password"}, headers=headers).status_code == 200
        body = {"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "raw-1", "checkpoint_id": head.checkpoint_id}
        first = client.post(f"/api/campaigns/{campaign.id}/generate", json=body, headers=headers)
        assert first.status_code == 201
        profile = persist_model_profile(db, owner.id, {"id": "raw-profile", "provider": "openrouter", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "model": "author/model", "context_limit": 12000, "output_limit": 4000, "credential_tier": "free", "pricing_verified": True, "secret_version": "credential-v1"})
        binding = {"id": profile["id"], "version": profile["version"], "profile_hash": profile["profile_hash"]}
        save_owner_settings(db, owner.id, {"roles": {"narrator": binding, "context": binding}, "mode": "quality", "policy": "free_only"})
        recovered = client.post(f"/api/campaigns/{campaign.id}/generate", json=body, headers=headers)
        assert recovered.status_code == 201
        assert recovered.json()["id"] == first.json()["id"]
        changed = client.post(f"/api/campaigns/{campaign.id}/generate", json={**body, "action": "Changed"}, headers=headers)
        assert changed.status_code == 409


def test_authenticated_sse_stream_replays_events_with_resume_cursor(tmp_path):
    database = tmp_path / "sse.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "sse@example.test", "sse stream password")
    campaign = create_campaign(db, owner.id, "SSE", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    app = create_app(database_url=str(database), allowed_hosts={"testserver"}, secure_cookies=False, generation_provider=FakeProvider(["streamed" ]), credential_root=tmp_path / "secrets")
    with TestClient(app, base_url="https://testserver") as client:
        headers = {"origin": "https://testserver"}
        client.post("/api/auth/login", json={"email": owner.email, "password": "sse stream password"}, headers=headers)
        response = client.post(f"/api/campaigns/{campaign.id}/generate", json={"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "sse-1", "checkpoint_id": head.checkpoint_id}, headers=headers)
        job_id = response.json()["id"]
        with client.stream("GET", f"/api/generation/jobs/{job_id}/events/stream") as stream:
            text = "".join(stream.iter_text())
            assert stream.headers["content-type"].startswith("text/event-stream")
            assert "event: reserved" in text and "event: completed" in text
        events = client.get(f"/api/generation/jobs/{job_id}/events").json()["events"]
        first_cursor = events[0]["id"]
        with client.stream("GET", f"/api/generation/jobs/{job_id}/events/stream?after={first_cursor}") as resumed:
            resumed_text = "".join(resumed.iter_text())
            assert "event: reserved" not in resumed_text
            assert "event: completed" in resumed_text


def test_local_http_sse_reconstructs_vietnamese_astral_text_and_resumes(tmp_path):
    database = tmp_path / "sse-unicode.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "sse-unicode@example.test", "sse unicode password")
    campaign = create_campaign(db, owner.id, "SSE Unicode", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    text = "Xin chào 👋 — tiếp tục"
    provider = FakeProvider([text])
    app = create_app(database_url=str(database), allowed_hosts={"127.0.0.1"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    server, server_thread, port = _start_local_http(app)
    try:
        login = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        status, headers, _ = _http_request(login, "POST", "/api/auth/login", body={"email": owner.email, "password": "sse unicode password"})
        assert status == 200
        cookie = next(value.split(";", 1)[0] for key, value in headers if key.casefold() == "set-cookie")
        login.close()
        submit = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = {"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "sse-unicode", "checkpoint_id": head.checkpoint_id}
        status, _, current = _http_request(submit, "POST", f"/api/campaigns/{campaign.id}/generate", cookie=cookie, body=body)
        assert status == 201
        submit.close()
        job_id = current["id"]
        for _ in range(100):
            poll = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            status, _, current = _http_request(poll, "GET", f"/api/generation/jobs/{job_id}", cookie=cookie)
            poll.close()
            if current["status"] == "candidate":
                break
            time.sleep(0.05)
        assert current["status"] == "candidate"

        stream = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        stream.request("GET", f"/api/generation/jobs/{job_id}/events/stream", headers={"Host": "127.0.0.1", "Cookie": cookie})
        response = stream.getresponse()
        raw = response.read()
        response.close()
        stream.close()
        decoded = raw.decode("utf-8")
        frames = [json.loads(line.removeprefix("data: ")) for line in decoded.splitlines() if line.startswith("data: ")]
        assert "event: delta" in decoded
        assert "".join(frame["content"] for frame in frames if frame["event_type"] == "delta") == text

        events_connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        status, _, event_payload = _http_request(events_connection, "GET", f"/api/generation/jobs/{job_id}/events", cookie=cookie)
        events_connection.close()
        assert status == 200
        first_cursor = event_payload["events"][0]["id"]
        resumed = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        resumed.request("GET", f"/api/generation/jobs/{job_id}/events/stream?after={first_cursor}", headers={"Host": "127.0.0.1", "Cookie": cookie})
        resumed_response = resumed.getresponse()
        resumed_text = resumed_response.read().decode("utf-8")
        resumed_response.close()
        resumed.close()
        assert "event: reserved" not in resumed_text
        assert "event: completed" in resumed_text
        assert provider.stage_counts == {"narration": 1}
    finally:
        _stop_local_http(server, server_thread)


def test_local_http_active_sse_disconnect_does_not_resend_provider(tmp_path):
    database = tmp_path / "sse-disconnect.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "sse-disconnect@example.test", "sse disconnect password")
    campaign = create_campaign(db, owner.id, "SSE disconnect", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingNarrator()
    app = create_app(database_url=str(database), allowed_hosts={"127.0.0.1"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    server, server_thread, port = _start_local_http(app)
    sse = None
    try:
        login = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        status, headers, _ = _http_request(login, "POST", "/api/auth/login", body={"email": owner.email, "password": "sse disconnect password"})
        assert status == 200
        cookie = next(value.split(";", 1)[0] for key, value in headers if key.casefold() == "set-cookie")
        login.close()
        submit = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = {"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "sse-disconnect", "checkpoint_id": head.checkpoint_id}
        status, _, current = _http_request(submit, "POST", f"/api/campaigns/{campaign.id}/generate", cookie=cookie, body=body)
        submit.close()
        assert status == 201
        job_id = current["id"]
        assert provider.started.wait(2)
        sse = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        sse.request("GET", f"/api/generation/jobs/{job_id}/events/stream", headers={"Host": "127.0.0.1", "Cookie": cookie})
        response = sse.getresponse()
        assert response.status == 200
        assert response.readline().startswith(b"id:")
        response.close()
        sse.close()
        sse = None
        provider.release.set()
        for _ in range(100):
            poll = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            status, _, current = _http_request(poll, "GET", f"/api/generation/jobs/{job_id}", cookie=cookie)
            poll.close()
            if current["status"] == "candidate":
                break
            time.sleep(0.05)
        assert current["status"] == "candidate"
        assert provider.calls == 1
    finally:
        if sse is not None:
            sse.close()
        provider.release.set()
        _stop_local_http(server, server_thread)


def test_local_http_session_revocation_ends_active_sse_without_private_bytes(tmp_path):
    database = tmp_path / "sse-revoke.sqlite3"
    db = connect(database)
    migrate(db)
    owner = create_owner(db, "sse-revoke@example.test", "sse revoke password")
    campaign = create_campaign(db, owner.id, "SSE revoke", {"name": "World"}, [], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = _BlockingNarrator()
    app = create_app(database_url=str(database), allowed_hosts={"127.0.0.1"}, secure_cookies=False, generation_provider=provider, credential_root=tmp_path / "secrets")
    server, server_thread, port = _start_local_http(app)
    sse = None
    response = None
    try:
        login = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        status, headers, _ = _http_request(login, "POST", "/api/auth/login", body={"email": owner.email, "password": "sse revoke password"})
        assert status == 200
        cookie = next(value.split(";", 1)[0] for key, value in headers if key.casefold() == "set-cookie")
        login.close()
        submit = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = {"branch_id": campaign.initial_branch_id, "action": "Look", "idempotency_key": "sse-revoke", "checkpoint_id": head.checkpoint_id}
        status, _, current = _http_request(submit, "POST", f"/api/campaigns/{campaign.id}/generate", cookie=cookie, body=body)
        submit.close()
        assert status == 201
        job_id = current["id"]
        assert provider.started.wait(2)

        sse = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        sse.request("GET", f"/api/generation/jobs/{job_id}/events/stream", headers={"Host": "127.0.0.1", "Cookie": cookie})
        response = sse.getresponse()
        assert response.status == 200
        chunks = [response.readline()]
        reader_done = threading.Event()

        def read_until_revoked():
            try:
                while True:
                    line = response.readline()
                    if not line:
                        return
                    chunks.append(line)
                    if b"event: session_expired" in line:
                        return
            finally:
                reader_done.set()

        reader = threading.Thread(target=read_until_revoked, name="playroom-test-sse-reader", daemon=True)
        reader.start()
        revoke = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        status, _, _ = _http_request(revoke, "POST", "/api/auth/logout", cookie=cookie)
        revoke.close()
        assert status == 204
        assert reader_done.wait(5)
        wire = b"".join(chunks)
        marker = b"event: session_expired"
        assert marker in wire
        assert b"late narrator" not in wire[wire.index(marker):]
        provider.release.set()
    finally:
        if response is not None:
            response.close()
        if sse is not None:
            sse.close()
        provider.release.set()
        _stop_local_http(server, server_thread)
