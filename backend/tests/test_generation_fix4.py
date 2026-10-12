from __future__ import annotations

import json
import threading
from decimal import Decimal

import pytest

from playroom.attempt_runtime import PhysicalAttemptRegistry
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.generation import DEFAULT_PROFILE, GenerationService
from playroom.provider import FakeProvider, ProviderAdapter, ProviderFailure, ProviderResult
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
        invocation_gate=lambda _handle: False,
    )
    assert next(stream).code == "CANCELLED"
    assert opened == []


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
    assert ledger["stages"]["context"]["actual_status"] == "actual"
    assert ledger["stages"]["narration"]["actual_status"] == "actual"
    assert Decimal(ledger["actual_total_usd"]) > 0
    run = db.execute("SELECT token_budget_json, request_json, wire_json, counter_id, counter_mode FROM context_runs").fetchone()
    assert json.loads(run["request_json"])["narrator"]["messages"]
    assert json.loads(run["wire_json"])["narrator"]["messages"]

