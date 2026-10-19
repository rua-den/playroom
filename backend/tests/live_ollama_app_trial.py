"""One-shot Ollama app trial with a fully offline contract harness."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import threading
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2 as httpx
from fastapi.testclient import TestClient

from playroom.auth import create_owner
from playroom.db import connect, migrate
from playroom.live_local import create_live_local_app
from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT, OLLAMA_FREE_CLOUD_API_MODEL, OLLAMA_FREE_CLOUD_MODEL, OllamaCloudVerifier
from playroom.provider import default_provider_factory

APPROVAL = "B4_LOCAL_APP_TRIAL_2026_10_18"
MODEL = OLLAMA_FREE_CLOUD_MODEL
MAX_OUTPUT_TOKENS = 640
MAX_TRIAL_USD = Decimal("0.01")
RESERVED_INPUT_TOKENS = 2200
ESTIMATED_RESERVE_USD = Decimal("0.000574")
OWNER_EMAIL = "synthetic-app-trial@example.test"
OWNER_PASSWORD = "synthetic app trial password"
ACTION = '*Lan mở chiếc hộp gỗ trên quầy.* "Vy, cậu có thấy tờ giấy xanh không?"'
NPC_ID = "00000000-0000-4000-8000-000000000001"
NPC_VERSION = "vy-profile-v1"
FIXTURE_KEY = "offline-fixture-key"


def trial_contract() -> dict:
    return {"max_provider_posts": 1, "max_output_tokens": MAX_OUTPUT_TOKENS, "max_usd": MAX_TRIAL_USD, "private_fixture": True, "endpoint": OLLAMA_CLOUD_ENDPOINT}


class DispatchGuard:
    def __init__(self, *, preflight=None):
        self._lock = threading.Lock()
        self.provider_posts = 0
        self.preflight = preflight

    def check(self, method: str, url: str, payload: dict | None) -> None:
        with self._lock:
            if method.upper() != "POST" or url != f"{OLLAMA_CLOUD_ENDPOINT}/chat/completions":
                raise RuntimeError("provider dispatch method or URL is not pinned")
            if not isinstance(payload, dict) or payload.get("model") != OLLAMA_FREE_CLOUD_API_MODEL:
                raise RuntimeError("provider dispatch model is not pinned")
            output_limit = payload.get("max_tokens")
            if not isinstance(output_limit, int) or output_limit <= 0 or output_limit > MAX_OUTPUT_TOKENS:
                raise RuntimeError("provider dispatch output limit exceeds trial bound")
            if self.provider_posts >= 1:
                raise RuntimeError("provider completion allows at most one POST")
            if self.preflight is not None:
                self.preflight()
                self.preflight = None
            self.provider_posts += 1


class CountingHttpClient:
    """Strict client wrapper: only one exact completion URL is dispatchable."""
    def __init__(self, client, guard: DispatchGuard | None = None):
        self.client = client
        self.guard = guard or DispatchGuard()

    @property
    def provider_posts(self):
        return self.guard.provider_posts

    def record_post(self, url: str) -> None:
        self.guard.check("POST", url, {"model": OLLAMA_FREE_CLOUD_API_MODEL, "max_tokens": MAX_OUTPUT_TOKENS})

    def get(self, *args, **kwargs):
        return self.client.get(*args, **kwargs)

    def stream(self, method, url, *args, **kwargs):
        if method.upper() == "POST":
            self.guard.check(method, str(url), kwargs.get("json"))
        return self.client.stream(method, url, *args, **kwargs)

    def close(self):
        self.client.close()


class OfflineProviderTransport:
    """Fixture-only transport that rejects every unexpected request early."""
    def __init__(self):
        self.provider_posts = 0
        self.verifier_gets = 0
        self.npc_profile_version = NPC_VERSION

    def __call__(self, request):
        url = str(request.url)
        if request.method == "GET" and url == f"{OLLAMA_CLOUD_ENDPOINT}/models":
            self.verifier_gets += 1
            return httpx.Response(200, json={"data": [{"id": OLLAMA_FREE_CLOUD_API_MODEL}]})
        if request.method == "POST" and url == f"{OLLAMA_CLOUD_ENDPOINT}/chat/completions":
            self.provider_posts += 1
            if self.provider_posts > 1:
                raise RuntimeError("fixture observed more than one completion POST")
            payload = json.dumps({"segments": [{"kind": "narration", "text": "Vy đặt tờ giấy xanh lên mặt bàn."}, {"kind": "dialogue", "text": "Có, ngay đây.", "character_id": NPC_ID, "profile_version_id": self.npc_profile_version}]}, ensure_ascii=False)
            frames = [{"choices": [{"delta": {"content": payload[:len(payload) // 2]}}]}, {"choices": [{"delta": {"content": payload[len(payload) // 2:]}}]}, {"choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 30, "completion_tokens": 28, "total_tokens": 58}}]
            body = "".join(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n" for frame in frames) + "data: [DONE]\n\n"
            return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})
        raise RuntimeError(f"offline fixture rejected unexpected {request.method} {url}")


def ensure_live_gate() -> bool:
    return os.environ.get("B4_LOCAL_APP_APPROVAL") == APPROVAL and os.environ.get("GITHUB_RUN_ATTEMPT") == "1" and bool(os.environ.get("OLLAMA_API_KEY"))


def _balance_preflight(secret: str) -> None:
    request = urllib.request.Request("https://ollama.com/api/balance", headers={"Authorization": "Bearer " + secret, "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            payload = json.load(response)
        included = Decimal(str(payload["included"]["balance_usd"]))
        purchased = Decimal(str(payload["purchased"]["balance_usd"]))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, TypeError, ValueError, InvalidOperation):
        raise RuntimeError("balance preflight unavailable; no provider POST") from None
    if not included.is_finite() or not purchased.is_finite() or included < MAX_TRIAL_USD or purchased != 0:
        raise RuntimeError("balance preflight did not establish included allowance and zero purchased credits")


def _assert_ok(response, expected: int | set[int] = 200) -> dict:
    statuses = {expected} if isinstance(expected, int) else expected
    if response.status_code not in statuses:
        raise RuntimeError(f"API step failed with status {response.status_code}")
    return response.json()


def _create_app(root: Path, *, transport: OfflineProviderTransport | None = None, live: bool = False, guard: DispatchGuard | None = None):
    frontend = root / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<html>synthetic</html>", encoding="utf-8")
    app = create_live_local_app(root / "data", frontend_dist=frontend)
    counted = None
    if transport is not None or live:
        shared = httpx.Client(transport=httpx.MockTransport(transport), timeout=30) if transport is not None else httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0))
        app.router.add_event_handler("shutdown", shared.close)
        app.state.provider_verifier = OllamaCloudVerifier(http_client=shared)
        # The production route constructs its pinned Ollama verifier directly;
        # inject the fixture client at the harness boundary without changing
        # application code or permitting a real network call.
        import playroom.api.configuration as configuration_api
        if transport is not None:
            configuration_api.OllamaCloudVerifier = lambda: OllamaCloudVerifier(http_client=shared)
        counted = CountingHttpClient(shared, guard or DispatchGuard())

        def factory(*, owner_id, stage, profile, credential, http_client=None):
            if stage != "narration":
                raise RuntimeError("offline trial permits narration only")
            return default_provider_factory(owner_id=owner_id, stage=stage, profile=profile, credential=credential, http_client=counted)

        app.state.generation_provider_factory = factory
        app.state._trial_http_client = counted
    return app


def _create_owner(root: Path) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    connection = connect(root / "data" / "playroom.sqlite3")
    try:
        migrate(connection)
        create_owner(connection, OWNER_EMAIL, OWNER_PASSWORD)
    finally:
        connection.close()


def _poll_job(client: TestClient, job_id: str, *, timeout: float = 120.0, interval: float = 0.05) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = _assert_ok(client.get(f"/api/generation/jobs/{job_id}"))
        if job.get("status") in {"candidate", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(interval)
    raise RuntimeError("generation job polling exceeded bounded timeout")


def _run_app_flow_impl(*, offline: bool) -> tuple[int, int]:
    transport = OfflineProviderTransport() if offline else None
    secret = os.environ.get("OLLAMA_API_KEY", "")
    guard = DispatchGuard(preflight=None if offline else lambda: _balance_preflight(secret))
    with tempfile.TemporaryDirectory(prefix="playroom-app-trial-") as directory:
        root = Path(directory)
        _create_owner(root)
        app = _create_app(root, transport=transport, live=not offline, guard=guard)
        counted = getattr(app.state, "_trial_http_client", None)
        headers = {"origin": "http://127.0.0.1"}
        with TestClient(app, base_url="http://127.0.0.1") as client:
            _assert_ok(client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, headers=headers))
            campaign = _assert_ok(client.post("/api/campaigns", json={"title": "Synthetic Ollama app trial", "world": {"name": "Quiet library", "public_canon": "A blue paper is waiting."}, "characters": [{"id": NPC_ID, "name": "Vy", "profile_version_id": NPC_VERSION, "present": True}], "persona": {"name": "Lan", "player_controlled": True}}, headers=headers), 201)
            credential = _assert_ok(client.post("/api/provider/credentials", json={"secret": FIXTURE_KEY if offline else os.environ["OLLAMA_API_KEY"]}, headers=headers), 201)
            profile = _assert_ok(client.post("/api/provider/profiles/verify", json={"provider": "ollama", "credential_id": credential["id"], "model": MODEL, "endpoint": OLLAMA_CLOUD_ENDPOINT}, headers=headers), 201)
            if profile.get("model") != OLLAMA_FREE_CLOUD_API_MODEL or profile.get("free_starter_eligible") is not True:
                raise RuntimeError("verified Ollama profile was unavailable or not starter eligible")
            settings = _assert_ok(client.put("/api/provider/settings", json={"narrator_profile_id": profile["id"], "mode": "economy", "policy": "capped_paid", "confirmed_usd_cap": str(MAX_TRIAL_USD), "budgets": {"narrator": {"input_limit": RESERVED_INPUT_TOKENS, "requested_output": MAX_OUTPUT_TOKENS, "wrapper_buffer": 64}}}, headers=headers))
            if settings.get("roles", {}).get("narrator", {}).get("version") != profile.get("version"):
                raise RuntimeError("immutable narrator profile binding was not persisted")
            expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            _assert_ok(client.post("/api/provider/trials", json={"profile_id": profile["id"], "profile_version": profile["version"], "total_cap_usd": str(MAX_TRIAL_USD), "per_send_cap_usd": str(MAX_TRIAL_USD), "max_jobs": 1, "expires_at": expires}, headers=headers), 201)
            detail = _assert_ok(client.get(f"/api/campaigns/{campaign['id']}"))
            preview = _assert_ok(client.post(f"/api/campaigns/{campaign['id']}/context/previews", json={"branch_id": campaign["branch_id"], "action": ACTION, "profile_id": profile["id"]}, headers=headers), 201)
            if preview.get("status") != "ready" or preview.get("budget", {}).get("fits") is not True:
                raise RuntimeError("verified context preview did not fit the bounded input/output wire budget")
            selected = preview.get("selected_characters") or []
            npc = next((item for item in selected if item.get("character_id") == NPC_ID), None)
            if npc is None or not npc.get("profile_version_id"):
                raise RuntimeError("context preview did not expose the persisted NPC profile version")
            expected_npc_version = npc["profile_version_id"]
            if transport is not None:
                transport.npc_profile_version = expected_npc_version
            job = _assert_ok(client.post(f"/api/campaigns/{campaign['id']}/generate", json={"branch_id": campaign["branch_id"], "action": ACTION, "idempotency_key": "synthetic-app-trial-once", "checkpoint_id": detail["checkpoint_id"], "preview_id": preview["id"], "mode": "economy", "policy": "capped_paid", "cap": str(MAX_TRIAL_USD)}, headers=headers), 201)
            job = _poll_job(client, job["id"])
            if job.get("status") != "candidate":
                raise RuntimeError(f"generation stopped before candidate: {job.get('failure', {}).get('code', 'unknown')}")
            output = job.get("output_segments") or []
            if not any(segment.get("character_id") == NPC_ID and segment.get("profile_version_id") == expected_npc_version for segment in output):
                raise RuntimeError("candidate output lost persisted NPC profile attribution")
            _assert_ok(client.post(f"/api/generation/jobs/{job['id']}/commit", headers=headers))
            projection = _assert_ok(client.get(f"/api/campaigns/{campaign['id']}/projection?branch_id={campaign['branch_id']}"))
            transcript = projection.get("transcript") or []
            if len(transcript) != 1 or transcript[0].get("action_text") != ACTION or not any(segment.get("character_id") == NPC_ID and segment.get("profile_version_id") == expected_npc_version for segment in transcript[0].get("output_segments") or []):
                raise RuntimeError("committed projection did not retain exact input and NPC output attribution")
        reload_transport = OfflineProviderTransport() if offline else None
        app2 = _create_app(root, transport=reload_transport, live=not offline, guard=guard)
        with TestClient(app2, base_url="http://127.0.0.1") as client2:
            _assert_ok(client2.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}, headers=headers))
            restored = _assert_ok(client2.get(f"/api/campaigns/{campaign['id']}/projection?branch_id={campaign['branch_id']}"))
            restored_turn = (restored.get("transcript") or [None])[0]
            if not restored_turn or restored_turn.get("action_text") != ACTION or not any(segment.get("character_id") == NPC_ID and segment.get("profile_version_id") == expected_npc_version for segment in restored_turn.get("output_segments") or []):
                raise RuntimeError("reload verification did not recover persisted NPC output attribution")
        if guard.provider_posts != 1:
            raise RuntimeError(f"expected exactly one total provider POST, observed {guard.provider_posts}")
        return guard.provider_posts, (transport.verifier_gets if transport else 0)


def _run_app_flow(*, offline: bool) -> tuple[int, int]:
    """Run a flow and always restore the offline-only verifier injection."""
    import playroom.api.configuration as configuration_api
    original = configuration_api.OllamaCloudVerifier
    try:
        return _run_app_flow_impl(offline=offline)
    finally:
        configuration_api.OllamaCloudVerifier = original


def _run_live() -> int:
    posts, _ = _run_app_flow(offline=False)
    if posts != 1:
        raise RuntimeError(f"expected one provider completion POST, observed {posts}")
    print("APP TRIAL: PASS; authenticated local app flow, one committed synthetic turn, reload persistence")
    print("PROVIDER POST COUNT:", posts)
    print("OUTPUT LIMIT:", MAX_OUTPUT_TOKENS, "; ESTIMATED RESERVE: bounded")
    return 0


def main() -> int:
    if os.environ.get("B4_DRY_RUN") == "1":
        assert trial_contract()["max_provider_posts"] == 1
        assert MAX_OUTPUT_TOKENS <= 640
        assert ESTIMATED_RESERVE_USD <= MAX_TRIAL_USD
        print("OFFLINE CONTRACT: PASS; zero network calls")
        return 0
    if os.environ.get("B4_OFFLINE_FIXTURE") == "1":
        posts, verifier_gets = _run_app_flow(offline=True)
        if posts != 1 or verifier_gets != 1:
            raise RuntimeError(f"offline fixture dispatch counts invalid: posts={posts}, verifier_gets={verifier_gets}")
        print("OFFLINE APP FLOW: PASS; verifier, credential, preview, one completion, commit, reload")
        print("PROVIDER POST COUNT:", posts)
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
