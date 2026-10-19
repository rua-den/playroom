from __future__ import annotations

import hashlib
import json
import time

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.provider import default_provider_factory
from playroom.timeline import get_branch_head
from playroom.wire_cost import canonical_json


def _poll_terminal(client: TestClient, job_id: str, *, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/generation/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"candidate", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.05)
    raise AssertionError("generation job did not reach a terminal state")


@pytest.mark.parametrize("policy", ["free_only", "capped_paid"])
@pytest.mark.parametrize("keyed", [False, True])
def test_custom_provider_authenticated_generation_commits_and_reloads(
    tmp_path, policy: str, keyed: bool
):
    from playroom.app import create_app

    database = tmp_path / f"custom-generation-{policy}-{keyed}.sqlite3"
    connection = connect(database)
    migrate(connection)
    owner = create_owner(connection, f"custom-generation-{policy}-{keyed}@example.test", "password-custom-generation")
    campaign = create_campaign(
        connection,
        owner.id,
        "Synthetic custom provider story",
        {"name": "A quiet room", "public_canon": "A blue paper waits."},
        [],
        {"name": "Player"},
    )
    checkpoint_id = get_branch_head(connection, campaign.id, campaign.initial_branch_id).checkpoint_id
    connection.close()

    calls: list[dict] = []
    response_body = (
        b'data: {"choices":[{"delta":{"content":"{\\"segments\\":[{\\"kind\\":\\"narration\\",\\"text\\":\\"Synthetic custom response.\\"}]}"}}]}\n\n'
        b'data: {"choices":[{"finish_reason":"stop"}]}\n\n'
        b'data: [DONE]\n\n'
    )

    def route(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url), "headers": dict(request.headers), "payload": json.loads(request.content)})
        return httpx.Response(200, content=response_body, headers={"content-type": "text/event-stream"})

    http_client = httpx.Client(transport=httpx.MockTransport(route))

    def factory(*, owner_id, stage, profile, credential):
        return default_provider_factory(
            owner_id=owner_id,
            stage=stage,
            profile=profile,
            credential=credential,
            http_client=http_client,
        )

    resolver_calls: list[tuple[str, str | None]] = []
    app = create_app(
        database_url=f"sqlite:///{database}",
        allowed_hosts={"testserver"},
        secure_cookies=False,
        credential_root=tmp_path / "secrets",
        generation_provider_factory=factory,
    )
    original_resolver = app.state.generation_credential_resolver
    if keyed:
        def recording_resolver(owner_id, version):
            resolver_calls.append((owner_id, version))
            return original_resolver(owner_id, version)
        app.state.generation_credential_resolver = recording_resolver
    else:
        app.state.generation_credential_resolver = lambda *_args: (_ for _ in ()).throw(AssertionError("keyless custom resolver was called"))
    headers = {"origin": "https://testserver"}
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post("/api/auth/login", json={"email": owner.email, "password": "password-custom-generation"}, headers=headers)
        assert login.status_code == 200, login.text

        credential = None
        if keyed:
            credential_response = client.post("/api/provider/credentials", json={"secret": "synthetic-owner-key"}, headers=headers)
            assert credential_response.status_code == 201, credential_response.text
            credential = credential_response.json()

        profile_response = client.post(
            "/api/provider/profiles/custom",
            json={
                "endpoint": "http://127.0.0.1:1234/v1",
                "model": "arbitrary-synthetic-model",
                **({"credential_id": credential["id"]} if credential else {}),
            },
            headers=headers,
        )
        assert profile_response.status_code == 201, profile_response.text
        profile = profile_response.json()
        assert profile["pricing"] is None
        assert profile["pricing_provenance"] == "unknown"
        assert profile["custom_billing"] == "provider_managed"
        assert profile.get("secret") is None

        settings_payload = {
            "narrator_profile_id": profile["id"],
            "mode": "economy",
            "policy": policy,
        }
        if policy == "capped_paid":
            settings_payload["confirmed_usd_cap"] = "0.01"
        settings = client.put("/api/provider/settings", json=settings_payload, headers=headers)
        assert settings.status_code == 200, settings.text
        assert settings.json()["roles"]["narrator"]["version"] == profile["version"]

        preview_response = client.post(
            f"/api/campaigns/{campaign.id}/context/previews",
            json={"branch_id": campaign.initial_branch_id, "action": "Read the paper", "profile_id": profile["id"]},
            headers=headers,
        )
        assert preview_response.status_code == 201, preview_response.text
        preview = preview_response.json()
        assert preview["status"] == "ready"
        assert calls == []

        generate_response = client.post(
            f"/api/campaigns/{campaign.id}/generate",
            json={
                "branch_id": campaign.initial_branch_id,
                "action": "Read the paper",
                "idempotency_key": f"custom-{policy}-{keyed}",
                "checkpoint_id": checkpoint_id,
                "preview_id": preview["id"],
            },
            headers=headers,
        )
        assert generate_response.status_code == 201, generate_response.text
        job = _poll_terminal(client, generate_response.json()["id"])
        assert job["status"] == "candidate", job
        assert job["cost_ledger"]["reserved_total_usd"] is None
        assert job["cost_ledger"]["cap"] is None
        assert job["cost_ledger"]["actual_total_usd"] is None
        assert job["cost_ledger"]["calculated_total_usd"] is None
        assert job["cost_ledger"]["stages"]["narration"]["estimated_cost_usd"] is None
        assert job["cost_ledger"]["stages"]["narration"]["cost_provenance"] == "provider_managed_unknown"
        assert job["attempt_details"][0]["status"] == "completed"
        attempt = next(item for item in job["attempt_details"] if item["stage"] == "narration")
        assert attempt["status"] == "completed"
        assert attempt["profile_snapshot"]["provider"] == "custom"
        assert "synthetic-owner-key" not in json.dumps(attempt["profile_snapshot"])
        wire = attempt["request"]["prepared_wire"]
        wire_hash = hashlib.sha256(canonical_json(wire).encode("utf-8")).hexdigest()
        assert wire_hash == attempt["request"]["wire_metadata"]["payload_hash"]
        assert wire_hash == attempt["payload_hash"]
        assert wire == calls[0]["payload"]

        committed = client.post(f"/api/generation/jobs/{job['id']}/commit", headers=headers)
        assert committed.status_code == 200, committed.text
        projection = client.get(f"/api/campaigns/{campaign.id}/projection?branch_id={campaign.initial_branch_id}")
        assert projection.status_code == 200
        assert len(projection.json()["transcript"]) == 1

    reloaded_app = create_app(
        database_url=f"sqlite:///{database}",
        allowed_hosts={"testserver"},
        secure_cookies=False,
        credential_root=tmp_path / "secrets",
        generation_provider_factory=factory,
    )
    with TestClient(reloaded_app, base_url="https://testserver") as client:
        assert client.post("/api/auth/login", json={"email": owner.email, "password": "password-custom-generation"}, headers=headers).status_code == 200
        projection = client.get(f"/api/campaigns/{campaign.id}/projection?branch_id={campaign.initial_branch_id}")
        assert projection.status_code == 200
        assert projection.json()["transcript"][0]["output_segments"] == [{"kind": "narration", "text": "Synthetic custom response."}]

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    if keyed:
        assert calls[0]["headers"]["authorization"] == "Bearer synthetic-owner-key"
        assert resolver_calls == [(owner.id, credential["id"])]
    else:
        assert "authorization" not in calls[0]["headers"]
        assert resolver_calls == []
    assert "synthetic-owner-key" not in json.dumps(profile)
    persisted = connect(database)
    try:
        assert persisted.execute("SELECT COUNT(*) FROM paid_trial_authorizations").fetchone()[0] == 0
        assert persisted.execute("SELECT COUNT(*) FROM paid_trial_reservations").fetchone()[0] == 0
        context_run = persisted.execute("SELECT payload_hash, wire_json FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()
        assert context_run["payload_hash"] == wire_hash
        assert json.loads(context_run["wire_json"])["narrator"] == calls[0]["payload"]
    finally:
        persisted.close()
