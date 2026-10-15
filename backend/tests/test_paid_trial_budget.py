"""RED-first paid-trial server authorization and cross-job budget tests (fake provider only)."""
from __future__ import annotations

import json
import threading
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.generation import GenerationService
from playroom.model_profiles import persist_model_profile
from playroom.provider import FakeProvider
from playroom.settings import save_owner_settings
from playroom.timeline import get_branch_head
from playroom.paid_trials import create_trial_authorization, get_trial_summary, revoke_trial_authorization


def prepared(tmp_path, *, policy="capped_paid", starter=False):
    path = tmp_path / "trial.sqlite3"
    db = connect(path)
    migrate(db)
    owner = create_owner(db, "budget@example.test", "long secure test password")
    profile = persist_model_profile(db, owner.id, {
        "id": "starter-narrator" if starter else "paid-narrator", "provider": "ollama", "endpoint": "https://ollama.com/v1",
        "model": "gemma4:31b" if starter else "gpt-oss:120b",
        "context_limit": 131072, "output_limit": 4096,
        "credential_tier": "free" if starter else "paid", "pricing_verified": True,
        "free_starter_eligible": starter,
        "account_free_credits_remaining": None if starter else None,
        "purchased_credit_exposure_unknown": True,
        "pricing": {"prompt": "0.00000015", "completion": "0.00000060"},
        "secret_version": "test-fixture-secret-id", "is_test_profile": True,
    })
    settings = save_owner_settings(db, owner.id, {
        "roles": {"narrator": {"id": profile["id"], "version": profile["version"], "profile_hash": profile["profile_hash"]}},
        "mode": "economy", "policy": policy,
        "confirmed_usd_cap": "1" if policy == "capped_paid" else None,
    })
    job_cost = Decimal(GenerationService(db, FakeProvider([]))._reservation(
        {"narrator": profile, "context": profile}, "economy", "capped_paid", "1", settings,
    )["reserved_total_usd"])
    return path, db, owner, profile, job_cost


def add_story(db, owner, n):
    return create_campaign(db, owner.id, f"Story {n}", {"name": "World"}, [], {"name": "Player"})


def reserve(db, owner, campaign, key, *, policy="capped_paid", cap="1"):
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    return GenerationService(db, FakeProvider([])).generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Look",
        idempotency_key=key, expected_checkpoint_id=head.checkpoint_id,
        policy=policy, cap=cap, execute=False,
    )


def approve(db, owner, profile, total, *, per_send=None, max_jobs=5, expires=None):
    return create_trial_authorization(
        db, owner.id, profile_id=profile["id"], profile_version=profile["version"],
        total_cap_usd=str(total), per_send_cap_usd=per_send or str(total),
        max_jobs=max_jobs,
        expires_at=expires or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )


def test_no_active_trial_denies_paid_reservation_and_preserves_other_tables(tmp_path):
    _, db, owner, _, _ = prepared(tmp_path)
    campaign = add_story(db, owner, 1)
    with pytest.raises(ValidationError, match="trial|authoriz|approval"):
        reserve(db, owner, campaign, "missing")
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0


def test_two_reserved_jobs_exhaust_total_third_is_denied_before_provider(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    grant = approve(db, owner, profile, cost * 2, max_jobs=10)
    first = reserve(db, owner, add_story(db, owner, 1), "first")
    second = reserve(db, owner, add_story(db, owner, 2), "second")
    with pytest.raises(ValidationError, match="trial|budget|cap"):
        reserve(db, owner, add_story(db, owner, 3), "third")
    rows = db.execute("SELECT job_id FROM paid_trial_reservations WHERE authorization_id=?", (grant["id"],)).fetchall()
    assert {row["job_id"] for row in rows} == {first["id"], second["id"]}
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 2
    summary = get_trial_summary(db, owner.id)
    assert Decimal(summary["reserved_usd"]) == cost * 2
    assert Decimal(summary["remaining_usd"]) == 0


def test_idempotent_lookup_has_exactly_one_debit_even_after_restart(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    grant = approve(db, owner, profile, cost)
    campaign = add_story(db, owner, 1)
    first = reserve(db, owner, campaign, "same")
    again = reserve(db, owner, campaign, "same")
    assert again["id"] == first["id"]
    GenerationService(db, FakeProvider([])).recover_after_restart()
    again = reserve(db, owner, campaign, "same")
    assert again["id"] == first["id"]
    assert db.execute("SELECT COUNT(*) FROM paid_trial_reservations WHERE authorization_id=?", (grant["id"],)).fetchone()[0] == 1


def test_caller_cannot_override_persisted_free_only_or_cap(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path, policy="free_only")
    campaign = add_story(db, owner, 1)
    with pytest.raises(ValidationError, match="policy|free_only|trial"):
        reserve(db, owner, campaign, "upgrade", policy="capped_paid", cap="100")
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0

    # Change to paid mode with a hard per-send setting; a stale crafted request
    # cannot increase the persisted per-send cap.
    save_owner_settings(db, owner.id, {
        "roles": {"narrator": {"id": profile["id"], "version": profile["version"], "profile_hash": profile["profile_hash"]}},
        "mode": "economy", "policy": "capped_paid", "confirmed_usd_cap": "0.01",
    })
    approve(db, owner, profile, cost * 2, per_send=str(cost))
    with pytest.raises(ValidationError, match="cap|authorization|budget|trial"):
        reserve(db, owner, campaign, "escalate", cap="100")
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0


def test_revoked_or_expired_grant_blocks_new_jobs(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    grant = approve(db, owner, profile, cost * 5)
    revoke_trial_authorization(db, owner.id, grant["id"])
    with pytest.raises(ValidationError, match="trial|approval|authoriz"):
        reserve(db, owner, add_story(db, owner, 1), "revoked")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="expiry|future|expired"):
        approve(db, owner, profile, cost, expires=past)


def test_parallel_reservations_cannot_oversubscribe_same_trial(tmp_path):
    path, db, owner, profile, cost = prepared(tmp_path)
    grant = approve(db, owner, profile, cost)
    campaigns = [add_story(db, owner, i) for i in range(2)]
    barrier = threading.Barrier(2)
    accepted, errors = [], []

    def work(i):
        connection = connect(path)
        try:
            barrier.wait(timeout=5)
            accepted.append(reserve(connection, owner, campaigns[i], f"parallel-{i}")["id"])
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work, args=(i,)) for i in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=12)
    assert len(accepted) == 1
    assert len(errors) == 1 and isinstance(errors[0], ValidationError)
    assert db.execute("SELECT COUNT(*) FROM paid_trial_reservations WHERE authorization_id=?", (grant["id"],)).fetchone()[0] == 1


def test_authenticated_trial_api_cannot_grant_on_behalf_of_another_owner(tmp_path):
    path, db, owner, profile, cost = prepared(tmp_path)
    app = create_app(database_url=f"sqlite:///{path}", allowed_hosts={"testserver"}, secure_cookies=False, credential_root=tmp_path / "secrets")
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "long secure test password"}, headers=headers).status_code == 200
    approval = client.post("/api/provider/trials", json={
        "profile_id": profile["id"], "profile_version": profile["version"],
        "total_cap_usd": str(cost * 2), "per_send_cap_usd": str(cost * 2),
        "max_jobs": 2, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }, headers=headers)
    assert approval.status_code == 201, approval.text
    assert approval.json()["id"] and approval.json()["max_jobs"] == 2
    status = client.get("/api/provider/trials/current")
    assert status.status_code == 200 and status.json()["id"] == approval.json()["id"]
    assert Decimal(status.json()["reserved_usd"]) == 0
    revoked = client.post(f"/api/provider/trials/{approval.json()['id']}/revoke", headers=headers)
    assert revoked.status_code == 200
    assert client.get("/api/provider/trials/current").json()["state"] == "revoked"


def test_spend_reservation_survives_generation_row_deletion(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    grant = approve(db, owner, profile, cost)
    campaign = add_story(db, owner, 1)
    job = reserve(db, owner, campaign, "held")
    db.execute("DELETE FROM generation_jobs WHERE id=?", (job["id"],))
    assert db.execute("SELECT COUNT(*) FROM paid_trial_reservations WHERE authorization_id=?", (grant["id"],)).fetchone()[0] == 1
    assert Decimal(get_trial_summary(db, owner.id)["reserved_usd"]) == cost
    with pytest.raises(ValidationError, match="trial|budget"):
        reserve(db, owner, add_story(db, owner, 2), "blocked-after-delete")


def test_disabling_paid_policy_blocks_dispatch_of_already_queued_job(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    approve(db, owner, profile, cost)
    campaign = add_story(db, owner, 1)
    job = reserve(db, owner, campaign, "queued-after-revoke")
    saved = save_owner_settings(db, owner.id, {
        "roles": {"narrator": {"id": profile["id"], "version": profile["version"], "profile_hash": profile["profile_hash"]}},
        "mode": "economy", "policy": "free_only",
    })
    provider = FakeProvider(["must not run"])
    service = GenerationService(db, provider)
    result = service.run(job["id"])
    assert result["status"] == "failed"
    assert provider.calls == []
    assert Decimal(get_trial_summary(db, owner.id)["reserved_usd"]) == cost


def test_unapproved_paid_api_override_rejected_before_job_or_dispatch(tmp_path):
    path, db, owner, _, _ = prepared(tmp_path, policy="free_only")
    campaign = add_story(db, owner, 1)
    checkpoint = get_branch_head(db, campaign.id, campaign.initial_branch_id).checkpoint_id
    provider = FakeProvider(["must never dispatch"])
    app = create_app(
        database_url=f"sqlite:///{path}", allowed_hosts={"testserver"},
        secure_cookies=False, credential_root=tmp_path / "secrets",
        generation_provider=provider,
    )
    client = TestClient(app, base_url="https://testserver")
    headers = {"origin": "https://testserver"}
    assert client.post("/api/auth/login", json={"email": owner.email, "password": "long secure test password"}, headers=headers).status_code == 200
    result = client.post(f"/api/campaigns/{campaign.id}/generate", json={
        "branch_id": campaign.initial_branch_id, "checkpoint_id": checkpoint,
        "action": "Unapproved paid", "idempotency_key": "unapproved-post",
        "mode": "economy", "policy": "capped_paid", "cap": "100",
    }, headers=headers)
    assert result.status_code == 422, result.text
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0
    assert provider.calls == []


def test_server_detects_provider_bill_larger_than_reserved_total(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    approve(db, owner, profile, cost * 3)
    job = reserve(db, owner, add_story(db, owner, 1), "first")
    row = db.execute("SELECT reserved_cost_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()
    ledger = json.loads(row["reserved_cost_json"])
    ledger["provider_reported_total_usd"] = str(cost * 4)
    db.execute("UPDATE generation_jobs SET reserved_cost_json=? WHERE id=?", (json.dumps(ledger), job["id"]))
    summary = get_trial_summary(db, owner.id)
    assert summary["state"] == "overrun"
    assert Decimal(summary["reserved_usd"]) == cost * 4
    with pytest.raises(ValidationError, match="trial|budget"):
        reserve(db, owner, add_story(db, owner, 2), "suspended")


def test_lowering_owner_cap_blocks_already_queued_paid_job(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    approve(db, owner, profile, cost * 2, per_send=str(cost * 2))
    job = reserve(db, owner, add_story(db, owner, 1), "queued-cap-changed")
    save_owner_settings(db, owner.id, {
        "roles": {"narrator": {"id": profile["id"], "version": profile["version"], "profile_hash": profile["profile_hash"]}},
        "mode": "economy", "policy": "capped_paid", "confirmed_usd_cap": str(cost / 2),
    })
    provider = FakeProvider(["must not dispatch"])
    result = GenerationService(db, provider).run(job["id"])
    assert result["status"] == "failed"
    assert provider.calls == []
    assert Decimal(get_trial_summary(db, owner.id)["reserved_usd"]) == cost


def test_revocation_rejected_for_other_owner(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    trial = approve(db, owner, profile, cost)
    another = create_owner(db, "second@example.test", "second password for test")
    with pytest.raises(ValidationError, match="not active|owner"):
        revoke_trial_authorization(db, another.id, trial["id"])
    assert get_trial_summary(db, owner.id)["state"] == "active"


def test_final_invocation_gate_rechecks_revoked_grant(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path)
    grant = approve(db, owner, profile, cost)
    campaign = add_story(db, owner, 1)
    job = reserve(db, owner, campaign, "revoked-at-last-gate")
    service = GenerationService(db, FakeProvider([]))
    epoch = service._epoch()
    stage_key = f"{job['id']}:narration"
    db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (job["id"],))
    db.execute("UPDATE provider_attempts SET status='claimed',claim_epoch=? WHERE stage_key=?", (epoch, stage_key))
    revoke_trial_authorization(db, owner.id, grant["id"])
    assert service._invocation_gate(job["id"], stage_key) is False
    assert db.execute("SELECT status FROM provider_attempts WHERE stage_key=?", (stage_key,)).fetchone()["status"] == "claimed"


def test_gemma_starter_free_only_unknown_purchased_credits_rejects_without_job(tmp_path):
    _, db, owner, profile, _ = prepared(tmp_path, policy="free_only", starter=True)
    assert profile["credential_tier"] == "free" and profile["free_starter_eligible"] is True
    assert profile["purchased_credit_exposure_unknown"] is True
    with pytest.raises(ValidationError, match="free_only|purchased.credit|billing"):
        reserve(db, owner, add_story(db, owner, 1), "starter-free", policy="free_only", cap=None)
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0


def test_gemma_starter_capped_paid_without_separate_grant_denies_before_job(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path, starter=True)
    assert cost > 0 and profile["credential_tier"] == "free"
    with pytest.raises(ValidationError, match="trial|approv|authoriz"):
        reserve(db, owner, add_story(db, owner, 1), "starter-no-grant")
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0


def test_gemma_starter_explicit_trial_grant_debits_across_branches_and_replays(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path, starter=True)
    grant = approve(db, owner, profile, cost * 2, per_send=str(cost), max_jobs=5)
    campaign = add_story(db, owner, 1)
    first = reserve(db, owner, campaign, "starter-granted")
    again = reserve(db, owner, campaign, "starter-granted")
    assert first["id"] == again["id"]
    second = reserve(db, owner, add_story(db, owner, 2), "starter-second")
    with pytest.raises(ValidationError, match="budget|trial|cap"):
        reserve(db, owner, add_story(db, owner, 3), "starter-third")
    rows = db.execute("SELECT job_id FROM paid_trial_reservations WHERE authorization_id=?", (grant["id"],)).fetchall()
    assert {x["job_id"] for x in rows} == {first["id"], second["id"]}
    assert Decimal(get_trial_summary(db, owner.id)["reserved_usd"]) == cost * 2
    revoke_trial_authorization(db, owner.id, grant["id"])
    assert GenerationService(db, FakeProvider([])).run(first["id"])["status"] == "failed"


def test_gemma_starter_quality_context_never_bypasses_paid_authorization(tmp_path):
    _, db, owner, profile, _ = prepared(tmp_path, starter=True)
    campaign = add_story(db, owner, 1)
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id)
    with pytest.raises(ValidationError, match="quality|strict|paid|trial"):
        GenerationService(db, FakeProvider([])).generate(
            owner.id, campaign.id, campaign.initial_branch_id, "Look",
            idempotency_key="starter-quality", expected_checkpoint_id=head.checkpoint_id,
            mode="quality", policy="capped_paid", cap="1", execute=False,
        )
    assert db.execute("SELECT COUNT(*) FROM generation_jobs").fetchone()[0] == 0


def test_starter_last_invocation_gate_rejects_revoked_grant_and_legacy_free_only_job(tmp_path):
    _, db, owner, profile, cost = prepared(tmp_path, starter=True)
    grant = approve(db, owner, profile, cost, per_send=str(cost))
    job = reserve(db, owner, add_story(db, owner, 1), "starter-last-gate")
    service = GenerationService(db, FakeProvider([]))
    epoch = service._epoch()
    key = f"{job['id']}:narration"
    db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (job["id"],))
    db.execute("UPDATE provider_attempts SET status='claimed',claim_epoch=? WHERE stage_key=?", (epoch, key))
    revoke_trial_authorization(db, owner.id, grant["id"])
    assert service._invocation_gate(job["id"], key) is False
    assert db.execute("SELECT status FROM provider_attempts WHERE stage_key=?", (key,)).fetchone()["status"] == "claimed"
    # Simulate a queued job created by an older Free-only version of Playroom.
    # It must never slip past the last-moment provider gate after an upgrade.
    db.execute("UPDATE generation_jobs SET policy='free_only' WHERE id=?", (job["id"],))
    assert service._invocation_gate(job["id"], key) is False
    assert db.execute("SELECT status FROM provider_attempts WHERE stage_key=?", (key,)).fetchone()["status"] == "claimed"


def test_starter_purchased_credit_exposure_cannot_be_disabled_by_profile_flag(tmp_path):
    _, db, owner, profile, _ = prepared(tmp_path, starter=True, policy="free_only")
    from playroom.model_profiles import validate_dispatch
    modified = {**profile, "purchased_credit_exposure_unknown": False,
                "account_free_credits_remaining": "999", "free_starter_eligible": True}
    with pytest.raises(ValidationError, match="purchased|billing|free_only"):
        validate_dispatch(modified, "free_only", None)
