"""One-shot synthetic Ollama trial through the real local application stack.

The live path is protected by the workflow and the product's persisted
settings/trial grant.  Offline mode exercises only local contracts and never
reads or transmits a credential.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx2 as httpx
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.db import connect, migrate
from playroom.live_local import create_live_local_app
from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT, OLLAMA_FREE_CLOUD_MODEL
from playroom.provider import default_provider_factory


APPROVAL = "B4_LOCAL_APP_TRIAL_2026_10_18"
MODEL = OLLAMA_FREE_CLOUD_MODEL
MAX_OUTPUT_TOKENS = 640
MAX_TRIAL_USD = Decimal("0.01")
RESERVED_INPUT_TOKENS = 1800
ESTIMATED_RESERVE_USD = Decimal("0.000508")
OWNER_EMAIL = "synthetic-app-trial@example.test"
OWNER_PASSWORD = "synthetic app trial password"
ACTION = '*Lan mở chiếc hộp gỗ trên quầy.* "Vy, cậu có thấy tờ giấy xanh không?"'
NPC_ID = "00000000-0000-4000-8000-000000000001"
NPC_VERSION = "vy-profile-v1"


def trial_contract() -> dict:
    return {
        "max_provider_posts": 1,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "max_usd": MAX_TRIAL_USD,
        "private_fixture": True,
        "endpoint": OLLAMA_CLOUD_ENDPOINT,
    }


class CountingHttpClient:
    """Transport wrapper counting only the actual completion POST."""

    def __init__(self, client):
        self.client = client
        self.provider_posts = 0

    def record_post(self, url: str) -> None:
        if url == f"{OLLAMA_CLOUD_ENDPOINT}/chat/completions":
            self.provider_posts += 1
            if self.provider_posts > 1:
                raise RuntimeError("provider completion allows at most one POST")

    def stream(self, method, url, *args, **kwargs):
        if method.upper() == "POST":
            self.record_post(url)
        return self.client.stream(method, url, *args, **kwargs)

    def close(self):
        self.client.close()


def ensure_live_gate() -> bool:
    if os.environ.get("B4_LOCAL_APP_APPROVAL") != APPROVAL:
        return False
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        return False
    if not os.environ.get("OLLAMA_API_KEY"):
        return False
    return True


def _balance_preflight(secret: str) -> None:
    request = urllib.request.Request(
        "https://ollama.com/api/balance",
        headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            payload = json.load(response)
        included = Decimal(str(payload["included"]["balance_usd"]))
        purchased = Decimal(str(payload["purchased"]["balance_usd"]))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, TypeError, ValueError, InvalidOperation):
        raise RuntimeError("balance preflight unavailable; no provider POST") from None
    if not included.is_finite() or not purchased.is_finite() or included < ESTIMATED_RESERVE_USD or purchased != 0:
        raise RuntimeError("balance preflight did not establish included allowance and zero purchased credits")


def _assert_ok(response, expected: int | set[int] = 200) -> dict:
    statuses = {expected} if isinstance(expected, int) else expected
    if response.status_code not in statuses:
        raise RuntimeError(f"API step failed with status {response.status_code}")
    return response.json()


def _make_app(root: Path, transport: CountingHttpClient):
    frontend = root / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<html>synthetic</html>", encoding="utf-8")
    app = create_live_local_app(root / "data", frontend_dist=frontend)

    def factory(*, owner_id, stage, profile, credential, http_client=None):
        if stage != "narration":
            return default_provider_factory(owner_id=owner_id, stage=stage, profile=profile, credential=credential, http_client=http_client)
        return default_provider_factory(owner_id=owner_id, stage=stage, profile=profile, credential=credential, http_client=transport)

    app.state.generation_provider_factory = factory
    return app


def _create_owner(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    connection = connect(root / "data" / "playroom.sqlite3")
    try:
        migrate(connection)
        create_owner(connection, OWNER_EMAIL, OWNER_PASSWORD)
    finally:
        connection.close()


def _poll_job(client: TestClient, job_id: str) -> dict:
    for _ in range(90):
        job = _assert_ok(client.get(f"/api/generation/jobs/{job_id}"))
        if job.get("status") in {"candidate", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(1)
    raise RuntimeError("generation job polling exceeded bounded timeout")


def _run_live() -> int:
    secret = os.environ["OLLAMA_API_KEY"]
    _balance_preflight(secret)
    with tempfile.TemporaryDirectory(prefix="playroom-app-trial-") as directory:
        root = Path(directory)
        _create_owner(root)
        transport = CountingHttpClient(httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)))
        app = _make_app(root, transport)
        headers = {"origin": "http://127.0.0.1"}
        campaign = None
        job = None
        with TestClient(app, base_url="http://127.0.0.1") as client:
            _assert_ok(client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, headers=headers))
            campaign = _assert_ok(client.post("/api/campaigns", json={
                "title": "Synthetic Ollama app trial",
                "world": {"name": "Hiệu sách vắng lúc tối", "public_canon": "Tờ giấy xanh chưa ai đọc."},
                "characters": [{"id": NPC_ID, "name": "Vy", "profile_version_id": NPC_VERSION, "present": True}],
                "persona": {"name": "Lan", "player_controlled": True},
            }, headers=headers), 201)
            credential = _assert_ok(client.post("/api/provider/credentials", json={"secret": secret}, headers=headers), 201)
            profile = _assert_ok(client.post("/api/provider/profiles/verify", json={
                "provider": "ollama", "credential_id": credential["id"], "model": MODEL,
                "endpoint": OLLAMA_CLOUD_ENDPOINT,
            }, headers=headers), 201)
            if profile.get("model") != "gemma4:31b" or profile.get("free_starter_eligible") is not True:
                raise RuntimeError("verified Ollama profile was unavailable or not starter eligible")
            settings = _assert_ok(client.put("/api/provider/settings", json={
                "narrator_profile_id": profile["id"], "mode": "economy", "policy": "capped_paid",
                "confirmed_usd_cap": str(MAX_TRIAL_USD),
                "budgets": {"narrator": {"input_limit": RESERVED_INPUT_TOKENS, "requested_output": MAX_OUTPUT_TOKENS, "wrapper_buffer": 64}},
            }, headers=headers))
            if settings.get("roles", {}).get("narrator", {}).get("version") != profile.get("version"):
                raise RuntimeError("immutable narrator profile binding was not persisted")
            expires = "2099-01-01T00:00:00+00:00"
            _assert_ok(client.post("/api/provider/trials", json={
                "profile_id": profile["id"], "profile_version": profile["version"],
                "total_cap_usd": str(MAX_TRIAL_USD), "per_send_cap_usd": str(MAX_TRIAL_USD),
                "max_jobs": 1, "expires_at": expires,
            }, headers=headers), 201)
            detail = _assert_ok(client.get(f"/api/campaigns/{campaign['id']}"))
            preview = _assert_ok(client.post(f"/api/campaigns/{campaign['id']}/context/previews", json={
                "branch_id": campaign["branch_id"], "action": ACTION,
            }, headers=headers), 201)
            job = _assert_ok(client.post(f"/api/campaigns/{campaign['id']}/generate", json={
                "branch_id": campaign["branch_id"], "action": ACTION,
                "idempotency_key": "synthetic-app-trial-once", "checkpoint_id": detail["checkpoint_id"],
                "preview_id": preview["id"], "mode": "economy", "policy": "capped_paid", "cap": str(MAX_TRIAL_USD),
            }, headers=headers), 201)
            job = _poll_job(client, job["id"])
            if job.get("status") != "candidate":
                raise RuntimeError("generation did not produce a complete candidate")
            _assert_ok(client.post(f"/api/generation/jobs/{job['id']}/commit", headers=headers))
            projection = _assert_ok(client.get(f"/api/campaigns/{campaign['id']}/projection?branch_id={campaign['branch_id']}"))
            transcript = projection.get("transcript") or []
            if len(transcript) != 1 or transcript[0].get("action_text") != ACTION:
                raise RuntimeError("committed transcript did not retain exact synthetic input")
            if NPC_ID not in json.dumps(transcript[0].get("input_segments"), ensure_ascii=False):
                raise RuntimeError("committed transcript lost synthetic NPC context")
        transport.close()
        reload_transport = CountingHttpClient(httpx.Client(timeout=5.0))
        app2 = _make_app(root, reload_transport)
        with TestClient(app2, base_url="http://127.0.0.1") as client2:
            _assert_ok(client2.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, headers=headers))
            restored = _assert_ok(client2.get(f"/api/campaigns/{campaign['id']}/projection?branch_id={campaign['branch_id']}"))
            restored_turn = (restored.get("transcript") or [None])[0]
            if not restored_turn or restored_turn.get("action_text") != ACTION or NPC_ID not in json.dumps(restored_turn.get("input_segments"), ensure_ascii=False):
                raise RuntimeError("reload verification did not recover exact input/source/NPC context")
        reload_transport.close()
        print("APP TRIAL: PASS; authenticated local app flow, one committed synthetic turn, reload persistence")
        print("PROVIDER POST COUNT:", transport.provider_posts)
        print("OUTPUT LIMIT:", MAX_OUTPUT_TOKENS, "; ESTIMATED RESERVE: bounded")
        return 0


def main() -> int:
    if os.environ.get("B4_DRY_RUN") == "1":
        assert trial_contract()["max_provider_posts"] == 1
        assert MAX_OUTPUT_TOKENS <= 640
        assert ESTIMATED_RESERVE_USD <= MAX_TRIAL_USD
        print("OFFLINE CONTRACT: PASS; zero network calls")
        return 0
    if not ensure_live_gate():
        print("DENIED: one-shot approval, first attempt, and credential are required")
        return 2
    try:
        return _run_live()
    except Exception as exc:
        print("APP TRIAL: STOPPED without retry; exception:", type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
