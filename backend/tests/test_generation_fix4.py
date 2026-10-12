from __future__ import annotations

import json
import threading
from decimal import Decimal

import pytest

from playroom.attempt_runtime import PhysicalAttemptRegistry
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.context import build_candidate_pool
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.generation import DEFAULT_PROFILE, GenerationService
from playroom.memory import append_memory_version
from playroom.provider import FakeProvider, OpenRouterAdapter, ProviderAdapter, ProviderFailure, ProviderResult
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
    run = db.execute("SELECT token_budget_json, request_json, wire_json, counter_id, counter_mode FROM context_runs").fetchone()
    assert json.loads(run["request_json"])["narrator"]["messages"]
    assert json.loads(run["wire_json"])["narrator"]["messages"]


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
