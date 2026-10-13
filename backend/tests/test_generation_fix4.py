from __future__ import annotations

import json
import threading
from decimal import Decimal

import httpx2 as httpx
import pytest

from playroom.attempt_runtime import PhysicalAttemptRegistry
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.context import build_candidate_pool
from playroom.credentials import CredentialStore
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.generation import DEFAULT_PROFILE, GenerationService, _ProviderError
from playroom.memory import append_memory_version
from playroom.model_profiles import persist_model_profile
from playroom.provider import FakeProvider, OpenRouterAdapter, ProviderAdapter, ProviderFailure, ProviderResult
from playroom.wire_cost import canonical_json, declared_count, wire_hash
from playroom.settings import get_owner_settings, save_owner_settings
from playroom.timeline import get_branch_head


def _story(tmp_path):
    db = connect(tmp_path / "fix4.sqlite3")
    migrate(db)
    owner = create_owner(db, "fix4@example.test", "fix4 password")
    campaign = create_campaign(db, owner.id, "Fix4", {"name": "World"}, [], {"name": "Player"})
    return db, owner, campaign


def test_role_budgets_are_immutable_settings_and_validate_against_profile(tmp_path):
    db, owner, _ = _story(tmp_path)
    saved = save_owner_settings(
        db,
        owner.id,
        {
            "roles": {"narrator": {"id": "synthetic", "version": 1}},
            "mode": "economy",
            "policy": "free_only",
            "budgets": {"narrator": {"input_limit": 321, "requested_output": 123, "wrapper_buffer": 17}},
        },
    )
    assert saved["budgets"]["narrator"] == {"input_limit": 321, "requested_output": 123, "wrapper_buffer": 17}
    loaded = get_owner_settings(db, owner.id)
    assert loaded["budgets"] == saved["budgets"]
    assert loaded["settings_revision"] == saved["settings_revision"]


def test_registry_post_slot_gate_blocks_stale_waiter_before_factory_and_provider():
    registry = PhysicalAttemptRegistry(limit=1)
    blocker = threading.Event()
    blocker_started = threading.Event()
    calls = []

    class Blocking(ProviderAdapter):
        def capabilities_for(self, profile):
            return None

        def generate_structured(self, request, schema):
            blocker_started.set()
            blocker.wait(2)
            return ProviderResult(text="{}")

    active = Blocking()
    threading.Thread(target=lambda: registry.structured("active:context", active, {}, {}, 2), daemon=True).start()
    assert blocker_started.wait(1)
    result = {}

    def waiter():
        result["value"] = registry.structured(
            "stale:context",
            None,
            {},
            {},
            2,
            provider_factory=lambda _handle: calls.append("factory") or Blocking(),
            invocation_gate=lambda _handle: False,
        )

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    assert registry.wait_registered("stale:context", 1)
    blocker.set()
    thread.join(2)
    assert not thread.is_alive()
    assert isinstance(result["value"], ProviderFailure)
    assert result["value"].code == "CANCELLED"
    assert calls == []


def test_stream_gate_is_checked_before_lazy_iterator_opens_provider():
    registry = PhysicalAttemptRegistry(limit=1)
    opened = []
    gate_results = iter([True, True, False])

    class Lazy(ProviderAdapter):
        def capabilities_for(self, profile):
            return None

        def generate_text(self, request):
            opened.append(True)
            yield ProviderResult(text="done")

    stream = registry.stream(
        "lazy:narration",
        Lazy(),
        {},
        1,
        pre_invocation_gate=lambda _handle: next(gate_results),
        invocation_gate=lambda _handle: next(gate_results),
    )
    assert next(stream).code == "CANCELLED"
    assert opened == []


def test_openrouter_stream_checks_cancel_before_mocked_client_stream():
    class Client:
        def __init__(self):
            self.calls = 0

        def stream(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("cancelled request opened the provider stream")

    client = Client()
    adapter = OpenRouterAdapter(
        "dummy-key",
        "https://openrouter.test/chat/completions",
        profile={
            "id": "stream-profile",
            "version": 1,
            "profile_hash": "stream-hash",
            "provider_tag": "provider-a",
            "model": "author/model",
            "output_limit": 4000,
            "supported_parameters": ["max_tokens"],
            "output_parameter": "max_tokens",
        },
        http_client=client,
    )
    request = {"stage": "narration", "messages": [], "reserved_completion_tokens": 1}
    request["cancel_event"] = threading.Event()
    request["cancel_event"].set()
    iterator = adapter.generate_text(request)
    with pytest.raises(StopIteration):
        next(iterator)
    assert client.calls == 0


def test_shared_actor_profile_survives_first_memory_drop_when_second_is_retained(tmp_path):
    db = connect(tmp_path / "shared-actor.sqlite3")
    migrate(db)
    owner = create_owner(db, "shared-actor@example.test", "shared actor password")
    character_id = "3c8b6d24-e4d5-4f4b-a11a-4d98407d6e80"
    campaign = create_campaign(db, owner.id, "Shared actor", {"name": "World"}, [{"id": character_id, "name": "Mila"}], {"name": "Player"})
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    first = append_memory_version(db, campaign.id, campaign.initial_branch_id, "lore", "very long " * 10000, origin="user", expected_state_version=head.state_version, source_revision_ids=[], entity_ids=[character_id], status="approved")
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    second = append_memory_version(db, campaign.id, campaign.initial_branch_id, "lore", "short retained memory", origin="user", expected_state_version=head.state_version, source_revision_ids=[], entity_ids=[character_id], status="approved")
    service = GenerationService(db, FakeProvider([]))
    preview = {
        "campaign_id": campaign.id,
        "branch_id": campaign.initial_branch_id,
        "checkpoint_id": get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id,
        "action": "Continue",
        "blocks": [{"id": "action", "type": "action", "text": "Continue", "source_ids": [], "mandatory": True}],
        "omission_reasons": [],
    }
    def as_item(memory):
        return {"id": memory.memory_id, "version_id": memory.version_id, "text": memory.text, "source_revision_ids": [], "entity_ids": list(memory.entity_ids), "known_by": list(memory.known_by), "effective_cursor": {"state_version": memory.state_version, "checkpoint_id": memory.checkpoint_id}}
    plan = {
        "selected_memory_ids": [first.memory_id, second.memory_id],
        "reasons": {first.memory_id: "first", second.memory_id: "second"},
        "optional": [as_item(first), as_item(second)],
    }
    packed = service._pack_selected(preview, plan, DEFAULT_PROFILE, director_selected_only=True)
    packed, _, _ = service._narrator_request({}, DEFAULT_PROFILE, packed, {"budgets": {"narrator": {"input_limit": 12000, "requested_output": 4000, "wrapper_buffer": 512}}})
    memory_ids = [block["id"] for block in packed["blocks"] if block.get("type") == "memory"]
    actor_blocks = [block for block in packed["blocks"] if block.get("type") == "character"]
    assert second.memory_id in memory_ids
    assert first.memory_id not in memory_ids
    assert actor_blocks and character_id in {block.get("actor_id") for block in actor_blocks}


def test_director_omission_reasons_are_counted_in_final_wire_trim(tmp_path):
    db, owner, campaign = _story(tmp_path)
    service = GenerationService(db, FakeProvider([]), profile={"roles": {"context": DEFAULT_PROFILE, "narrator": DEFAULT_PROFILE}})
    pool = {
        "checkpoint_id": "checkpoint",
        "action_hash": "action-hash",
        "mandatory": [],
        "scene_ids": [],
        "omission_reasons": [],
        "recent_context": [],
        "optional": [{"id": f"memory-{index}", "text": "x" * 500, "source_ids": [f"source-{index}"]} for index in range(4)],
    }
    request, metadata, omissions, _ = service._director_request(
        {"action": "Continue"},
        pool,
        DEFAULT_PROFILE,
        {"budgets": {"context": {"input_limit": 900, "requested_output": 10, "wrapper_buffer": 0}}},
    )
    assert omissions
    assert metadata["fits"] is True
    assert metadata["input_tokens"] <= metadata["input_cap"]
    assert request["prepared_wire"]["messages"][1]["content"].find("omission_reasons") >= 0


def test_quality_uses_actual_persisted_wire_and_cost_ledger(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    plan = {"checkpoint_id": head.checkpoint_id, "action_hash": "", "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": [], "conflict_flags": []}
    profile = {
        **DEFAULT_PROFILE,
        "id": "paid-test",
        "credential_tier": "paid",
        "is_test_profile": False,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "input_limit": 12000,
        "context_limit": 16512,
        "output_limit": 4000,
    }

    class UsageProvider(FakeProvider):
        def generate_structured(self, request, schema):
            plan["action_hash"] = request["action_hash"]
            return ProviderResult(text=json.dumps(plan), usage={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18})

        def generate_text(self, request):
            self.calls.append({key: value for key, value in request.items() if key != "cancel_event"})
            yield "Narrative"
            yield ProviderResult(text="Narrative", usage={"input_tokens": 13, "output_tokens": 5, "total_tokens": 18})

    provider = UsageProvider([])
    service = GenerationService(
        db,
        provider,
        profile={"roles": {"context": profile, "narrator": profile}},
    )
    # The implementation must reject a paid path without an explicit cap and
    # retain the immutable role-specific ledger when a cap is supplied.
    with pytest.raises(ValidationError):
        service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="ledger-free", expected_checkpoint_id=head.checkpoint_id, mode="quality", policy="capped_paid")
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="ledger-paid", expected_checkpoint_id=head.checkpoint_id, mode="quality", policy="capped_paid", cap="1")
    assert job["status"] == "candidate"
    ledger = job["cost_ledger"]
    assert ledger["stages"]["context"]["actual_status"] == "calculated"
    assert ledger["stages"]["narration"]["actual_status"] == "calculated"
    assert ledger["stages"]["context"]["calculated_cost_usd"]
    assert ledger["stages"]["narration"]["calculated_cost_usd"]
    assert ledger["stages"]["context"]["provider_reported_cost_usd"] is None
    assert Decimal(ledger["calculated_total_usd"]) > 0
    run = db.execute("SELECT token_budget_json, request_json, wire_json, payload_hash, counter_id, counter_mode FROM context_runs").fetchone()
    request_snapshot = json.loads(run["request_json"])
    wire_snapshot = json.loads(run["wire_json"])
    emitted = provider.calls[-1]
    assert emitted["messages"] == wire_snapshot["narrator"]["messages"]
    assert emitted["prepared_wire"] == wire_snapshot["narrator"]
    assert emitted["wire_metadata"]["payload_hash"] == run["payload_hash"]
    assert emitted["wire_metadata"]["input_tokens"] == json.loads(run["token_budget_json"])["narrator"]["input_tokens"]
    assert request_snapshot["narrator"] == emitted["prepared_wire"]


@pytest.mark.parametrize(
    ("mode", "context_version", "narrator_version", "expected_stages"),
    [("economy", 1, 2, ["narration"]), ("quality", 1, 2, ["context", "narration"]), ("quality", 2, 1, ["context", "narration"])],
)
def test_same_profile_id_keeps_role_version_identity(mode, context_version, narrator_version, expected_stages, tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    base = {**DEFAULT_PROFILE, "id": "shared-role", "is_test_profile": False}
    persisted = {
        version: persist_model_profile(db, owner.id, {**base, "model": f"author/shared-v{version}"})
        for version in (1, 2)
    }
    context = persisted[context_version]
    narrator = persisted[narrator_version]
    save_owner_settings(
        db,
        owner.id,
        {
            "roles": {
                "context": {"id": context["id"], "version": context["version"], "profile_hash": context["profile_hash"]},
                "narrator": {"id": narrator["id"], "version": narrator["version"], "profile_hash": narrator["profile_hash"]},
            },
            "mode": mode,
            "policy": "free_only",
        },
    )
    calls = []

    class RoleProvider(FakeProvider):
        def generate_structured(self, request, schema):
            pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
            plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": request["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
            return ProviderResult(text=json.dumps(plan), usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

        def generate_text(self, request):
            yield ProviderResult(text="role identity narrative", usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    def factory(**kwargs):
        calls.append((kwargs["stage"], kwargs["profile"]["id"], kwargs["profile"]["version"], kwargs["profile"]["profile_hash"]))
        return RoleProvider([])

    service = GenerationService(
        db, FakeProvider([]),
        provider_factory=factory, credential_resolver=lambda owner_id, version: "role-secret",
    )
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key=f"role-{mode}-{context_version}-{narrator_version}", expected_checkpoint_id=head.checkpoint_id, mode=mode)
    assert job["status"] == "candidate"
    assert [stage for stage, *_ in calls] == expected_stages
    expected_versions = {"context": context_version, "narration": narrator_version}
    assert calls == [
        (stage, "shared-role", expected_versions[stage], persisted[expected_versions[stage]]["profile_hash"])
        for stage in expected_stages
    ]
    run = db.execute("SELECT token_budget_json FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()
    snapshot = json.loads(run["token_budget_json"])["profile_snapshot"]
    assert snapshot["context"]["id"] == "shared-role"
    assert snapshot["context"]["version"] == context_version
    assert snapshot["context"]["profile_hash"] == persisted[context_version]["profile_hash"]
    assert snapshot["narrator"]["id"] == "shared-role"
    assert snapshot["narrator"]["version"] == narrator_version
    assert snapshot["narrator"]["profile_hash"] == persisted[narrator_version]["profile_hash"]


def test_openrouter_adapter_wire_matches_persisted_quality_attempts(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {
        **DEFAULT_PROFILE,
        "id": "wire-profile", "provider": "openrouter", "endpoint": "https://wire.test/chat",
        "model": "author/wire", "provider_tag": "exact", "supported_parameters": ["max_tokens", "response_format"],
        "native_structured_output": True, "structured_output": True, "structured_schema_parameter": "response_format",
        "output_parameter": "max_tokens", "is_test_profile": False,
    }
    captured = []

    def route(request):
        payload = json.loads(request.content)
        captured.append(payload)
        if "response_format" in payload:
            wire = json.loads(payload["messages"][1]["content"])
            body_value = {
                "checkpoint_id": wire["checkpoint_id"], "action_hash": wire["action_hash"],
                "selected_memory_ids": [], "reasons": {}, "reason_sources": {},
                "scene_ids": wire["candidate_pool"]["scene_ids"], "conflict_flags": [],
            }
            content = json.dumps(body_value, separators=(",", ":"))
        else:
            content = "wire narrative"
        body = b"data: " + json.dumps({"choices": [{"delta": {"content": content}}]}).encode() + b"\n\n"
        body += b'data: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}}\n\n'
        body += b"data: [DONE]\n\n"
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    adapter = OpenRouterAdapter("dummy-key", profile["endpoint"], profile=profile, http_client=httpx.Client(transport=httpx.MockTransport(route)))
    service = GenerationService(db, adapter, profile={"roles": {"context": profile, "narrator": profile}})
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="adapter-wire", expected_checkpoint_id=head.checkpoint_id, mode="quality")
    assert job["status"] == "candidate"
    assert len(captured) == 2
    attempts = db.execute("SELECT stage,payload_hash,request_json FROM provider_attempts WHERE generation_job_id=? ORDER BY stage", (job["id"],)).fetchall()
    run = db.execute("SELECT wire_json,token_budget_json,payload_hash FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()
    wires = json.loads(run["wire_json"])
    budgets = json.loads(run["token_budget_json"])
    for attempt, payload in zip(attempts, captured):
        stage = attempt["stage"]
        wire_key = "director" if stage == "context" else "narrator"
        assert payload == wires[wire_key]
        assert attempt["payload_hash"] == wire_hash(payload)
        assert declared_count(canonical_json(payload)) == budgets[wire_key]["input_tokens"]
    assert wire_hash(captured[-1]) == run["payload_hash"]


def test_queued_job_keeps_profile_and_wire_snapshot_after_settings_change(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile_v1 = persist_model_profile(db, owner.id, {
        **DEFAULT_PROFILE, "id": "queued-role", "provider": "openrouter",
        "endpoint": "https://queued.test/chat", "model": "author/queued-v1",
        "provider_tag": "exact", "supported_parameters": ["max_tokens"], "output_parameter": "max_tokens",
        "is_test_profile": False,
    })
    profile_v2 = persist_model_profile(db, owner.id, {**profile_v1, "model": "author/queued-v2"})
    settings_v1 = save_owner_settings(db, owner.id, {
        "roles": {"narrator": {"id": profile_v1["id"], "version": profile_v1["version"], "profile_hash": profile_v1["profile_hash"]}},
        "mode": "economy", "policy": "free_only",
        "budgets": {"narrator": {"input_limit": 1000, "requested_output": 50}},
    })
    seen = []
    captured = []

    def route(request):
        payload = json.loads(request.content)
        captured.append(payload)
        body = b'data: {"choices":[{"delta":{"content":"queued narrative"}}]}\n\ndata: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    adapter = OpenRouterAdapter(profile_v1["secret_version"], profile_v1["endpoint"], profile=profile_v1, http_client=httpx.Client(transport=httpx.MockTransport(route)))

    def factory(**kwargs):
        seen.append((kwargs["stage"], kwargs["profile"]["version"], kwargs["profile"]["profile_hash"]))
        return adapter

    service = GenerationService(db, adapter, profile=profile_v1, provider_factory=factory, credential_resolver=lambda owner_id, version: "queued-secret")
    queued = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="queued-settings", expected_checkpoint_id=head.checkpoint_id, execute=False)
    queued_attempt = db.execute("SELECT profile_snapshot_json,request_json FROM provider_attempts WHERE generation_job_id=? AND stage='narration'", (queued["id"],)).fetchone()
    settings_v2 = save_owner_settings(db, owner.id, {
        "roles": {"narrator": {"id": profile_v2["id"], "version": profile_v2["version"], "profile_hash": profile_v2["profile_hash"]}},
        "mode": "economy", "policy": "free_only",
        "budgets": {"narrator": {"input_limit": 2000, "requested_output": 100}},
    })
    assert settings_v2["settings_revision"] > settings_v1["settings_revision"]
    finished = service.run(queued["id"])
    assert finished["status"] == "candidate"
    assert profile_v1["profile_hash"] != profile_v2["profile_hash"]
    assert seen == [("narration", 1, profile_v1["profile_hash"])]
    assert len(captured) == 1
    assert captured[0]["model"] == "author/queued-v1"
    assert captured[0]["max_tokens"] == 50
    final_attempt = db.execute("SELECT profile_snapshot_json FROM provider_attempts WHERE generation_job_id=? AND stage='narration'", (queued["id"],)).fetchone()
    job_snapshot = db.execute("SELECT settings_snapshot_json FROM generation_jobs WHERE id=?", (queued["id"],)).fetchone()
    assert json.loads(job_snapshot["settings_snapshot_json"])["settings_revision"] == settings_v1["settings_revision"]
    run = db.execute("SELECT wire_json,token_budget_json,payload_hash FROM context_runs WHERE generation_job_id=?", (queued["id"],)).fetchone()
    wire = json.loads(run["wire_json"])["narrator"]
    budget = json.loads(run["token_budget_json"])["narrator"]
    assert captured[0] == wire
    assert captured[0]["messages"] == wire["messages"]
    assert captured[0]["max_tokens"] == budget["output_reserve"]
    assert budget["output_reserve"] == 50
    assert wire_hash(captured[0]) == run["payload_hash"]
    assert json.loads(queued_attempt["profile_snapshot_json"])["version"] == 1
    assert json.loads(final_attempt["profile_snapshot_json"])["version"] == 1


def test_revoked_pinned_credential_opens_zero_http_streams(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    store = CredentialStore(tmp_path / "secrets")
    credential = store.put(owner.id, "dummy-provider-secret")
    profile = {
        **DEFAULT_PROFILE, "id": "revoked-wire", "provider": "openrouter", "endpoint": "https://wire.test/chat",
        "model": "author/wire", "provider_tag": "exact", "supported_parameters": ["max_tokens"],
        "output_parameter": "max_tokens", "is_test_profile": False, "secret_version": credential.id,
    }
    store.revoke(owner.id, credential.id)
    streams = []

    def route(request):
        streams.append(request)
        return httpx.Response(200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    adapter = OpenRouterAdapter("dummy-key", profile["endpoint"], profile=profile, http_client=httpx.Client(transport=httpx.MockTransport(route)))
    service = GenerationService(
        db, adapter, profile=profile, provider_factory=lambda **kwargs: adapter,
        credential_resolver=store.get,
    )
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="revoked-wire", expected_checkpoint_id=head.checkpoint_id)
    assert job["status"] == "failed"
    assert job["failure"]["code"] == "CREDENTIAL_UNAVAILABLE"
    assert streams == []


def test_required_narrator_wire_overflow_preflights_before_director(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {
        **DEFAULT_PROFILE,
        "input_limit": 260,
        "context_limit": 1024,
        "output_limit": 64,
    }

    class CountingProvider(FakeProvider):
        def __init__(self):
            super().__init__([])
            self.director_calls = 0

        def generate_structured(self, request, schema):
            self.director_calls += 1
            raise AssertionError("director must not run when required narrator wire overflows")

    provider = CountingProvider()
    service = GenerationService(db, provider, profile={"roles": {"context": {**profile, "input_limit": 4096, "context_limit": 8192}, "narrator": profile}})

    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="required-overflow-preflight", expected_checkpoint_id=head.checkpoint_id, mode="quality", execute=False)
    result = service.run(job["id"])

    assert result["status"] == "failed"
    assert provider.director_calls == 0
    assert db.execute("SELECT status FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()[0] == "interrupted"
    assert db.execute("SELECT COUNT(*) FROM generation_branch_guards WHERE generation_job_id=?", (job["id"],)).fetchone()[0] == 0


def test_context_run_insert_rolls_back_when_final_context_cas_loses(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    service = GenerationService(db, FakeProvider([]))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="context-cas-rollback", expected_checkpoint_id=head.checkpoint_id, execute=False)
    preview = json.loads(job["preview_snapshot_json"])
    db.execute("UPDATE generation_jobs SET status='running',cancel_requested=1 WHERE id=?", (job["id"],))

    with pytest.raises(_ProviderError, match="Generation was cancelled"):
        service._save_context_run(job, preview)

    assert db.execute("SELECT COUNT(*) FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()[0] == 0


def test_post_director_pack_failure_terminalizes_attempt_and_usage(tmp_path, monkeypatch):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
    plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
    director_text = json.dumps({**plan, "action_hash": pool["action_hash"]})

    class DirectorOnly(FakeProvider):
        def generate_structured(self, request, schema):
            return ProviderResult(text=director_text, usage={"input_tokens": 17, "output_tokens": 5, "total_tokens": 22})

    provider = DirectorOnly([])
    service = GenerationService(db, provider, profile={"roles": {"context": DEFAULT_PROFILE, "narrator": DEFAULT_PROFILE}})
    monkeypatch.setattr(service, "_pack_selected", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced pack failure")))
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="post-director-pack-failure", expected_checkpoint_id=head.checkpoint_id, mode="quality")

    assert job["status"] == "failed"
    attempt = db.execute("SELECT status,output_text,usage_json FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()
    assert attempt["status"] == "failed"
    assert attempt["output_text"] == director_text
    assert json.loads(attempt["usage_json"])["total_tokens"] == 22
    assert provider.stage_counts.get("narration", 0) == 0
    assert db.execute("SELECT COUNT(*) FROM provider_attempts WHERE status='dispatched'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM generation_branch_guards WHERE generation_job_id=?", (job["id"],)).fetchone()[0] == 0


@pytest.mark.parametrize("transition", ["recover", "cancel"])
@pytest.mark.parametrize("packing_error", [False, True])
def test_old_director_result_cannot_write_after_transition(tmp_path, monkeypatch, transition, packing_error):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(
        db, campaign.id, campaign.initial_branch_id, "Look",
        checkpoint_id=head.checkpoint_id, owner_id=owner.id,
    )
    selection = {
        "checkpoint_id": head.checkpoint_id,
        "action_hash": pool["action_hash"],
        "selected_memory_ids": [], "reasons": {}, "reason_sources": {},
        "scene_ids": pool["scene_ids"], "conflict_flags": [],
    }
    provider = FakeProvider([json.dumps(selection), "must not narrate"])
    service = GenerationService(db, provider)
    job = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Look",
        idempotency_key="old-writer", expected_checkpoint_id=head.checkpoint_id,
        mode="quality", execute=False,
    )
    entered = threading.Event()
    release = threading.Event()
    original = service._pack_selected

    def held_pack(*args, **kwargs):
        entered.set()
        assert release.wait(5), "post-result test barrier timed out"
        if packing_error:
            raise RuntimeError("synthetic packing failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_pack_selected", held_pack)
    worker = threading.Thread(target=lambda: service.run(job["id"]), daemon=True)
    db_path = db.execute("PRAGMA database_list").fetchone()[2]
    other = connect(db_path)
    try:
        worker.start()
        assert entered.wait(3)
        competing = GenerationService(other, FakeProvider([]))
        epoch_before = db.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()[0]
        if transition == "recover":
            competing.recover_after_restart()
            assert db.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()[0] != epoch_before
            assert db.execute("SELECT status FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()[0] == "interrupted"
        else:
            competing.cancel(owner.id, job["id"])
            cancel_state = db.execute("SELECT cancel_requested,status FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()
            assert cancel_state["cancel_requested"] == 1
            assert cancel_state["status"] in {"cancelling", "cancelled"}
        before = {
            "reserved": db.execute("SELECT reserved_cost_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0],
            "context": db.execute("SELECT final_context_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0],
            "events": db.execute("SELECT COUNT(*) FROM generation_events WHERE generation_job_id=?", (job["id"],)).fetchone()[0],
            "runs": db.execute("SELECT COUNT(*) FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()[0],
            "attempt": tuple(db.execute("SELECT output_text,usage_json FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()),
        }
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert db.execute("SELECT reserved_cost_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == before["reserved"]
        assert db.execute("SELECT final_context_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == before["context"]
        events_after = db.execute("SELECT event_type,payload_json FROM generation_events WHERE generation_job_id=? ORDER BY id", (job["id"],)).fetchall()
        late_events = [row[0] for row in events_after[before["events"]:]]
        assert not ({"context_completed", "completed", "candidate", "success"} & set(late_events))
        assert not any(
            row[0] == "phase_changed" and json.loads(row[1]).get("phase") == "context_completed"
            for row in events_after[before["events"]:]
        )
        if transition == "recover":
            assert late_events == []
        assert db.execute("SELECT COUNT(*) FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()[0] == before["runs"]
        assert tuple(db.execute("SELECT output_text,usage_json FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()) == before["attempt"]
        assert provider.stage_counts.get("narration", 0) == 0
    finally:
        release.set()
        worker.join(3)
        other.close()


def test_old_director_result_cannot_write_after_status_transition(tmp_path, monkeypatch):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(
        db, campaign.id, campaign.initial_branch_id, "Look",
        checkpoint_id=head.checkpoint_id, owner_id=owner.id,
    )
    selection = {
        "checkpoint_id": head.checkpoint_id,
        "action_hash": pool["action_hash"],
        "selected_memory_ids": [], "reasons": {}, "reason_sources": {},
        "scene_ids": pool["scene_ids"], "conflict_flags": [],
    }
    provider = FakeProvider([json.dumps(selection), "must not narrate"])
    service = GenerationService(db, provider)
    job = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Look",
        idempotency_key="old-writer-status", expected_checkpoint_id=head.checkpoint_id,
        mode="quality", execute=False,
    )
    entered = threading.Event()
    release = threading.Event()

    def held_pack(*args, **kwargs):
        entered.set()
        assert release.wait(5), "post-result status test barrier timed out"
        raise RuntimeError("synthetic status-transition packing failure")

    monkeypatch.setattr(service, "_pack_selected", held_pack)
    worker = threading.Thread(target=lambda: service.run(job["id"]), daemon=True)
    db_path = db.execute("PRAGMA database_list").fetchone()[2]
    other = connect(db_path)
    try:
        worker.start()
        assert entered.wait(3)
        before = {
            "epoch": db.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()[0],
            "cancel": db.execute("SELECT cancel_requested FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0],
            "reserved": db.execute("SELECT reserved_cost_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0],
            "context": db.execute("SELECT final_context_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0],
            "runs": db.execute("SELECT COUNT(*) FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()[0],
            "attempt": tuple(db.execute("SELECT output_text,usage_json FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()),
            "events": db.execute("SELECT COUNT(*) FROM generation_events WHERE generation_job_id=?", (job["id"],)).fetchone()[0],
        }
        updated = other.execute("UPDATE generation_jobs SET status='failed' WHERE id=? AND status='running'", (job["id"],))
        other.commit()
        assert updated.rowcount == 1
        state = db.execute("SELECT status,cancel_requested FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()
        assert state["status"] == "failed"
        assert state["cancel_requested"] == before["cancel"] == 0
        assert db.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()[0] == before["epoch"]
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert db.execute("SELECT reserved_cost_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == before["reserved"]
        assert db.execute("SELECT final_context_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == before["context"]
        assert db.execute("SELECT COUNT(*) FROM context_runs WHERE generation_job_id=?", (job["id"],)).fetchone()[0] == before["runs"]
        assert tuple(db.execute("SELECT output_text,usage_json FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()) == before["attempt"]
        late_events = db.execute("SELECT event_type,payload_json FROM generation_events WHERE generation_job_id=? ORDER BY id", (job["id"],)).fetchall()[before["events"]:]
        assert not any(row[0] in {"completed", "candidate", "success"} for row in late_events)
        assert not any(row[0] == "phase_changed" and json.loads(row[1]).get("phase") == "context_completed" for row in late_events)
        assert provider.stage_counts.get("narration", 0) == 0
    finally:
        release.set()
        worker.join(3)
        other.close()


@pytest.mark.parametrize("transition", ["recover", "cancel"])
def test_narration_delta_cannot_write_after_post_gate_transition(tmp_path, monkeypatch, transition):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider([{"events": ["late output"], "finish_reason": "stop", "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}])
    service = GenerationService(db, provider)
    job = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Look",
        idempotency_key=f"narration-delta-{transition}", expected_checkpoint_id=head.checkpoint_id,
        execute=False,
    )
    entered = threading.Event()
    release = threading.Event()
    original_require = service._require_active
    paused = False

    def gated_require(key, job_id):
        nonlocal paused
        original_require(key, job_id)
        if key.endswith(":narration") and not paused:
            paused = True
            entered.set()
            assert release.wait(5), "post-gate narration test barrier timed out"

    monkeypatch.setattr(service, "_require_active", gated_require)
    worker = threading.Thread(target=lambda: service.run(job["id"]), daemon=True)
    db_path = db.execute("PRAGMA database_list").fetchone()[2]
    other = connect(db_path)
    try:
        worker.start()
        assert entered.wait(3)
        before = {
            "draft": db.execute("SELECT draft FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0],
            "attempt_output": db.execute("SELECT output_text FROM provider_attempts WHERE generation_job_id=? AND stage='narration'", (job["id"],)).fetchone()[0],
            "last_event": db.execute("SELECT COALESCE(MAX(id), 0) FROM generation_events WHERE generation_job_id=?", (job["id"],)).fetchone()[0],
            "epoch": db.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()[0],
        }
        competing = GenerationService(other, FakeProvider([]))
        if transition == "recover":
            competing.recover_after_restart()
            assert db.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()[0] != before["epoch"]
        else:
            competing.cancel(owner.id, job["id"])
            state = db.execute("SELECT cancel_requested,status FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()
            assert state["cancel_requested"] == 1
            assert state["status"] in {"cancelling", "cancelled"}
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert db.execute("SELECT draft FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()[0] == before["draft"]
        assert db.execute("SELECT output_text FROM provider_attempts WHERE generation_job_id=? AND stage='narration'", (job["id"],)).fetchone()[0] == before["attempt_output"]
        late_events = db.execute("SELECT event_type,payload_json FROM generation_events WHERE generation_job_id=? AND id>?", (job["id"], before["last_event"])).fetchall()
        assert not any(row[0] == "delta" for row in late_events)
    finally:
        release.set()
        worker.join(3)
        other.close()


def test_narration_completion_event_cannot_follow_cancel_after_commit(tmp_path, monkeypatch):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    provider = FakeProvider(["completed narrative"])
    service = GenerationService(db, provider)
    job = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Look",
        idempotency_key="narration-event-boundary", expected_checkpoint_id=head.checkpoint_id,
        execute=False,
    )
    entered = threading.Event()
    release = threading.Event()

    def after_completion(_job_id):
        entered.set()
        assert release.wait(5), "narration completion barrier timed out"

    monkeypatch.setattr(service, "_after_narration_completion", after_completion)
    worker = threading.Thread(target=lambda: service.run(job["id"]), daemon=True)
    db_path = db.execute("PRAGMA database_list").fetchone()[2]
    other = connect(db_path)
    try:
        worker.start()
        assert entered.wait(3)
        completed_before = db.execute(
            "SELECT id FROM generation_events WHERE generation_job_id=? AND stage='narration' AND event_type='completed' ORDER BY id DESC LIMIT 1",
            (job["id"],),
        ).fetchone()
        assert completed_before is not None
        competing = GenerationService(other, FakeProvider([]))
        competing.cancel(owner.id, job["id"])
        state = db.execute("SELECT cancel_requested,status FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()
        assert state["cancel_requested"] == 1
        assert state["status"] == "cancelled"
        cancelled_event = db.execute(
            "SELECT id FROM generation_events WHERE generation_job_id=? AND event_type='cancelled' ORDER BY id DESC LIMIT 1",
            (job["id"],),
        ).fetchone()
        if cancelled_event is not None:
            assert completed_before["id"] < cancelled_event["id"]
        before_release = db.execute("SELECT COUNT(*) FROM generation_events WHERE generation_job_id=?", (job["id"],)).fetchone()[0]
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        late_events = db.execute("SELECT event_type FROM generation_events WHERE generation_job_id=? ORDER BY id", (job["id"],)).fetchall()[before_release:]
        assert "completed" not in [row[0] for row in late_events]
    finally:
        release.set()
        worker.join(3)
        other.close()


def test_fractional_paid_cap_rejects_before_first_provider_call(tmp_path):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    profile = {**DEFAULT_PROFILE, "credential_tier": "paid", "is_test_profile": False, "pricing": {"prompt": "0.000001", "completion": "0.000001"}}

    class Counting(FakeProvider):
        def __init__(self):
            super().__init__([])
            self.calls = 0

        def generate_text(self, request):
            self.calls += 1
            yield ProviderResult(text="unused", usage={"input_tokens": 1, "output_tokens": 1})

    provider = Counting()
    service = GenerationService(db, provider, profile=profile, settings={"budgets": {"narrator": {"input_limit": 1000, "requested_output": 100}}})
    with pytest.raises(ValidationError, match="Aggregate generation estimate"):
        service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key="fractional-cap", expected_checkpoint_id=head.checkpoint_id, policy="capped_paid", cap="0.000001")
    assert provider.calls == 0


@pytest.mark.parametrize("director_usage", [{"provider_cost_usd": "0.00099"}, {"status": "unknown"}])
def test_director_cost_updates_remaining_allowance_before_narrator(tmp_path, director_usage):
    db, owner, campaign = _story(tmp_path)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    pool = build_candidate_pool(db, campaign.id, campaign.initial_branch_id, "Look", checkpoint_id=head.checkpoint_id, owner_id=owner.id)
    plan = {"checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "selected_memory_ids": [], "reasons": {}, "reason_sources": {}, "scene_ids": pool["scene_ids"], "conflict_flags": []}
    context_profile = {**DEFAULT_PROFILE, "id": "priced-context", "credential_tier": "paid", "is_test_profile": False, "pricing": {"prompt": "0.00000001", "completion": "0.00000001"}}
    narrator_profile = {**context_profile, "id": "priced-narrator", "pricing": {"prompt": "0.0000001", "completion": "0.0000001"}}

    class Provider(FakeProvider):
        def __init__(self):
            super().__init__([])
            self.director_calls = 0
            self.narrator_calls = 0

        def generate_structured(self, request, schema):
            self.director_calls += 1
            return ProviderResult(text=json.dumps({**plan, "action_hash": request["action_hash"]}), usage=director_usage)

        def generate_text(self, request):
            self.narrator_calls += 1
            yield ProviderResult(text="unused", usage={"provider_cost_usd": "0.00001"})

    provider = Provider()
    settings = {"budgets": {"context": {"input_limit": 12000, "requested_output": 4000}, "narrator": {"input_limit": 1000, "requested_output": 100}}}
    service = GenerationService(db, provider, profile={"roles": {"context": context_profile, "narrator": narrator_profile}}, settings=settings)
    job = service.generate(owner.id, campaign.id, campaign.initial_branch_id, "Look", idempotency_key=f"director-cost-{director_usage.get('status', 'known')}", expected_checkpoint_id=head.checkpoint_id, mode="quality", policy="capped_paid", cap="0.001")

    assert provider.director_calls == 1, job
    if director_usage.get("status") == "unknown":
        assert provider.narrator_calls == 1
        assert job["cost_ledger"]["stages"]["context"]["actual_status"] == "unknown"
        assert Decimal(job["cost_ledger"]["stages"]["context"]["estimated_cost_usd"]) > 0
    else:
        assert provider.narrator_calls == 0
        assert job["status"] == "failed"


def test_cost_ledger_keeps_provider_billing_separate_from_unknown_usage(tmp_path):
    db, owner, campaign = _story(tmp_path)
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
    context_profile = {
        **DEFAULT_PROFILE,
        "id": "priced-context",
        "credential_tier": "paid",
        "is_test_profile": False,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "input_limit": 12000,
        "context_limit": 16512,
        "output_limit": 4000,
    }
    narrator_profile = {
        **context_profile,
        "id": "priced-narrator",
        "pricing": {"prompt": "0.000003", "completion": "0.000004"},
    }

    class BillingProvider(FakeProvider):
        def generate_structured(self, request, schema):
            return ProviderResult(text=json.dumps({**plan, "action_hash": request["action_hash"]}), usage={"provider_cost_usd": "0.0005"})

        def generate_text(self, request):
            yield "Narrative with unknown billing."
            yield ProviderResult(text="Narrative with unknown billing.", usage={"status": "unknown"}, finish_reason="stop")

    service = GenerationService(
        db,
        BillingProvider([]),
        profile={"roles": {"context": context_profile, "narrator": narrator_profile}},
    )
    job = service.generate(
        owner.id,
        campaign.id,
        campaign.initial_branch_id,
        "Look",
        idempotency_key="billing-provenance",
        expected_checkpoint_id=head.checkpoint_id,
        mode="quality",
        policy="capped_paid",
        cap="1",
    )
    ledger = job["cost_ledger"]
    context_entry = ledger["stages"]["context"]
    narrator_entry = ledger["stages"]["narration"]
    assert context_entry["provider_reported_cost_usd"] == "0.0005"
    assert context_entry["actual_status"] == "provider_reported"
    assert narrator_entry["provider_reported_cost_usd"] is None
    assert narrator_entry["calculated_cost_usd"] is None
    assert narrator_entry["actual_status"] == "unknown"
    assert narrator_entry["estimated_cost_usd"]
    assert ledger["actual_total_usd"] is None
    assert Decimal(job["remaining_cost_usd"]) < Decimal("1")
    assert Decimal(job["remaining_cost_usd"]) >= Decimal("0")
    assert ledger["stages"]["context"]["estimated_cost_usd"] != ledger["stages"]["narration"]["estimated_cost_usd"]
