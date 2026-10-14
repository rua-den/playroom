"""Durable, owner-authorized spending grants for opt-in paid narrator trials.

One SQLite BEGIN IMMEDIATE transaction must guard a generation job and the
corresponding reservation. Estimates are held conservatively even after failure.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .domain import ValidationError


def _usd(value: str, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a positive USD decimal string")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{field} must be a positive USD decimal string") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValidationError(f"{field} must be a positive USD decimal string")
    return amount


def _date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValidationError("Trial expiry must be an ISO timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError("Trial expiry must include a timezone")
    return parsed.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _latest(connection, owner_id: str):
    return connection.execute(
        "SELECT * FROM paid_trial_authorizations WHERE owner_id=? ORDER BY approved_at DESC, rowid DESC LIMIT 1",
        (owner_id,),
    ).fetchone()


def create_trial_authorization(
    connection, owner_id: str, *, profile_id: str, profile_version: int,
    total_cap_usd: str, per_send_cap_usd: str, max_jobs: int, expires_at: str,
) -> dict:
    """Explicit grant creation, only after authenticated owner action."""
    total, per_send = _usd(total_cap_usd, "Total trial budget"), _usd(per_send_cap_usd, "Per-send budget")
    if per_send > total:
        raise ValidationError("Per-send trial cap cannot exceed total budget")
    if not isinstance(max_jobs, int) or isinstance(max_jobs, bool) or not 1 <= max_jobs <= 100:
        raise ValidationError("Trial max jobs must be between 1 and 100")
    expiry = _date(expires_at)
    if expiry <= _now():
        raise ValidationError("Trial expiry must be in the future")
    from .settings import get_owner_settings
    from .model_profiles import get_model_profile
    from .db import transaction

    with transaction(connection):
        settings = get_owner_settings(connection, owner_id)
        binding = (settings.get("roles") or {}).get("narrator") or {}
        if settings.get("policy") != "capped_paid" or settings.get("mode") != "economy":
            raise ValidationError("Trial authorization requires persisted economy capped_paid settings")
        if (binding.get("id"), binding.get("version")) != (profile_id, profile_version):
            raise ValidationError("Trial narrator must match the selected immutable profile")
        profile = get_model_profile(connection, owner_id, profile_id, profile_version)
        if profile.get("credential_tier") != "paid" or not profile.get("pricing_verified"):
            raise ValidationError("Trial narrator must be a verified paid profile")
        configured_cap = _usd(str(settings.get("confirmed_usd_cap") or ""), "Configured per-send budget")
        if per_send > configured_cap:
            raise ValidationError("Trial per-send cap exceeds persisted owner spending limit")
        current = _latest(connection, owner_id)
        if current and current["state"] == "active" and _date(current["expires_at"]) > _now():
            raise ValidationError("Revoke the current trial before approving a new one")
        ident = str(uuid4())
        connection.execute(
            "INSERT INTO paid_trial_authorizations (id,owner_id,profile_id,profile_version,total_cap_usd,per_send_cap_usd,max_jobs,expires_at,state,approved_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ident, owner_id, profile_id, profile_version, str(total), str(per_send), max_jobs, expiry.isoformat(), "active", _now().isoformat()),
        )
    return get_trial_summary(connection, owner_id)


def _charged_amount(row) -> Decimal:
    held = Decimal(row["reserved_usd"])
    # A provider bill larger than reservation must never free the budget.
    try:
        ledger = json.loads(row["reserved_cost_json"] or "{}")
    except (ValueError, TypeError):
        return held
    for name in ("provider_reported_total_usd", "calculated_total_usd", "actual_total_usd"):
        value = ledger.get(name)
        if value is not None:
            try:
                additional = Decimal(str(value))
                if additional.is_finite() and additional >= 0:
                    held = max(held, additional)
            except (InvalidOperation, ValueError, TypeError):
                pass
    return held


def _usage(connection, trial_id: str) -> tuple[Decimal, int]:
    rows = connection.execute(
        "SELECT r.reserved_usd, j.reserved_cost_json FROM paid_trial_reservations r LEFT JOIN generation_jobs j ON j.id=r.job_id WHERE r.authorization_id=?",
        (trial_id,),
    ).fetchall()
    return sum((_charged_amount(row) for row in rows), Decimal("0")), len(rows)


def get_trial_summary(connection, owner_id: str) -> dict:
    row = _latest(connection, owner_id)
    if row is None:
        return {"state": "none", "reserved_usd": "0", "remaining_usd": "0", "jobs_used": 0}
    used, count = _usage(connection, row["id"])
    total = Decimal(row["total_cap_usd"])
    state = "expired" if row["state"] == "active" and _date(row["expires_at"]) <= _now() else row["state"]
    if used > total:
        state = "overrun"
    return {
        "id": row["id"], "profile_id": row["profile_id"], "profile_version": row["profile_version"],
        "total_cap_usd": row["total_cap_usd"], "per_send_cap_usd": row["per_send_cap_usd"],
        "max_jobs": row["max_jobs"], "expires_at": row["expires_at"],
        "state": state, "reserved_usd": str(used), "remaining_usd": str(max(total - used, Decimal("0"))),
        "jobs_used": count,
    }


def revoke_trial_authorization(connection, owner_id: str, trial_id: str) -> dict:
    from .db import transaction
    with transaction(connection):
        result = connection.execute(
            "UPDATE paid_trial_authorizations SET state='revoked' WHERE id=? AND owner_id=? AND state='active'",
            (trial_id, owner_id),
        )
        if result.rowcount != 1:
            raise ValidationError("Trial authorization was not active for this owner")
    return get_trial_summary(connection, owner_id)


def check_trial_reservation(
    connection, owner_id: str, *, profile: dict, campaign_id: str,
    proposed_usd: str, requested_cap, policy: str, mode: str,
) -> str:
    """Call inside the existing GenerationService transaction, BEFORE inserting job.

    This does not mutate the ledger; caller MUST insert the matching reservation
    in the same transaction as the generation job. Requires a persisted grant.
    """
    from .settings import get_owner_settings
    if policy != "capped_paid" or mode != "economy":
        raise ValidationError("Paid trial policy and economy mode must match the approved grant")
    settings = get_owner_settings(connection, owner_id)
    binding = (settings.get("roles") or {}).get("narrator") or {}
    if settings.get("policy") != "capped_paid" or settings.get("mode") != "economy":
        raise ValidationError("Paid policy requires current owner trial approval")
    if (binding.get("id"), binding.get("version")) != (profile.get("id"), profile.get("version")):
        raise ValidationError("Trial profile is no longer selected")
    persisted_cap = _usd(str(settings.get("confirmed_usd_cap") or ""), "Persisted per-send cap")
    requested = _usd(str(requested_cap), "Request per-send cap")
    if requested > persisted_cap:
        raise ValidationError("Request cap exceeds persisted owner cap")
    row = _latest(connection, owner_id)
    if row is None or row["state"] != "active" or _date(row["expires_at"]) <= _now():
        raise ValidationError("An active trial authorization is required for paid generation")
    if (row["profile_id"], row["profile_version"]) != (profile.get("id"), profile.get("version")):
        raise ValidationError("Trial model/profile does not match the grant")
    per_send = _usd(row["per_send_cap_usd"], "Trial per-send cap")
    proposed = _usd(proposed_usd, "Reserved cost")
    if proposed > per_send:
        raise ValidationError("Generation exceeds authorized trial per-send cap")
    used, jobs = _usage(connection, row["id"])
    if jobs >= row["max_jobs"] or used + proposed > _usd(row["total_cap_usd"], "Trial total cap"):
        raise ValidationError("Trial cumulative budget or job count exhausted")
    return row["id"]


def insert_trial_reservation(connection, job_id: str, authorization_id: str, reserved_usd: str) -> None:
    # The caller's active BEGIN IMMEDIATE transaction includes both the
    # generation_jobs insert and this one. One job ID can debit only once.
    connection.execute(
        "INSERT INTO paid_trial_reservations (job_id,authorization_id,reserved_usd,created_at) VALUES (?,?,?,?)",
        (job_id, authorization_id, reserved_usd, _now().isoformat()),
    )


def assert_trial_dispatch_allowed(connection, job: dict, *, profile: dict) -> None:
    """Fail closed if a queued paid attempt lost its grant before provider dispatch."""
    row = connection.execute(
        "SELECT a.* FROM paid_trial_reservations r JOIN paid_trial_authorizations a ON a.id=r.authorization_id WHERE r.job_id=? AND a.owner_id=?",
        (job["id"], job["owner_id"]),
    ).fetchone()
    if (row is None or row["state"] != "active" or _date(row["expires_at"]) <= _now()
            or (row["profile_id"], row["profile_version"]) != (profile.get("id"), profile.get("version"))):
        raise ValidationError("Paid trial authorization is missing, revoked, expired, or mismatched")
    from .settings import get_owner_settings
    settings = get_owner_settings(connection, job["owner_id"])
    binding = (settings.get("roles") or {}).get("narrator") or {}
    if (settings.get("policy") != "capped_paid" or settings.get("mode") != "economy"
            or (binding.get("id"), binding.get("version")) != (profile.get("id"), profile.get("version"))):
        raise ValidationError("Owner disabled or changed the paid trial configuration")
    used, _ = _usage(connection, row["id"])
    if used > _usd(row["total_cap_usd"], "Trial total cap"):
        raise ValidationError("Trial billed cost exceeded its approved budget")
