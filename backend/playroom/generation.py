from __future__ import annotations

"""Durable generation orchestration.

SQLite owns reservations and stage state. Provider I/O always runs outside a
transaction, so a browser disconnect cannot cancel or duplicate work.
"""

import hashlib
import json
import logging
import sqlite3
import time
from threading import Event, RLock
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from jsonschema import Draft202012Validator

from .context import build_candidate_pool, build_context_preview, _profiles
from .db import transaction
from .domain import NotFound, StateConflict, ValidationError
from .model_profiles import estimate_cost_usd, validate_dispatch, requires_spending_authorization
from .paid_trials import check_trial_reservation, insert_trial_reservation, assert_trial_dispatch_allowed
from .model_profiles import get_model_profile
from .settings import get_owner_settings, ROLE_BUDGET_DEFAULTS
from .provider import ProviderAdapter, ProviderFailure, ProviderResult
from .context_director import deterministic_selection, validate_director_plan
from .timeline import _create_committed_revision_in_transaction, get_branch_head, load_state_checkpoint
from .chatgpt_import import assert_import_review_approved
from .roleplay_segments import parse_narrator_payload, validate_narrator_segments
from .roleplay_policy import GroundingViolation, NpcKnowledgeViolation, PlayerAgencyViolation, validate_grounded_precision, validate_npc_knowledge, validate_player_agency
from .attempt_runtime import PhysicalAttemptRegistry
from .wire_cost import (
    DEFAULT_COUNTER_ID,
    calculated_usage_cost,
    count_provider_wire,
    conservative_ledger_cost,
    effective_input_cap,
    normalized_budget,
    provider_reported_cost,
    stage_cost,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _serializable_request(value):
    copied = dict(value)
    copied.pop("cancel_event", None)
    return _copy(copied)


DEFAULT_PROFILE = {
    "id": "fake-narrator-test", "version": 1, "profile_hash": "synthetic-profile",
    "provider": "fake", "endpoint": "fake://local", "model": "synthetic-fixture",
    "context_limit": 12000, "output_limit": 4000, "credential_tier": "free",
    "pricing_verified": True, "pricing": {"prompt": "0", "completion": "0"},
    "secret_version": "synthetic", "is_test_profile": True,
    "capabilities_verified": True, "structured_output": True,
    "native_structured_output": True, "structured_schema_parameter": "response_format",
}

SELECTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["checkpoint_id", "action_hash", "selected_memory_ids", "reasons", "reason_sources", "scene_ids", "conflict_flags", "selected_characters"],
    "properties": {
        "checkpoint_id": {"type": "string"}, "action_hash": {"type": "string"},
        "selected_memory_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "uniqueItems": True},
        "reasons": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 180}},
        "reason_sources": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        "scene_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "conflict_flags": {"type": "array", "items": {"type": "string", "maxLength": 160}},
        "selected_characters": {"type": "array", "maxItems": 32, "items": {"type": "object", "additionalProperties": False, "required": ["character_id", "profile_version_id"], "properties": {"character_id": {"type": "string"}, "profile_version_id": {"type": "string"}}}},
    },
}

NARRATOR_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["segments"],
    "properties": {
        "segments": {
            "type": "array", "minItems": 1, "maxItems": 128,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "text"],
                "allOf": [
                    {"if": {"properties": {"kind": {"const": "dialogue"}}}, "then": {"required": ["character_id", "profile_version_id"]}},
                    {"if": {"properties": {"kind": {"const": "narration"}}}, "then": {"not": {"anyOf": [{"required": ["character_id"]}, {"required": ["profile_version_id"]}]}}},
                ],
                "properties": {
                    "kind": {"enum": ["narration", "dialogue"]},
                    "text": {"type": "string", "minLength": 1},
                    "character_id": {"type": "string"},
                    "profile_version_id": {"type": "string"},
                },
            },
        },
    },
}


class _ProviderError(Exception):
    def __init__(self, failure: ProviderFailure):
        self.failure = failure


class GenerationService:
    """Durable worker with one immutable parent and one attempt per stage."""

    def __init__(self, connection: sqlite3.Connection, provider: ProviderAdapter | None, *, profile: dict | None = None, settings: dict | None = None, timeout_seconds: float = 300.0, provider_factory=None, credential_resolver=None, attempt_registry=None, context_counter=None, context_counter_id: str = DEFAULT_COUNTER_ID):
        self.connection, self.provider = connection, provider
        self.timeout_seconds = timeout_seconds
        self.profile = _copy(profile or DEFAULT_PROFILE)
        self.settings = _copy(settings or {})
        self.provider_factory = provider_factory
        self.credential_resolver = credential_resolver
        self.attempt_registry = attempt_registry or PhysicalAttemptRegistry()
        self._context_counter = context_counter
        self._context_counter_id = context_counter_id
        self._attempt_cancel_events: dict[str, Event] = {}
        # Provider worker callbacks and the request/worker thread share one
        # SQLite connection in local execution.  Serialize the small durable
        # claim/output transitions so a lazy stream advance cannot interleave
        # a cursor or transaction with a main-thread append.
        self._db_lock = RLock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        # Schema ownership stays in startup ``migrate``; service construction
        # must be a read/worker operation and cannot implicitly run DDL.
        required = {"generation_jobs", "provider_attempts", "generation_branch_guards", "generation_events", "execution_epochs"}
        present = {row["name"] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(present):
            raise RuntimeError("Generation schema is not migrated")

    def _profiles(self) -> dict:
        if isinstance(self.profile.get("roles"), dict):
            roles = self.profile["roles"]
            narrator, context = roles.get("narrator") or DEFAULT_PROFILE, roles.get("context") or roles.get("narrator") or DEFAULT_PROFILE
        elif isinstance(self.profile.get("narrator"), dict):
            narrator, context = self.profile["narrator"], self.profile.get("context") or self.profile["narrator"]
        else:
            narrator = context = self.profile
        return {"narrator": _copy(narrator), "context": _copy(context)}

    def _role_budget(self, profile: dict, settings: dict, role: str) -> dict:
        custom_defaults = (
            profile.get("provider") == "custom"
            and profile.get("custom_billing") == "provider_managed"
            and profile.get("limits_source") == "application_default"
            and profile.get("pricing_verified") is False
            and profile.get("capabilities_verified") is False
        )
        configured = {} if custom_defaults else ((settings.get("budgets") or {}).get(role) or {})
        return normalized_budget(profile, configured)

    def _counter(self, profile: dict):
        # A server-owned exact counter may be supplied by a test/tokenizer
        # integration through the service settings.  Client metadata is never
        # trusted as an exact counter.
        counter = self._context_counter or self.settings.get("context_counter")
        return counter if callable(counter) else None

    def _counter_id(self, profile: dict) -> str:
        value = self.settings.get("context_counter_id") if self._context_counter_id == DEFAULT_COUNTER_ID else self._context_counter_id
        return str(value or profile.get("counter_id") or DEFAULT_COUNTER_ID)

    def _preview_config(self, profile: dict, settings: dict, role: str = "narrator") -> dict:
        budget = self._role_budget(profile, settings, role)
        return {
            "profile_id": profile.get("id"),
            "profile_version": profile.get("version"),
            "profile_hash": profile.get("profile_hash"),
            "settings_revision": settings.get("settings_revision"),
            "owner_settings_hash": settings.get("settings_hash"),
            **budget,
            "is_test_profile": bool(profile.get("is_test_profile")),
            "capabilities_verified": bool(profile.get("capabilities_verified", True)),
            "limits_source": profile.get("limits_source"),
            "counter_id": self._counter_id(profile),
        }

    def _persisted_config(self, owner_id: str):
        settings = get_owner_settings(self.connection, owner_id)
        roles = {}
        for role, binding in (settings.get("roles") or {}).items():
            if binding:
                roles[role] = get_model_profile(self.connection, owner_id, binding["id"], binding.get("version"))
        if not roles:
            return None, None
        narrator = roles.get("narrator") or DEFAULT_PROFILE
        return settings, {"narrator": _copy(narrator), "context": _copy(roles.get("context") or narrator)}

    def _epoch(self) -> str:
        with self._db_lock:
            row = self.connection.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()
            if row is None:
                raise RuntimeError("Execution epoch is unavailable")
            return row["epoch"]

    def _reservation(self, profiles: dict, mode: str, policy: str, cap, settings: dict | None = None) -> dict:
        settings = settings or self.settings
        if mode == "quality":
            if (profiles.get("narrator") or {}).get("provider") == "custom":
                raise ValidationError("Custom provider supports narrator economy only")
            context_profile = profiles.get("context") or {}
            if not context_profile.get("native_structured_output", context_profile.get("structured_output", True)):
                raise ValidationError("Quality mode requires native strict structured output for the context role")
        stages = ["narration"] if mode == "economy" else ["context", "narration"]
        entries, total = {}, Decimal("0")
        for stage in stages:
            profile = profiles["context" if stage == "context" else "narrator"]
            role = "context" if stage == "context" else "narrator"
            budget = self._role_budget(profile, settings, role)
            input_tokens = budget["input_limit"]
            output_tokens = budget["requested_output"]
            custom_unknown_cost = profile.get("provider") == "custom" and profile.get("custom_billing") == "provider_managed"
            if custom_unknown_cost:
                validate_dispatch(profile, policy, {"input_tokens": input_tokens, "completion_tokens": output_tokens}, cap)
            elif policy == "free_only":
                validate_dispatch(profile, policy, {"input_tokens": 0, "completion_tokens": output_tokens}, None)
            elif policy == "capped_paid":
                if cap is None:
                    raise ValidationError("A confirmed USD cap is required")
                total += estimate_cost_usd(profile, input_tokens, output_tokens)
            estimated_cost = None if custom_unknown_cost else estimate_cost_usd(profile, input_tokens, output_tokens)
            entries[stage] = {
                "role": role,
                "reserved_input_tokens": input_tokens,
                "reserved_output_tokens": output_tokens,
                "estimated_cost_usd": str(estimated_cost) if estimated_cost is not None else None,
                "estimated_status": "unknown" if custom_unknown_cost else "estimated",
                "provider_reported_cost_usd": None,
                "provider_reported_status": "unknown",
                "calculated_cost_usd": None,
                "calculated_status": "unknown",
                "cost_provenance": "provider_managed_unknown" if custom_unknown_cost else "estimated",
                "actual_cost_usd": None,
                "actual_status": "unknown",
                "usage": None,
                "budget": budget,
                "profile_id": profile.get("id"),
                "profile_version": profile.get("version"),
                "profile_hash": profile.get("profile_hash"),
            }
        custom_unknown = any((profiles["context" if stage == "context" else "narrator"].get("provider") == "custom") for stage in stages)
        if policy == "capped_paid" and not custom_unknown and total > Decimal(str(cap)):
            raise ValidationError("Aggregate generation estimate exceeds the confirmed USD cap")
        return {"policy": policy, "cap": None if custom_unknown else (str(cap) if cap is not None else None), "stages": entries, "reserved_total_usd": None if custom_unknown else str(total), "actual_total_usd": None}

    def _request_hash(self, campaign_id, branch_id, action, checkpoint_id, preview_id, idempotency_key, mode, policy, cap, submitted_identity=None):
        # Recovery identity is derived only from the submitted request. Live
        # settings/profiles/keys are intentionally absent and may change later.
        if submitted_identity is not None:
            return _hash({"campaign_id": campaign_id, "branch_id": branch_id, "action": action, "checkpoint_id": checkpoint_id, "preview_id": preview_id, "idempotency_key": idempotency_key, "submitted": submitted_identity})
        return _hash({"campaign_id": campaign_id, "branch_id": branch_id, "action": action, "checkpoint_id": checkpoint_id, "preview_id": preview_id, "idempotency_key": idempotency_key, "mode": mode, "policy": policy, "cap": str(cap) if cap is not None else None})

    def existing_for_submitted_request(self, owner_id, campaign_id, branch_id, action, *, idempotency_key, expected_checkpoint_id, preview_id, submitted_identity):
        # Recovery/idempotency is only valid while the campaign branch remains
        # active. Historical terminal jobs stay readable through GET methods,
        # but a trashed campaign cannot replay or reserve generation work.
        get_branch_head(self.connection, campaign_id, branch_id, owner_id)
        request_hash = self._request_hash(campaign_id, branch_id, action, expected_checkpoint_id, preview_id, idempotency_key, None, None, None, submitted_identity=submitted_identity)
        existing = self.connection.execute("SELECT id,request_hash FROM generation_jobs WHERE owner_id=? AND branch_id=? AND operation='generation' AND idempotency_key=?", (owner_id, branch_id, idempotency_key)).fetchone()
        if existing is None:
            return None
        if existing["request_hash"] != request_hash:
            raise StateConflict("Conflicting idempotency payload")
        return self._job(existing["id"])

    def generate(self, owner_id: str, campaign_id: str, branch_id: str, action: str, *, idempotency_key: str, expected_checkpoint_id: str, preview_id: str | None = None, mode: str = "economy", policy: str = "free_only", cap=None, execute: bool = True, submitted_identity=None) -> dict:
        if mode not in {"economy", "quality"}:
            raise ValidationError("Unknown generation mode")
        if not action.strip() or not idempotency_key.strip():
            raise ValidationError("Action and idempotency key are required")
        request_hash = self._request_hash(campaign_id, branch_id, action, expected_checkpoint_id, preview_id, idempotency_key, mode, policy, cap, submitted_identity=submitted_identity)
        get_branch_head(self.connection, campaign_id, branch_id, owner_id)
        existing = self.connection.execute("SELECT id,request_hash FROM generation_jobs WHERE owner_id=? AND branch_id=? AND operation='generation' AND idempotency_key=?", (owner_id, branch_id, idempotency_key)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise StateConflict("Conflicting idempotency payload")
            return self._job(existing["id"])
        preview_snapshot = None
        profiles = self._profiles()
        settings = _copy(self.settings)
        settings.setdefault("budgets", {role: dict(values) for role, values in ROLE_BUDGET_DEFAULTS.items()})
        settings.update({"mode": mode, "policy": policy, "confirmed_usd_cap": str(cap) if cap is not None else settings.get("confirmed_usd_cap")})
        settings["counter_id"] = self._counter_id(profiles["narrator"])
        settings["counter_mode"] = "exact" if self._counter(profiles["narrator"]) is not None else "estimated"
        head = get_branch_head(self.connection, campaign_id, branch_id, owner_id)
        if head.checkpoint_id != expected_checkpoint_id:
            raise StateConflict("Generation checkpoint is stale")
        job_id, created = str(uuid4()), _now()
        with transaction(self.connection):
            # Recheck ownership/head while the reservation lock is held.
            locked_head = get_branch_head(self.connection, campaign_id, branch_id, owner_id)
            if locked_head.checkpoint_id != expected_checkpoint_id:
                raise StateConflict("Generation checkpoint is stale")
            assert_import_review_approved(self.connection, owner_id, campaign_id, locked_head.checkpoint_id)
            if self.connection.execute("SELECT 1 FROM generation_branch_guards WHERE branch_id=?", (branch_id,)).fetchone():
                raise StateConflict("A generation is already active on this branch")
            # A persistent count prevents multiple application workers from
            # exceeding the two upstream attempt contract.
            count = self.connection.execute("SELECT COUNT(*) AS n FROM provider_attempts WHERE status='dispatched'").fetchone()["n"]
            if count >= 2:
                raise StateConflict("Provider concurrency limit reached")
            locked_settings, locked_profiles = self._persisted_config(owner_id)
            if locked_settings is not None:
                settings = locked_settings
                profiles = locked_profiles
                if submitted_identity is not None:
                    if not submitted_identity["mode"]["present"] or submitted_identity["mode"]["value"] is None:
                        mode = settings.get("mode", mode)
                    if not submitted_identity["policy"]["present"] or submitted_identity["policy"]["value"] is None:
                        policy = settings.get("policy", policy)
                    if not submitted_identity["cap"]["present"] or submitted_identity["cap"]["value"] is None:
                        cap = settings.get("confirmed_usd_cap")
                # A request's policy and cap are NOT independent spending
                # approval. Persisted owner settings are the upper bound.
                if policy != locked_settings.get("policy", "free_only"):
                    raise ValidationError("Submitted paid policy differs from persisted owner approval")
                if mode == "quality" and locked_settings.get("mode") != "quality":
                    raise ValidationError("Submitted quality mode differs from persisted owner approval")
                if policy == "capped_paid":
                    configured = locked_settings.get("confirmed_usd_cap")
                    if configured is None or cap is None:
                        raise ValidationError("Persisted paid cap is required")
                    from decimal import Decimal as _Money
                    if _Money(str(cap)) > _Money(str(configured)):
                        raise ValidationError("Submitted paid cap exceeds persisted owner cap")
                settings = _copy(settings)
                settings.update({"mode": mode, "policy": policy, "confirmed_usd_cap": str(cap) if cap is not None else settings.get("confirmed_usd_cap")})
                settings.setdefault("budgets", {role: dict(values) for role, values in ROLE_BUDGET_DEFAULTS.items()})
                settings["counter_id"] = self._counter_id(profiles["narrator"])
                settings["counter_mode"] = "exact" if self._counter(profiles["narrator"]) is not None else "estimated"
            if preview_id is not None:
                preview_row = self.connection.execute("SELECT payload_json FROM context_previews WHERE id=? AND owner_id=?", (preview_id, owner_id)).fetchone()
                if preview_row is None:
                    raise NotFound("Context preview not found")
                preview_snapshot = json.loads(preview_row["payload_json"])
                if (preview_snapshot.get("campaign_id"), preview_snapshot.get("branch_id"), preview_snapshot.get("action"), preview_snapshot.get("checkpoint_id")) != (campaign_id, branch_id, action, expected_checkpoint_id):
                    raise StateConflict("Submitted context preview does not match generation identity")
                if preview_snapshot.get("status") != "ready":
                    raise ValidationError("Only a ready context preview can be submitted")
            if preview_snapshot is not None and preview_snapshot.get("profile_id"):
                preview_profile = next((candidate for candidate in (profiles.get("context"), profiles.get("narrator")) if candidate and candidate.get("id") == preview_snapshot.get("profile_id")), None)
                if preview_profile is None or (preview_snapshot.get("profile_version") is not None and preview_profile.get("version") != preview_snapshot.get("profile_version")) or (preview_snapshot.get("profile_hash") and preview_profile.get("profile_hash") != preview_snapshot.get("profile_hash")):
                    raise StateConflict("Submitted context preview is stale because its profile changed")
            if preview_snapshot is None:
                narrator = profiles["narrator"]
                preview_config = self._preview_config(narrator, settings, "narrator")
                preview_snapshot = build_context_preview(self.connection, campaign_id, branch_id, action, preview_config, owner_id=owner_id, settings_hash=_hash(settings))
            if preview_snapshot.get("settings_revision") is not None and preview_snapshot.get("settings_revision") != settings.get("settings_revision"):
                raise StateConflict("Submitted context preview is stale because settings changed")
            if preview_snapshot.get("owner_settings_hash") and preview_snapshot.get("owner_settings_hash") != settings.get("settings_hash"):
                raise StateConflict("Submitted context preview is stale because settings changed")
            if preview_snapshot.get("checkpoint_id") != expected_checkpoint_id or preview_snapshot.get("action") != action:
                raise StateConflict("Submitted context preview is stale")
            if preview_snapshot.get("status") == "blocked":
                raise ValidationError(preview_snapshot.get("failure") or "Required context exceeds the verified input budget")
            # Keep the immutable snapshots in the parent and use them for all
            # later wire/cost checks.  The configured role budgets participate
            # in both the settings hash and this conservative reservation.
            reservation = self._reservation(profiles, mode, policy, cap, settings)
            trial_id = None
            if locked_settings is not None and policy == "capped_paid" and requires_spending_authorization(profiles["narrator"]):
                trial_id = check_trial_reservation(
                    self.connection, owner_id, profile=profiles["narrator"],
                    campaign_id=campaign_id, proposed_usd=reservation["reserved_total_usd"],
                    requested_cap=cap, policy=policy, mode=mode,
                )
                reservation["trial_authorization_id"] = trial_id
            self.connection.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,action,status,mode,policy,created_at,settings_revision,settings_snapshot_json,profile_snapshot_json,credential_version,execution_epoch,cancel_requested,reserved_cost_json,preview_id,preview_snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, owner_id, campaign_id, branch_id, "generation", idempotency_key, request_hash, expected_checkpoint_id, action, "queued", mode, policy, created, settings.get("settings_revision", 0), json.dumps(settings, sort_keys=True), json.dumps(profiles, sort_keys=True), profiles.get("narrator", {}).get("secret_version"), self._epoch(), 0, json.dumps(reservation, sort_keys=True), preview_id, json.dumps(preview_snapshot, ensure_ascii=False, sort_keys=True)))
            if trial_id is not None:
                insert_trial_reservation(self.connection, job_id, trial_id, reservation["reserved_total_usd"])
            planned = ["narration"] if mode == "economy" else ["context", "narration"]
            for stage in planned:
                stage_profile = profiles["context" if stage == "context" else "narrator"]
                self.connection.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,request_json,output_text,output_offset,claim_epoch,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), job_id, stage, f"{job_id}:{stage}", json.dumps(_copy(stage_profile), sort_keys=True), f"pending:{stage}", "queued", "{}", "", 0, self._epoch(), created))
            self.connection.execute("INSERT INTO generation_branch_guards(branch_id,generation_job_id,acquired_at) VALUES(?,?,?)", (branch_id, job_id, created))
            self._event(job_id, None, "reserved", None, "", {"checkpoint_id": expected_checkpoint_id})
        return self.run(job_id) if execute else self._job(job_id)

    def run_queued(self, *, limit: int = 1) -> list[dict]:
        rows = self.connection.execute("SELECT id FROM generation_jobs WHERE status='queued' AND execution_epoch=(SELECT epoch FROM execution_epochs WHERE id=1) ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return [self.run(row["id"]) for row in rows]

    def run(self, job_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFound("Generation job not found")
        if row["status"] not in {"queued", "running"}:
            return self._job(job_id)
        self.connection.execute("UPDATE generation_jobs SET status='running' WHERE id=? AND status='queued'", (job_id,))
        self._event(job_id, None, "phase_changed", None, "", {"phase": "running"})
        try:
            self._execute(row)
        except _ProviderError as exc:
            self._fail(job_id, exc.failure)
        except (ValidationError, StateConflict) as exc:
            self._fail(job_id, ProviderFailure("STATE_CONFLICT", str(exc)))
        except Exception as exc:
            logger.exception("generation job failed", extra={"job_id": job_id})
            self._fail(job_id, ProviderFailure("GENERATION_FAILED", "Generation worker failed"))
        return self._job(job_id)

    def _wire_metadata(self, request: dict, profile: dict, *, schema: dict | None = None, role: str, budget: dict) -> dict:
        metadata = count_provider_wire(request, profile, schema=schema, counter=self._counter(profile))
        metadata["counter_id"] = self._counter_id(profile)
        metadata["role"] = role
        metadata["budget"] = dict(budget)
        metadata["input_cap"] = effective_input_cap(profile, budget)
        metadata["output_reserve"] = int(request.get("reserved_completion_tokens", 0))
        if metadata["input_tokens"] > metadata["input_cap"]:
            metadata["fits"] = False
        else:
            metadata["fits"] = True
        return metadata

    def _director_request(self, job, pool: dict, profile: dict, settings: dict):
        budget = self._role_budget(profile, settings, "context")
        base_payload = {
            "action": job["action"],
            "checkpoint_id": pool["checkpoint_id"],
            "action_hash": pool["action_hash"],
            "candidate_pool": {
                "mandatory": pool.get("mandatory", []),
                "optional": [],
                "scene_ids": pool.get("scene_ids", []),
                "selected_characters": pool.get("selected_characters", []),
                "omission_reasons": list(pool.get("omission_reasons", [])),
            },
            "recent_context": pool.get("recent_context", [])[-8:],
        }
        system = "Return only a SelectionPlan JSON. Select supplied IDs and cite each source. Do not invent facts or alter canon."
        schema = SELECTION_SCHEMA

        def make_request(payload):
            return {
                "stage": "context",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
                ],
                "schema": schema,
                "schema_name": "selection_plan",
                "reserved_completion_tokens": budget["requested_output"],
                "model": profile.get("model"),
                "checkpoint_id": pool["checkpoint_id"],
                "action_hash": pool["action_hash"],
            }

        request = make_request(base_payload)
        required_meta = self._wire_metadata(request, profile, schema=schema, role="context", budget=budget)
        if not required_meta["fits"]:
            raise ValidationError("Required director context exceeds the configured input budget")
        omissions = list(pool.get("omission_reasons", []))
        optional = list(pool.get("optional", []))
        included = []

        def add_omission(item, reason):
            entry = {"id": item.get("id"), "reason": reason}
            if entry not in omissions:
                omissions.append(entry)

        def trial_metadata(items):
            payload = _copy(base_payload)
            payload["candidate_pool"]["optional"] = list(items)
            payload["candidate_pool"]["omission_reasons"] = list(omissions)
            return self._wire_metadata(make_request(payload), profile, schema=schema, role="context", budget=budget)

        for item in optional:
            trial_meta = trial_metadata([*included, item])
            if trial_meta["fits"]:
                included.append(item)
            else:
                add_omission(item, "Optional director candidate omitted to fit the context role wire budget.")
            # Omission metadata is part of the counted user wire.  If adding
            # its reason made the final request too large, evict the least
            # recently included optional item and record that eviction too.
            while not trial_metadata(included)["fits"]:
                if not included:
                    raise ValidationError("Required director context exceeds the configured input budget")
                removed = included.pop()
                add_omission(removed, "Optional director candidate omitted to fit the context role wire budget.")
        payload = _copy(base_payload)
        payload["candidate_pool"]["optional"] = included
        payload["candidate_pool"]["omission_reasons"] = omissions
        request = make_request(payload)
        metadata = self._wire_metadata(request, profile, schema=schema, role="context", budget=budget)
        if not metadata["fits"]:
            raise ValidationError("Director wire exceeds the configured input budget")
        request["payload_hash"] = metadata["payload_hash"]
        request["prepared_wire"] = metadata["wire"]
        metadata["source_ids"] = sorted({source for item in [*pool.get("mandatory", []), *included] for source in item.get("source_ids", []) if source})
        metadata["omission_reasons"] = omissions
        request["wire_metadata"] = {
            key: value for key, value in metadata.items() if key not in {"wire", "serialized"}
        }
        bounded_pool = _copy(pool)
        bounded_pool["optional"] = included
        bounded_pool["omission_reasons"] = omissions
        return request, metadata, omissions, bounded_pool

    def _narrator_request(self, job, profile: dict, preview: dict, settings: dict, *, required_only: bool = False):
        budget = self._role_budget(profile, settings, "narrator")
        supported_parameters = set(profile.get("supported_parameters", ()))
        native_schema_capable = bool(profile.get("structured_output") and profile.get("native_structured_output") and profile.get("structured_schema_parameter") in supported_parameters)
        narrator_schema = None if profile.get("is_test_profile") or profile.get("legacy_plain_output") or not native_schema_capable else NARRATOR_SCHEMA
        system = (
            "Continue Vietnamese using supplied context. Canon/invariants; later committed raw turns override summaries. "
            "Exclude pending/foreign/rejected/future facts. Associations/known_by describe knowledge, not presence; narrator knowledge may differ from NPC. "
            "Respect focus/parallel scenes; StyleProfile voice; player controls choices. "
            "Use selected_characters only; never invent speakers. Dialogue only for selected chars; stable IDs character_id/profile_version_id; narration prose. "
            "Respond to the latest player action or dialogue with eligible context. React with a concrete consequence in each selected NPC's established voice; avoid generic atmosphere or reused prior-turn openings/ambient beats. "
            "Preserve selected voice/knowledge; plausibly present. End on a natural open scene beat, leaving the player's next action open. Player controls actions and thoughts. Do not force A/B choices, quests, stats, or other game mechanics. "
            "No invented canon"
        )
        if not profile.get("is_test_profile") and profile.get("legacy_plain_output"):
            # This provider mode has no structured-output contract. Keep the
            # explicit agency rule without breaking tight preflight budgets.
            system = (
                "Continue Vietnamese using supplied context. Respect canon; committed raw turns override summaries. "
                "Exclude pending, foreign, rejected and future facts. known_by means knowledge, not presence. "
                "Respect scenes, selected NPC established voices and player choices. Only selected NPCs may speak. "
                "React to latest player input with grounded consequences; avoid generic atmosphere or reused prior-turn openings/ambient beats. End on a natural open scene beat, leaving the player's next action open. "
                "Never narrate new actions, dialogue, thoughts, or decisions for the player persona. "
                "Do not force A/B choices, quests, stats, or other game mechanics. No invented canon"
            )
        if not profile.get("is_test_profile") and not profile.get("legacy_plain_output"):
            # This is a narrator *application* contract even if the provider
            # cannot enforce a native JSON schema (e.g. Ollama Cloud). Keep
            # post-parse attribution validation regardless of wire capability.
            system += (
                ' Return exactly one JSON object with a "segments" array. '
                'Do not include Markdown fences, commentary, or text outside the JSON object. '
                'Each element must be either {"kind": "narration", "text": "..."} '
                'or {"kind": "dialogue", "text": "...", "character_id": "selected ID", '
                '"profile_version_id": "selected version ID"}. '
                'For dialogue, copy character_id and profile_version_id exactly from the selected_characters list; '
                'if no NPC is eligible, return narration segments only. '
                'Do not place NPCs who are marked present=false into the active scene without an actual scene transition. '
                'Never narrate new actions, dialogue, thoughts, or decisions for the player persona.'
            )
        required = [block for block in preview.get("blocks", []) if block.get("mandatory")]
        optional = [block for block in preview.get("blocks", []) if not block.get("mandatory")]

        def make_request(blocks):
            request = {
                "stage": "narration",
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps({
                            "blocks": blocks,
                            "action": preview["action"],
                            "selected_characters": preview.get("selected_characters", []),
                            "selected_memory_ids": [block["id"] for block in blocks if block.get("type") == "memory" and not block.get("mandatory")],
                        }, ensure_ascii=False, sort_keys=True),
                    },
                ],
                "reserved_completion_tokens": budget["requested_output"],
                "model": profile.get("model"),
                "payload_hash": preview.get("payload_hash"),
            }
            if narrator_schema is not None:
                request["schema"] = narrator_schema
                request["schema_name"] = "narrator_segments"
            return request

        request = make_request(required)
        required_meta = self._wire_metadata(request, profile, schema=narrator_schema, role="narrator", budget=budget)
        if not required_meta["fits"]:
            raise ValidationError("Required narrator context exceeds the configured input budget")
        if required_only:
            return _copy(preview), request, required_meta
        selected = list(required)
        omissions = list(preview.get("omission_reasons", []))
        selected_ids = {block.get("id") for block in selected}
        memory_blocks = [block for block in optional if block.get("type") == "memory"]
        actor_blocks = [block for block in optional if block.get("type") == "character" and (block.get("required_by_memory_ids") or block.get("dependent_memory_id"))]
        other_blocks = [block for block in optional if block not in memory_blocks and block not in actor_blocks]
        actor_by_memory = {}
        for actor in actor_blocks:
            references = actor.get("required_by_memory_ids") or [actor.get("dependent_memory_id")]
            for memory_id in references:
                actor_by_memory.setdefault(memory_id, []).append(actor)

        # Fit each memory together with any actor profiles it depends on. A
        # shared actor is attached to every dependent memory logically, but is
        # emitted once. Thus dropping one reference cannot orphan the profile
        # while dropping all references removes it from the wire entirely.
        for block in memory_blocks:
            unit = [block]
            for actor in actor_by_memory.get(block.get("id"), []):
                if actor.get("id") not in selected_ids:
                    unit.append(actor)
            trial = make_request([*selected, *unit])
            trial_meta = self._wire_metadata(trial, profile, schema=narrator_schema, role="narrator", budget=budget)
            if trial_meta["fits"]:
                selected.extend(unit)
                selected_ids.update(item.get("id") for item in unit)
            else:
                for block in unit:
                    omissions.append({"id": block.get("id"), "reason": "Optional narrator block and its dependent profile omitted to fit the final provider wire budget."})
        for block in other_blocks:
            if block.get("id") in selected_ids:
                continue
            trial = make_request([*selected, block])
            trial_meta = self._wire_metadata(trial, profile, schema=narrator_schema, role="narrator", budget=budget)
            if trial_meta["fits"]:
                selected.append(block)
                selected_ids.add(block.get("id"))
            else:
                omissions.append({"id": block.get("id"), "reason": "Optional narrator block and its dependent profile omitted to fit the final provider wire budget."})
        for actor in actor_blocks:
            if actor.get("id") not in selected_ids:
                reason = "Dependent actor profile omitted because all associated optional memories were omitted."
                if not any(item.get("id") == actor.get("id") and item.get("reason") == reason for item in omissions):
                    omissions.append({"id": actor.get("id"), "reason": reason})
        request = make_request(selected)
        metadata = self._wire_metadata(request, profile, schema=narrator_schema, role="narrator", budget=budget)
        if not metadata["fits"]:
            raise ValidationError("Narrator wire exceeds the configured input budget")
        selected_ids = [block["id"] for block in selected]
        packed = _copy(preview)
        packed["blocks"] = selected
        packed["selected_memory_ids"] = [block["id"] for block in selected if block.get("type") == "memory" and not block.get("mandatory")]
        packed["omission_reasons"] = omissions
        packed["payload_hash"] = metadata["payload_hash"]
        packed["budget"] = {
            **(preview.get("budget") or {}),
            "input_tokens": metadata["input_tokens"],
            "input_limit": budget["input_limit"],
            "input_cap": metadata["input_cap"],
            "context_window": budget["context_window"],
            "output_reserve": budget["requested_output"],
            "output_limit": budget["output_limit"],
            "wrapper_buffer": budget["wrapper_buffer"],
            "counter_mode": metadata["counter_mode"],
            "counter_id": metadata["counter_id"],
            "wire_hash": metadata["payload_hash"],
            "selected_block_ids": selected_ids,
        }
        request["payload_hash"] = metadata["payload_hash"]
        request["prepared_wire"] = metadata["wire"]
        metadata["source_ids"] = sorted({source for block in selected for source in block.get("source_ids", []) if source})
        metadata["omission_reasons"] = omissions
        request["wire_metadata"] = {key: value for key, value in metadata.items() if key not in {"wire", "serialized"}}
        return packed, request, metadata

    def _execute(self, job) -> None:
        # Recovery can encounter jobs reserved before the import review gate
        # existed; re-check immediately before any provider dispatch.
        assert_import_review_approved(self.connection, job["owner_id"], job["campaign_id"], job["checkpoint_id"])
        profiles, settings = json.loads(job["profile_snapshot_json"]), json.loads(job["settings_snapshot_json"])
        narrator, context = profiles["narrator"], profiles["context"]
        saved_preview = job["preview_snapshot_json"] if "preview_snapshot_json" in job.keys() else None
        if saved_preview:
            preview = json.loads(saved_preview)
        else:
            config = self._preview_config(narrator, settings, "narrator")
            preview = build_context_preview(self.connection, job["campaign_id"], job["branch_id"], job["action"], config, owner_id=job["owner_id"], settings_hash=_hash(settings))
        if preview["checkpoint_id"] != job["checkpoint_id"] or preview["status"] == "stale":
            raise StateConflict("Generation checkpoint is stale")
        if preview["status"] == "blocked":
            raise ValidationError(preview.get("failure") or "Required context exceeds the verified input budget")
        pool = build_candidate_pool(self.connection, job["campaign_id"], job["branch_id"], job["action"], checkpoint_id=job["checkpoint_id"], owner_id=job["owner_id"])
        plan = deterministic_selection(pool, pool["checkpoint_id"], pool["action_hash"])
        final_preview = preview
        context_attempt = self.connection.execute("SELECT status FROM provider_attempts WHERE generation_job_id=? AND stage='context'", (job["id"],)).fetchone()
        saved_context = job["final_context_json"] if "final_context_json" in job.keys() else None
        director_request = None
        director_meta = None
        director_key = None
        director_result = None
        # Validate the exact required narrator system/user wrapper before any
        # quality director inference. This preserves the zero-call boundary
        # when the final required wire cannot fit.
        if job["mode"] == "quality":
            self._narrator_request(job, narrator, preview, settings, required_only=True)
        if job["mode"] == "quality" and context_attempt and context_attempt["status"] == "completed" and saved_context:
            final_preview = json.loads(saved_context)
        elif job["mode"] == "quality":
            director_request, director_meta, director_omissions, bounded_pool = self._director_request(job, pool, context, settings)
            self._check_dispatch(job, context, narrator, preview, aggregate=True, stage_meta=director_meta, stage="context")
            key = f"{job['id']}:context"
            director_key = key
            self._insert_attempt(job, "context", key, director_meta["payload_hash"], context, director_request)
            if not self._mark_dispatched(key):
                raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt was claimed by another worker"))
            try:
                result = self.attempt_registry.structured(
                    key,
                    None,
                    director_request,
                    SELECTION_SCHEMA,
                    self.timeout_seconds,
                    provider_factory=lambda _handle: self._provider_for_or_failure(job, "context", context),
                    invocation_gate=lambda _handle: self._invocation_gate(job["id"], key),
                    pre_invocation_gate=lambda _handle: self._claim_gate(job["id"], key),
                )
            except TimeoutError as exc:
                code = "CANCELLED" if str(exc) == "cancelled" else "PROVIDER_TIMEOUT"
                failure = ProviderFailure(code, "Generation was cancelled" if code == "CANCELLED" else "Context director exceeded its timeout")
                self._finish_attempt(key, "interrupted" if code == "CANCELLED" else "failed", failure, "")
                raise _ProviderError(failure)
            except _ProviderError as exc:
                self._finish_attempt(key, "failed", exc.failure, "")
                raise
            self._require_active(key, job["id"])
            if isinstance(result, ProviderFailure):
                self._finish_active_attempt(key, job["id"], "failed", result, "")
                raise _ProviderError(result)
            if not isinstance(result, ProviderResult):
                failure = ProviderFailure("MISSING_TERMINAL", "Context director did not return a terminal result")
                self._finish_active_attempt(key, job["id"], "failed", failure, "")
                raise _ProviderError(failure)
            if result.failure:
                failure = result.failure
                self._finish_active_attempt(key, job["id"], "failed", failure, result.text or "")
                raise _ProviderError(failure)
            if result.finish_reason != "stop":
                code = "OUTPUT_TRUNCATED" if result.finish_reason in {"length", "max_tokens"} else "MODEL_REFUSED" if result.finish_reason == "refusal" else "MISSING_TERMINAL"
                failure = ProviderFailure(code, "Context director did not complete normally")
                self._finish_active_attempt(key, job["id"], "failed", failure, result.text or "")
                raise _ProviderError(failure)
            try:
                value = json.loads(result.text)
                Draft202012Validator(SELECTION_SCHEMA).validate(value)
                plan = validate_director_plan(bounded_pool, bounded_pool["checkpoint_id"], bounded_pool["action_hash"], value)
            except Exception as exc:
                failure = ProviderFailure("SCHEMA_INVALID", str(exc))
                self._finish_active_attempt(key, job["id"], "failed", failure, "")
                raise _ProviderError(failure)
            director_meta["usage"] = result.usage or {"status": "unknown"}
            director_result = result
            try:
                final_preview = self._pack_selected(preview, plan, narrator, director_selected_only=True)
                final_preview["omission_reasons"] = [*final_preview.get("omission_reasons", []), *[item for item in director_omissions if item not in final_preview.get("omission_reasons", [])]]
            except Exception as exc:
                failure = ProviderFailure("PACKING_FAILED", "Validated director output could not be packed")
                with transaction(self.connection):
                    self._require_active(director_key, job["id"])
                    self._record_usage(job["id"], "context", result)
                    if self._finish_attempt(director_key, "failed", result, result.text or "") != 1:
                        raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
                raise _ProviderError(failure) from exc
        else:
            final_preview = self._pack_selected(preview, plan, narrator)
        try:
            final_preview, narrator_request, narrator_meta = self._narrator_request(job, narrator, final_preview, settings)
        except Exception as exc:
            if director_result is None:
                raise
            failure = ProviderFailure("PACKING_FAILED", "Validated director output could not be packed")
            with transaction(self.connection):
                self._require_active(director_key, job["id"])
                self._record_usage(job["id"], "context", director_result)
                if self._finish_attempt(director_key, "failed", director_result, director_result.text or "") != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
            raise _ProviderError(failure) from exc
        saved_narrator = self.connection.execute("SELECT request_json FROM provider_attempts WHERE generation_job_id=? AND stage='narration' AND status='queued'", (job["id"],)).fetchone()
        if saved_narrator and saved_narrator["request_json"] and saved_narrator["request_json"] != "{}":
            persisted_request = json.loads(saved_narrator["request_json"])
            if persisted_request.get("payload_hash") == final_preview.get("payload_hash"):
                narrator_request = persisted_request
                narrator_meta = dict(persisted_request.get("wire_metadata") or {})
                narrator_meta["wire"] = persisted_request.get("prepared_wire")
                narrator_meta.setdefault("payload_hash", final_preview.get("payload_hash"))
        if director_result is not None:
            # Update the ledger before checking the narrator allowance. A
            # provider-reported director cost must reduce the remaining
            # parent cap before narration can be dispatched.
            # The validated selection, immutable final context, usage ledger,
            # and completed director attempt form one durable boundary.  The
            # narrator claim is made only after this transaction commits, so
            # a cancel/restart cannot leave a successful director disguised
            # as dispatched or let a late writer advance the next stage.
            with transaction(self.connection):
                self._require_active(director_key, job["id"])
                self._record_usage(job["id"], "context", director_result)
                self._save_context_run(job, final_preview, director_meta, narrator_meta)
                changed = self._finish_attempt(director_key, "completed", director_result, director_result.text or "")
                if changed != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
                self._event(job["id"], "context", "phase_changed", None, "", {"phase": "context_completed", "selected_memory_ids": plan["selected_memory_ids"]})
            self._check_dispatch(job, context, narrator, final_preview, aggregate=False, stage_meta=narrator_meta, stage="narration")
        else:
            self._check_dispatch(job, context, narrator, final_preview, aggregate=False, stage_meta=narrator_meta, stage="narration")
            self._save_context_run(job, final_preview, director_meta, narrator_meta)
        self._narrate(job, narrator, final_preview, request=narrator_request)

    def _check_dispatch(self, job, context, narrator, preview, *, aggregate: bool, stage_meta=None, stage="narration"):
        if job["policy"] == "capped_paid":
            persisted, _ = self._persisted_config(job["owner_id"])
            if persisted is not None and requires_spending_authorization(narrator):
                assert_trial_dispatch_allowed(self.connection, job, profile=narrator)
        settings = json.loads(job["settings_snapshot_json"] or "{}")
        profile = context if stage == "context" else narrator
        budget = self._role_budget(profile, settings, "context" if stage == "context" else "narrator")
        tokens = int((stage_meta or {}).get("input_tokens") or (preview.get("budget") or {}).get("input_tokens") or 0)
        out = int((stage_meta or {}).get("output_reserve") or budget["requested_output"])
        if stage_meta is not None and not stage_meta.get("fits", False):
            raise ValidationError("Final serialized provider wire exceeds the verified input budget")
        if tokens > effective_input_cap(profile, budget):
            raise ValidationError("Final serialized provider wire exceeds the verified input budget")
        cap = json.loads(job["settings_snapshot_json"] or "{}").get("confirmed_usd_cap")
        if profile.get("provider") == "custom" and profile.get("custom_billing") == "provider_managed":
            validate_dispatch(profile, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, cap)
            return
        if job["policy"] == "capped_paid":
            if cap is None:
                raise ValidationError("A confirmed USD cap is required")
            ledger_row = self.connection.execute("SELECT reserved_cost_json FROM generation_jobs WHERE id=?", (job["id"],)).fetchone()
            ledger = json.loads((ledger_row["reserved_cost_json"] if ledger_row else job["reserved_cost_json"]) or "{}")
            reserved = Decimal("0")
            stage_reserved = Decimal("0")
            if aggregate:
                # Stage one must fit the parent aggregate before any call. The
                # reservation already includes a safe narrator upper allowance.
                for name, entry in (ledger.get("stages") or {}).items():
                    amount = Decimal(str(entry.get("estimated_cost_usd") or "0"))
                    reserved += amount
                    if name == stage:
                        stage_reserved = amount
            else:
                for name, entry in (ledger.get("stages") or {}).items():
                    if name != stage:
                        reserved += conservative_ledger_cost(entry) or Decimal("0")
            current = stage_cost(profile, tokens, out)
            if aggregate and reserved > Decimal(str(cap)):
                raise ValidationError("Aggregate generation estimate exceeds the confirmed USD cap")
            comparable_reserved = reserved - stage_reserved if aggregate else reserved
            if comparable_reserved + current > Decimal(str(cap)):
                raise ValidationError("Aggregate generation estimate exceeds the confirmed USD cap")
            validate_dispatch(profile, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, Decimal(str(cap)) - comparable_reserved)
        else:
            validate_dispatch(profile, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, None)
            if aggregate and job["mode"] == "quality":
                validate_dispatch(context, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, None)

    def _provider_for(self, job, stage, profile):
        secret = None
        keyless_custom = profile.get("provider") == "custom" and profile.get("custom_billing") == "provider_managed" and profile.get("limits_source") == "application_default" and profile.get("pricing_verified") is False and profile.get("capabilities_verified") is False and not profile.get("secret_version")
        if self.credential_resolver is not None and (not keyless_custom) and (profile.get("secret_version") or profile.get("provider") != "custom") and (self.provider_factory is not None or self.provider.__class__.__name__ != "FakeProvider"):
            try:
                secret = self.credential_resolver(job["owner_id"], profile.get("secret_version"))
            except Exception as exc:
                raise _ProviderError(ProviderFailure("CREDENTIAL_UNAVAILABLE", "Pinned credential version is unavailable")) from exc
        if self.provider_factory is not None:
            try:
                return self.provider_factory(owner_id=job["owner_id"], stage=stage, profile=_copy(profile), credential=secret)
            except Exception as exc:
                raise _ProviderError(ProviderFailure("CONFIG_INVALID", "Provider could not be constructed for the pinned profile")) from exc
        return self.provider

    def _provider_for_or_failure(self, job, stage, profile):
        try:
            return self._provider_for(job, stage, profile)
        except _ProviderError as exc:
            return exc.failure

    def _pack_selected(self, preview, plan, profile, *, director_selected_only=False):
        base = [b for b in preview.get("blocks", []) if b.get("mandatory")] if director_selected_only else list(preview.get("blocks", []))
        blocks, known = list(base), {b["id"] for b in base}
        by_id = {item["id"]: item for item in plan.get("optional", [])}
        selected_memories = []
        shared_actors = {}
        checkpoint = load_state_checkpoint(self.connection, preview["campaign_id"], preview["branch_id"], preview["checkpoint_id"])
        actor_profiles = {actor["key"].partition(":")[2]: actor for actor in _profiles(self.connection, preview["campaign_id"], checkpoint.snapshot) if actor["kind"] == "character"}
        for memory_id in plan.get("selected_memory_ids", []):
            item = by_id.get(memory_id)
            if item and memory_id not in known:
                selected_memories.append({"id": memory_id, "type": "memory", "text": item["text"], "source_ids": [item.get("version_id"), *item.get("source_revision_ids", [])], "mandatory": False, "why": plan["reasons"][memory_id], "knowledge_scope": item.get("knowledge_scope"), "known_by": item.get("known_by", []), "as_of_cursor": item.get("effective_cursor")})
                actor_ids = {*item.get("entity_ids", []), *item.get("known_by", [])}
                for actor_id in sorted(actor_ids):
                    actor = actor_profiles.get(actor_id)
                    if actor is None or actor["id"] in known:
                        continue
                    shared = shared_actors.setdefault(actor["id"], {"id": actor["id"], "type": "character", "text": actor["text"], "source_ids": actor["source_ids"], "mandatory": False, "why": "Character profile required by selected memory association.", "actor_id": actor_id, "required_by_memory_ids": []})
                    if memory_id not in shared["required_by_memory_ids"]:
                        shared["required_by_memory_ids"].append(memory_id)
        blocks.extend(selected_memories)
        for actor in shared_actors.values():
            actor["dependent_memory_id"] = actor["required_by_memory_ids"][0]
            blocks.append(actor)
        packed = _copy(preview)
        packed["blocks"], packed["selected_memory_ids"] = blocks, list(plan.get("selected_memory_ids", []))
        allowed_cast = {(item.get("character_id"), item.get("profile_version_id")): item for item in preview.get("selected_characters", [])}
        packed["selected_characters"] = [allowed_cast[(item["character_id"], item["profile_version_id"])] for item in plan.get("selected_characters", []) if isinstance(item, dict) and (item.get("character_id"), item.get("profile_version_id")) in allowed_cast]
        packed["payload_hash"] = _hash({"blocks": blocks, "action": preview["action"], "profile": profile})
        packed["budget"] = {**preview.get("budget", {}), "selected_memory_ids": packed["selected_memory_ids"]}
        return packed

    def _save_context_run(self, job, preview, director_meta=None, narrator_meta=None):
        if self.connection.in_transaction:
            return self._save_context_run_body(job, preview, director_meta, narrator_meta)
        # Economy mode reaches this helper outside the director completion
        # transaction. Keep the insert and guarded final-context CAS under
        # one lock so a cancel/recovery writer cannot strand a stale row.
        with transaction(self.connection):
            return self._save_context_run_body(job, preview, director_meta, narrator_meta)

    def _save_context_run_body(self, job, preview, director_meta=None, narrator_meta=None):
        source_ids = [source for block in preview.get("blocks", []) for source in block.get("source_ids", [])]
        for metadata in (director_meta or {}, narrator_meta or {}):
            source_ids.extend(metadata.get("source_ids", []))
        settings = json.loads(job["settings_snapshot_json"] or "{}")
        director_meta = director_meta or {"status": "not_called", "mode": "economy"}
        narrator_meta = narrator_meta or {}
        budget = {
            **(preview.get("budget") or {}),
            "director": {key: value for key, value in director_meta.items() if key not in {"wire", "serialized"}},
            "narrator": {key: value for key, value in narrator_meta.items() if key not in {"wire", "serialized"}},
            "settings_revision": settings.get("settings_revision", 0),
            "profile_snapshot": json.loads(job["profile_snapshot_json"] or "{}"),
        }
        request_snapshot = {
            "director": director_meta.get("wire") if isinstance(director_meta, dict) else None,
            "narrator": narrator_meta.get("wire") if isinstance(narrator_meta, dict) else None,
            "source_ids": sorted(set(source_ids)),
            "omission_reasons": preview.get("omission_reasons", []),
        }
        wires = {"director": director_meta.get("wire") if isinstance(director_meta, dict) else None, "narrator": narrator_meta.get("wire") if isinstance(narrator_meta, dict) else None}
        existing = self.connection.execute("SELECT 1 FROM context_runs WHERE generation_job_id=? LIMIT 1", (job["id"],)).fetchone()
        if existing is not None:
            updated = self.connection.execute("UPDATE generation_jobs SET final_context_json=? WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=(SELECT epoch FROM execution_epochs WHERE id=1)", (json.dumps(preview, ensure_ascii=False, sort_keys=True), job["id"]))
            if updated.rowcount != 1:
                raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))
            return
        self.connection.execute(
            "INSERT INTO context_runs(id,campaign_id,branch_id,checkpoint_id,settings_revision,source_ids_json,omission_reasons_json,token_budget_json,payload_hash,generation_job_id,request_json,wire_json,counter_id,counter_mode,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()), job["campaign_id"], job["branch_id"], job["checkpoint_id"], settings.get("settings_revision", 0),
                json.dumps(sorted(set(source_ids))), json.dumps(preview.get("omission_reasons", []), ensure_ascii=False),
                json.dumps(budget, ensure_ascii=False, sort_keys=True), preview["payload_hash"], job["id"],
                json.dumps(request_snapshot, ensure_ascii=False, sort_keys=True), json.dumps(wires, ensure_ascii=False, sort_keys=True),
                narrator_meta.get("counter_id") or director_meta.get("counter_id") or DEFAULT_COUNTER_ID,
                narrator_meta.get("counter_mode") or director_meta.get("counter_mode") or "estimated", _now(),
            ),
        )
        updated = self.connection.execute("UPDATE generation_jobs SET final_context_json=? WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=(SELECT epoch FROM execution_epochs WHERE id=1)", (json.dumps(preview, ensure_ascii=False, sort_keys=True), job["id"]))
        if updated.rowcount != 1:
            raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))

    def _player_persona(self, job) -> dict:
        owner_id = job["owner_id"] if "owner_id" in job.keys() else None
        checkpoint = load_state_checkpoint(
            self.connection,
            job["campaign_id"],
            job["branch_id"],
            job["checkpoint_id"],
            owner_id,
        )
        return next(
            (profile["data"] for profile in _profiles(self.connection, job["campaign_id"], checkpoint.snapshot) if profile["kind"] == "persona"),
            {},
        )

    def _narrate(self, job, profile, preview, *, request=None):
        key = f"{job['id']}:narration"
        if request is None:
            settings = json.loads(job["settings_snapshot_json"] or "{}")
            _, request, _ = self._narrator_request(job, profile, preview, settings)
        self._insert_attempt(job, "narration", key, preview["payload_hash"], profile, request)
        if not self._mark_dispatched(key):
            raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt was claimed by another worker"))
        parts, result = [], None
        structured_required = bool(not profile.get("is_test_profile") and not profile.get("legacy_plain_output"))
        progress_emitted = False
        try:
            try:
                for event in self.attempt_registry.stream(
                    key,
                    None,
                    request,
                    self.timeout_seconds,
                    provider_factory=lambda _handle: self._provider_for_or_failure(job, "narration", profile),
                    invocation_gate=lambda _handle: self._invocation_gate(job["id"], key),
                    pre_invocation_gate=lambda _handle: self._claim_gate(job["id"], key),
                ):
                    if self._cancel_requested(job["id"]):
                        self.attempt_registry.cancel(job["id"])
                        raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))
                    if isinstance(event, ProviderFailure):
                        raise _ProviderError(event)
                    if isinstance(event, ProviderResult):
                        result = event
                        if structured_required:
                            if not parts and event.text:
                                self._append_private_structured_output(job["id"], key, event.text, progress=not progress_emitted)
                                progress_emitted = True
                                parts.append(event.text)
                        elif not parts and event.text:
                            self._append_output(job["id"], "narration", event.text, parts)
                    elif isinstance(event, str) and event:
                        if structured_required:
                            self._append_private_structured_output(job["id"], key, event, progress=not progress_emitted)
                            progress_emitted = True
                            parts.append(event)
                        else:
                            self._append_output(job["id"], "narration", event, parts)
            except TimeoutError as exc:
                code = "CANCELLED" if str(exc) == "cancelled" or self._cancel_requested(job["id"]) else "PROVIDER_TIMEOUT"
                raise _ProviderError(ProviderFailure(code, "Generation was cancelled" if code == "CANCELLED" else "Narration attempt exceeded its timeout"))
            if result is None:
                raise _ProviderError(ProviderFailure("MISSING_TERMINAL", "Provider did not return a terminal result"))
            if result.failure:
                raise _ProviderError(result.failure)
            if result.finish_reason != "stop":
                raise _ProviderError(ProviderFailure("OUTPUT_TRUNCATED" if result.finish_reason in {"length", "max_tokens"} else "MODEL_REFUSED", "Provider did not complete normally"))
            draft = "".join(parts)
            if not draft:
                raise _ProviderError(ProviderFailure("MISSING_TERMINAL", "Provider returned empty narrative"))
            selected = {}
            context = preview
            for item in context.get("selected_characters", []):
                if isinstance(item, dict) and isinstance(item.get("character_id"), str) and isinstance(item.get("profile_version_id"), str):
                    selected[item["character_id"]] = item["profile_version_id"]
            try:
                normalized_draft, output_segments = parse_narrator_payload(draft, selected)
                if narrator_requires_structured := (not profile.get("is_test_profile", False) and not profile.get("legacy_plain_output", False)):
                    if output_segments is None:
                        raise ValidationError("Narrator must return attributed structured segments")
                draft = normalized_draft
            except Exception as exc:
                failure = ProviderFailure("SCHEMA_INVALID", str(exc))
                with transaction(self.connection):
                    self._require_active(key, job["id"])
                    self._record_usage(job["id"], "narration", result)
                raise _ProviderError(failure) from exc
            try:
                if output_segments is not None:
                    validate_player_agency(job["action"], output_segments, self._player_persona(job))
            except PlayerAgencyViolation as exc:
                failure = ProviderFailure("PLAYER_AGENCY_VIOLATION", str(exc))
                with transaction(self.connection):
                    self._require_active(key, job["id"])
                    self._record_usage(job["id"], "narration", result)
                raise _ProviderError(failure) from exc
            try:
                if output_segments is not None:
                    validate_npc_knowledge(output_segments, preview)
            except NpcKnowledgeViolation as exc:
                failure = ProviderFailure("NPC_KNOWLEDGE_VIOLATION", str(exc))
                with transaction(self.connection):
                    self._require_active(key, job["id"])
                    self._record_usage(job["id"], "narration", result)
                raise _ProviderError(failure) from exc
            try:
                if output_segments is not None:
                    validate_grounded_precision(output_segments, preview)
            except GroundingViolation as exc:
                failure = ProviderFailure("UNGROUNDED_PRECISION", str(exc))
                with transaction(self.connection):
                    self._require_active(key, job["id"])
                    self._record_usage(job["id"], "narration", result)
                raise _ProviderError(failure) from exc
            with transaction(self.connection):
                self._require_active(key, job["id"])
                self._finish_attempt(key, "completed", result, "".join(parts))
                self._record_usage(job["id"], "narration", result)
                changed = self.connection.execute("UPDATE generation_jobs SET status='candidate',draft=?,output_segments_json=?,usage_json=? WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=(SELECT epoch FROM execution_epochs WHERE id=1)", (draft, json.dumps(output_segments, ensure_ascii=False) if output_segments is not None else None, json.dumps(result.usage or {"status": "unknown"}, ensure_ascii=False), job["id"]))
                if changed.rowcount != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job["id"],))
                self._event(job["id"], "narration", "completed", self._offset(draft), "", {"usage": result.usage or {"status": "unknown"}, "offset_unit": "utf16_code_units"})
            self._after_narration_completion(job["id"])
        except _ProviderError as exc:
            self._finish_attempt(key, "interrupted" if exc.failure.code == "CANCELLED" else "failed", exc.failure, "".join(parts))
            raise

    def _append_output(self, job_id, stage, text, parts):
        with self._db_lock:
            row = self.connection.execute("SELECT stage_key FROM provider_attempts WHERE generation_job_id=? AND stage=?", (job_id, stage)).fetchone()
            self._require_active(row["stage_key"], job_id)
            with transaction(self.connection):
                self._require_active(row["stage_key"], job_id)
                parts.append(text)
                output = "".join(parts)
                current = self._epoch()
                changed = self.connection.execute("UPDATE provider_attempts SET output_text=?,output_offset=? WHERE stage_key=? AND status='dispatched' AND claim_epoch=?", (output, self._offset(output), row["stage_key"], current)).rowcount
                if changed != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
                changed = self.connection.execute("UPDATE generation_jobs SET draft=? WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=?", (output, job_id, current)).rowcount
                if changed != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation is no longer active"))
                self._event(job_id, stage, "delta", self._offset(output), text, {"offset_unit": "utf16_code_units"})

    def _append_private_structured_output(self, job_id, stage_key, text, *, progress: bool):
        """Retain raw structured chunks privately while exposing safe progress only."""
        with self._db_lock:
            row = self.connection.execute("SELECT output_text FROM provider_attempts WHERE stage_key=?", (stage_key,)).fetchone()
            if row is None:
                raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
            raw = (row["output_text"] or "") + text
            with transaction(self.connection):
                self._require_active(stage_key, job_id)
                changed = self.connection.execute("UPDATE provider_attempts SET output_text=?,output_offset=? WHERE stage_key=? AND status='dispatched' AND claim_epoch=?", (raw, self._offset(raw), stage_key, self._epoch())).rowcount
                if changed != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
                if progress:
                    current = self._epoch()
                    self.connection.execute("UPDATE generation_jobs SET draft=? WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=?", ("Đang xử lý…", job_id, current))
                    self._event(job_id, "narration", "delta", self._offset("Đang xử lý…"), "Đang xử lý…", {"offset_unit": "utf16_code_units", "private_raw": True})

    def _after_narration_completion(self, job_id):
        """Test hook for the boundary after the narration completion commit."""
        return None

    def _insert_attempt(self, job, stage, key, payload_hash, profile, request):
        with self._db_lock:
            updated = self.connection.execute("UPDATE provider_attempts SET profile_snapshot_json=?,payload_hash=?,request_json=? WHERE generation_job_id=? AND stage=? AND status='queued'", (json.dumps(_copy(profile), sort_keys=True), payload_hash, json.dumps(_serializable_request(request), ensure_ascii=False, sort_keys=True), job["id"], stage))
            if updated.rowcount == 0:
                self.connection.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,request_json,output_text,output_offset,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), job["id"], stage, key, json.dumps(_copy(profile), sort_keys=True), payload_hash, "queued", json.dumps(_serializable_request(request), ensure_ascii=False, sort_keys=True), "", 0, _now()))

    def _mark_dispatched(self, key):
        with self._db_lock:
            row = self.connection.execute("SELECT generation_job_id,stage FROM provider_attempts WHERE stage_key=? AND status='queued'", (key,)).fetchone()
            if row is None:
                return False
            current = self._epoch()
            changed = self.connection.execute("UPDATE provider_attempts SET status='claimed',claim_epoch=? WHERE stage_key=? AND status='queued' AND EXISTS (SELECT 1 FROM generation_jobs WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=?)", (current, key, row["generation_job_id"], current)).rowcount
            if changed == 1:
                self._event(row["generation_job_id"], row["stage"], "phase_changed", None, "", {"phase": f"{row['stage']}_claimed"})
            return changed == 1

    def _invocation_gate(self, job_id, key):
        """Durably activate an owned claim immediately before provider I/O.

        Paid-trial permission is rechecked inside the SAME SQLite write
        transaction that marks the attempt dispatched. Revoking the grant
        before this boundary cannot race past an earlier read-only preflight.
        """
        with self._db_lock:
            with transaction(self.connection):
                current = self._epoch()
                row = self.connection.execute("SELECT a.stage,a.status,a.claim_epoch,j.status AS job_status,j.execution_epoch,j.cancel_requested FROM provider_attempts a JOIN generation_jobs j ON j.id=a.generation_job_id WHERE a.stage_key=? AND j.id=?", (key, job_id)).fetchone()
                if row is None or row["claim_epoch"] != current or row["execution_epoch"] != current or row["job_status"] not in {"running", "queued"} or row["cancel_requested"]:
                    return False
                if row["status"] == "dispatched":
                    return True
                if row["status"] != "claimed":
                    return False
                job = self.connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
                if job is None:
                    return False
                # The approval boundary is checked again in the same
                # transaction that flips claimed -> dispatched. This closes
                # the race where an imported campaign is revoked after the
                # recovery precheck but before provider I/O.
                try:
                    assert_import_review_approved(self.connection, job["owner_id"], job["campaign_id"], job["checkpoint_id"])
                except (ValidationError, StateConflict):
                    return False
                if job["policy"] in {"capped_paid", "free_only"}:
                    try:
                        profiles = json.loads(job["profile_snapshot_json"] or "{}")
                        narrator = profiles.get("narrator") or {}
                        if requires_spending_authorization(narrator):
                            if job["policy"] == "free_only":
                                # Protect jobs queued under older code, too.
                                # No verified Ollama purchased-credit lockout.
                                return False
                            persisted, _ = self._persisted_config(job["owner_id"])
                            if persisted is not None:
                                assert_trial_dispatch_allowed(self.connection, job, profile=narrator)
                    except (ValidationError, ValueError, TypeError):
                        return False
                changed = self.connection.execute("UPDATE provider_attempts SET status='dispatched',dispatched_at=? WHERE stage_key=? AND status='claimed' AND claim_epoch=? AND EXISTS (SELECT 1 FROM generation_jobs WHERE id=? AND status='running' AND execution_epoch=? AND cancel_requested=0)", (_now(), key, current, job_id, current)).rowcount
                if changed == 1:
                    self._event(job_id, row["stage"], "phase_changed", None, "", {"phase": f"{row['stage']}_dispatched"})
                    return True
                return False

    def _claim_gate(self, job_id, key):
        """Read-only post-slot eligibility check before credential resolution."""
        with self._db_lock:
            current = self._epoch()
            row = self.connection.execute("SELECT a.status,a.claim_epoch,j.status AS job_status,j.execution_epoch,j.cancel_requested FROM provider_attempts a JOIN generation_jobs j ON j.id=a.generation_job_id WHERE a.stage_key=? AND j.id=?", (key, job_id)).fetchone()
            return bool(row and row["status"] == "claimed" and row["claim_epoch"] == current and row["execution_epoch"] == current and row["job_status"] in {"running", "queued"} and not row["cancel_requested"])

    @staticmethod
    def _offset(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    def _require_active(self, key, job_id):
        with self._db_lock:
            row = self.connection.execute("SELECT a.status,a.claim_epoch,j.status AS job_status,j.execution_epoch,j.cancel_requested FROM provider_attempts a JOIN generation_jobs j ON j.id=a.generation_job_id WHERE a.stage_key=? AND j.id=?", (key, job_id)).fetchone()
            current = self._epoch()
            if row is None or row["status"] != "dispatched" or row["job_status"] != "running" or row["claim_epoch"] != current or row["execution_epoch"] != current or row["cancel_requested"]:
                raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))

    def _record_usage(self, job_id, stage, result):
        row = self.connection.execute("SELECT reserved_cost_json,profile_snapshot_json FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return
        ledger = json.loads(row["reserved_cost_json"] or "{}")
        entry = (ledger.get("stages") or {}).get(stage)
        if entry is None:
            return
        usage = result.usage if isinstance(result, ProviderResult) else None
        entry["usage"] = usage or {"status": "unknown"}
        profile_snapshot = json.loads(row["profile_snapshot_json"] or "{}").get("context" if stage == "context" else "narrator", {})
        reported = provider_reported_cost(usage)
        calculated = calculated_usage_cost(profile_snapshot, usage)
        entry["provider_reported_cost_usd"] = str(reported) if reported is not None else None
        entry["provider_reported_status"] = "provider_reported" if reported is not None else "unknown"
        entry["calculated_cost_usd"] = str(calculated) if calculated is not None else None
        entry["calculated_status"] = "calculated" if calculated is not None else "unknown"
        if reported is not None:
            entry["actual_cost_usd"] = str(reported)
            entry["actual_status"] = "provider_reported"
            entry["cost_provenance"] = "provider_reported"
        elif calculated is not None:
            entry["actual_cost_usd"] = None
            entry["actual_status"] = "calculated"
            entry["cost_provenance"] = "calculated"
        else:
            entry["actual_cost_usd"] = None
            entry["actual_status"] = "unknown"
            entry["cost_provenance"] = "provider_managed_unknown" if entry.get("cost_provenance") == "provider_managed_unknown" else "unknown"
        provider_total = Decimal("0")
        calculated_total = Decimal("0")
        stage_values = list((ledger.get("stages") or {}).values())
        for value in stage_values:
            if value.get("provider_reported_cost_usd") is not None:
                provider_total += Decimal(str(value["provider_reported_cost_usd"]))
            if value.get("calculated_cost_usd") is not None:
                calculated_total += Decimal(str(value["calculated_cost_usd"]))
        ledger["provider_reported_total_usd"] = str(provider_total) if stage_values and all(value.get("provider_reported_cost_usd") is not None for value in stage_values) else None
        ledger["calculated_total_usd"] = str(calculated_total) if stage_values and all(value.get("calculated_cost_usd") is not None for value in stage_values) else None
        ledger["actual_total_usd"] = ledger["provider_reported_total_usd"]
        ledger["actual_status"] = "provider_reported" if ledger["actual_total_usd"] is not None else "calculated" if ledger["calculated_total_usd"] is not None else "unknown"
        self.connection.execute("UPDATE generation_jobs SET reserved_cost_json=? WHERE id=?", (json.dumps(ledger, sort_keys=True), job_id))

    def _finish_attempt(self, key, status, result, output):
        usage = result.usage if isinstance(result, ProviderResult) else {"status": "unknown"}
        failure = result if isinstance(result, ProviderFailure) else None
        changed = self.connection.execute("UPDATE provider_attempts SET status=?,output_text=?,output_offset=?,usage_json=?,failure_json=?,finished_at=? WHERE stage_key=? AND status IN ('claimed','dispatched') AND claim_epoch=(SELECT epoch FROM execution_epochs WHERE id=1)", (status, output, self._offset(output), json.dumps(usage or {"status": "unknown"}), json.dumps({"code": failure.code, "message": failure.message}) if failure else None, _now(), key)).rowcount
        self._attempt_cancel_events.pop(key, None)
        return changed

    def _finish_active_attempt(self, key, job_id, status, result, output):
        """Finish a provider result only while its claim is still current."""
        with transaction(self.connection):
            self._require_active(key, job_id)
            changed = self._finish_attempt(key, status, result, output)
            if changed != 1:
                raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))
            return changed

    def _fail(self, job_id, failure):
        changed = self.connection.execute("UPDATE generation_jobs SET status=?,failure_json=? WHERE id=? AND status IN ('queued','running','cancelling')", ("cancelled" if failure.code == "CANCELLED" else "failed", json.dumps({"code": failure.code, "message": failure.message}, ensure_ascii=False), job_id)).rowcount
        if changed != 1:
            return
        self.connection.execute("UPDATE provider_attempts SET status='interrupted',failure_json=?,finished_at=? WHERE generation_job_id=? AND status IN ('queued','claimed')", (json.dumps({"code": failure.code, "message": failure.message}, ensure_ascii=False), _now(), job_id))
        self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
        for key, event in list(self._attempt_cancel_events.items()):
            if key.startswith(f"{job_id}:"):
                event.set()
                self._attempt_cancel_events.pop(key, None)
        self._event(job_id, None, "failed", None, "", {"code": failure.code, "message": failure.message})

    def _cancel_requested(self, job_id):
        row = self.connection.execute("SELECT cancel_requested FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def cancel(self, owner_id, job_id):
        job = self.get_job(owner_id, job_id)
        with transaction(self.connection):
            get_branch_head(self.connection, job["campaign_id"], job["branch_id"], owner_id)
            active = self.connection.execute("SELECT COUNT(*) AS n FROM provider_attempts WHERE generation_job_id=? AND status='dispatched'", (job_id,)).fetchone()["n"]
            status = "cancelling" if active else "cancelled"
            self.connection.execute("UPDATE generation_jobs SET cancel_requested=1,status=? WHERE id=? AND owner_id=? AND status IN ('queued','running','candidate')", (status, job_id, owner_id))
            self.attempt_registry.cancel(job_id)
            for key, event in self._attempt_cancel_events.items():
                if key.startswith(f"{job_id}:"):
                    event.set()
            self.connection.execute("UPDATE provider_attempts SET status='interrupted',finished_at=?,failure_json=? WHERE generation_job_id=? AND status IN ('queued','claimed')", (_now(), json.dumps({"code": "CANCELLED", "message": "Generation was cancelled"}), job_id))
            if not active:
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
            self._event(job_id, None, "cancelled", None, "", {})
        return self._job(job_id)

    def edit_draft(self, owner_id, job_id, draft: str):
        job = self.get_job(owner_id, job_id)
        if not isinstance(draft, str):
            raise ValidationError("Draft must be text")
        with transaction(self.connection):
            get_branch_head(self.connection, job["campaign_id"], job["branch_id"], owner_id)
            if job["status"] in {"candidate", "committed"}:
                raise ValidationError("Complete candidates cannot be edited as drafts")
            self.connection.execute("UPDATE generation_jobs SET draft=? WHERE id=? AND owner_id=? AND status NOT IN ('candidate','committed')", (draft, job_id, owner_id))
            self._event(job_id, None, "draft_edited", self._offset(draft), "", {"offset_unit": "utf16_code_units"})
        return self._job(job_id)

    def recover_after_restart(self):
        with transaction(self.connection):
            current_epoch = str(uuid4())
            self.connection.execute("UPDATE execution_epochs SET epoch=?,created_at=? WHERE id=1", (current_epoch, _now()))
            jobs = self.connection.execute("SELECT generation_job_id FROM provider_attempts WHERE status IN ('claimed','dispatched')").fetchall()
            self.connection.execute("UPDATE provider_attempts SET status='interrupted',failure_json=?,finished_at=? WHERE status IN ('claimed','dispatched')", (json.dumps({"code": "PROVIDER_INTERRUPTED", "message": "Process restarted while provider call was ambiguous"}), _now()))
            running = self.connection.execute("SELECT id,final_context_json FROM generation_jobs WHERE status='running'").fetchall()
            self.connection.execute("UPDATE generation_jobs SET status='interrupted' WHERE status='running'")
            for job in jobs:
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job["generation_job_id"],))
            for job in running:
                queued = self.connection.execute("SELECT 1 FROM provider_attempts WHERE generation_job_id=? AND status='queued'", (job["id"],)).fetchone()
                dispatched = self.connection.execute("SELECT 1 FROM provider_attempts WHERE generation_job_id=? AND status='dispatched'", (job["id"],)).fetchone()
                if queued and not dispatched and job["final_context_json"]:
                    self.connection.execute("UPDATE generation_jobs SET status='queued',execution_epoch=? WHERE id=?", (current_epoch, job["id"]))
            self.connection.execute("UPDATE generation_jobs SET execution_epoch=? WHERE status='queued' AND execution_epoch<>?", (current_epoch, current_epoch))

    startup_recover = recover_after_restart

    def _event(self, job_id, stage, event_type, offset, content, payload):
        with self._db_lock:
            self.connection.execute("INSERT INTO generation_events(generation_job_id,stage,event_type,offset,content,payload_json,created_at) VALUES(?,?,?,?,?,?,?)", (job_id, stage, event_type, offset, content, json.dumps(payload, ensure_ascii=False, sort_keys=True), _now()))

    def events(self, owner_id, job_id, *, after=0):
        self.get_job(owner_id, job_id)
        return self._events_raw(job_id, after=after)

    def _events_raw(self, job_id, *, after=0):
        rows = self.connection.execute("SELECT id,stage,event_type,offset,content,payload_json,created_at FROM generation_events WHERE generation_job_id=? AND id>? ORDER BY id", (job_id, after)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def content(self, owner_id, job_id):
        job = self.get_job(owner_id, job_id)
        return {"job_id": job_id, "status": job["status"], "draft": job.get("draft", ""), "offset": self._offset(job.get("draft", "")), "offset_unit": "utf16_code_units", "failure": job.get("failure")}

    def get_job_by_key(self, owner_id, branch_id, idempotency_key):
        row = self.connection.execute("SELECT id FROM generation_jobs WHERE owner_id=? AND branch_id=? AND operation='generation' AND idempotency_key=?", (owner_id, branch_id, idempotency_key)).fetchone()
        if row is None:
            raise NotFound("Generation job not found")
        return self._job(row["id"])

    def _job(self, job_id):
        row = self.connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFound("Generation job not found")
        values = dict(row)
        values["failure"] = json.loads(values["failure_json"]) if values.get("failure_json") else None
        values["usage"] = json.loads(values["usage_json"]) if values.get("usage_json") else None
        values["output_segments"] = json.loads(values["output_segments_json"]) if values.get("output_segments_json") else None
        values["settings_snapshot"] = json.loads(values.get("settings_snapshot_json") or "{}")
        values["profile_snapshot"] = json.loads(values.get("profile_snapshot_json") or "{}")
        values["cost_ledger"] = json.loads(values.get("reserved_cost_json") or "{}")
        values["remaining_cost_usd"] = self._remaining_cost(values)
        attempts = self.connection.execute("SELECT stage,status,stage_key,output_offset,output_text,usage_json,failure_json,payload_hash,profile_snapshot_json,request_json,dispatched_at,claim_epoch,finished_at FROM provider_attempts WHERE generation_job_id=? ORDER BY created_at", (job_id,)).fetchall()
        values["attempts"] = [item["stage"] for item in attempts]
        attempt_details = []
        for item in attempts:
            detail = {**dict(item), "usage": json.loads(item["usage_json"]) if item["usage_json"] else None, "failure": json.loads(item["failure_json"]) if item["failure_json"] else None, "profile_snapshot": json.loads(item["profile_snapshot_json"]), "request": json.loads(item["request_json"] or "{}") if item["request_json"] else {}}
            detail.pop("output_text", None)
            attempt_details.append(detail)
        values["attempt_details"] = attempt_details
        phase_counts = {phase: sum(1 for item in attempts if item["status"] == phase) for phase in ("queued", "claimed", "dispatched", "completed", "failed", "interrupted")}
        values["attempt_counts"] = {"planned": len(attempts), **phase_counts}
        values["attempt_counts_by_stage"] = {stage: {phase: sum(1 for item in attempts if item["stage"] == stage and item["status"] == phase) for phase in ("queued", "claimed", "dispatched", "completed", "failed", "interrupted")} for stage in {item["stage"] for item in attempts}}
        values["planned_attempts"] = len(attempts)
        values["claimed_attempts"] = phase_counts["claimed"]
        values["dispatched_attempts"] = phase_counts["dispatched"]
        values["completed_attempts"] = phase_counts["completed"]
        values["events"] = self._events_raw(job_id)
        return values

    @staticmethod
    def _remaining_cost(job) -> str | None:
        ledger = job.get("cost_ledger") or {}
        cap = ledger.get("cap")
        if cap is None:
            return None
        remaining = Decimal(str(cap))
        for entry in (ledger.get("stages") or {}).values():
            remaining -= conservative_ledger_cost(entry) or Decimal("0")
        return str(max(Decimal("0"), remaining))

    def get_job(self, owner_id, job_id):
        row = self.connection.execute("SELECT owner_id FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["owner_id"] != owner_id:
            raise NotFound("Generation job not found")
        return self._job(job_id)

    def commit_candidate(self, owner_id, job_id):
        job = self.get_job(owner_id, job_id)
        if job["status"] == "candidate":
            selected = {}
            selected_context = json.loads(job.get("final_context_json") or job.get("preview_snapshot_json") or "{}")
            for item in selected_context.get("selected_characters", []):
                if isinstance(item, dict) and isinstance(item.get("character_id"), str) and isinstance(item.get("profile_version_id"), str):
                    selected[item["character_id"]] = item["profile_version_id"]
            output_segments = job.get("output_segments")
            if output_segments is None:
                _, output_segments = parse_narrator_payload(job["draft"], selected)
            if output_segments is not None:
                try:
                    validate_player_agency(job["action"], output_segments, self._player_persona(job))
                    validate_npc_knowledge(output_segments, selected_context)
                    validate_grounded_precision(output_segments, selected_context)
                except (PlayerAgencyViolation, NpcKnowledgeViolation, GroundingViolation) as exc:
                    if isinstance(exc, PlayerAgencyViolation):
                        failure_code = "PLAYER_AGENCY_VIOLATION"
                    elif isinstance(exc, NpcKnowledgeViolation):
                        failure_code = "NPC_KNOWLEDGE_VIOLATION"
                    else:
                        failure_code = "UNGROUNDED_PRECISION"
                    failure = {
                        "code": failure_code,
                        "message": str(exc),
                    }
                    with transaction(self.connection):
                        changed = self.connection.execute(
                            "UPDATE generation_jobs SET status='failed',failure_json=? WHERE id=? AND owner_id=? AND status='candidate'",
                            (json.dumps(failure, ensure_ascii=False), job_id, owner_id),
                        ).rowcount
                        if changed == 1:
                            self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
                            self._event(job_id, None, "failed", None, "", failure)
                    raise
        with transaction(self.connection):
            head = get_branch_head(self.connection, job["campaign_id"], job["branch_id"], owner_id)
            if job["status"] == "committed":
                return self._job(job_id)
            if job["status"] != "candidate":
                raise ValidationError("Only a complete candidate can be committed")
            if head.checkpoint_id != job["checkpoint_id"]:
                raise StateConflict("Candidate is stale")
            competing = self.connection.execute("SELECT generation_job_id FROM generation_branch_guards WHERE branch_id=? AND generation_job_id<>?", (job["branch_id"], job_id)).fetchone()
            if competing:
                raise StateConflict("An active generation owns this branch")
            selected = {}
            selected_context = json.loads(job.get("final_context_json") or job.get("preview_snapshot_json") or "{}")
            for item in selected_context.get("selected_characters", []):
                if isinstance(item, dict) and isinstance(item.get("character_id"), str) and isinstance(item.get("profile_version_id"), str):
                    selected[item["character_id"]] = item["profile_version_id"]
            output_segments = job.get("output_segments")
            if output_segments is not None:
                validate_narrator_segments(output_segments, selected)
                narrative_text = job["draft"]
            else:
                narrative_text, output_segments = parse_narrator_payload(job["draft"], selected)
            _create_committed_revision_in_transaction(self.connection, job["campaign_id"], job["branch_id"], job["action"], narrative_text, expected_state_version=head.state_version, output_segments=output_segments)
            if self.connection.execute("UPDATE generation_jobs SET status='committed' WHERE id=? AND status='candidate'", (job_id,)).rowcount != 1:
                raise StateConflict("Candidate was already committed")
            self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
            self._event(job_id, "narration", "committed", self._offset(job["draft"]), "", {"offset_unit": "utf16_code_units"})
        return self._job(job_id)


class DurableGenerationWorker:
    """Small process-worker facade used by startup loops and tests.

    It intentionally delegates all state transitions to ``GenerationService``
    so HTTP requests, a background worker and a restarted worker share the same
    idempotency, guard and epoch rules.
    """

    def __init__(self, service: GenerationService):
        self.service = service

    def run_once(self, limit: int = 1) -> list[dict]:
        return self.service.run_queued(limit=limit)

    def recover(self) -> None:
        self.service.recover_after_restart()


class GenerationRuntime:
    """Shared application worker independent from request/stream lifetime."""

    def __init__(self, database_url, provider, *, profile=None, provider_factory=None, credential_resolver=None, attempt_registry=None, context_counter=None, context_counter_id: str = DEFAULT_COUNTER_ID, poll_seconds: float = 0.05):
        from threading import Event, Thread
        from .db import connect
        self._connect = connect
        self.connection = connect(database_url)
        self.attempt_registry = attempt_registry or PhysicalAttemptRegistry()
        self.service = GenerationService(self.connection, provider, profile=profile, provider_factory=provider_factory, credential_resolver=credential_resolver, attempt_registry=self.attempt_registry, context_counter=context_counter, context_counter_id=context_counter_id)
        self.poll_seconds = poll_seconds
        self._stop = Event()
        self._thread = None

    def start(self):
        from threading import Thread
        if self._thread and self._thread.is_alive():
            return
        self.service.recover_after_restart()
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="playroom-generation-worker", daemon=True)
        self._thread.start()

    def _loop(self):
        from time import sleep
        while not self._stop.is_set():
            try:
                self.service.run_queued(limit=1)
            except Exception:
                # Job-level failures are persisted by GenerationService. A
                # transient database lock leaves queued work durable, while
                # the exception remains observable to operators.
                logger.exception("generation worker iteration failed")
            sleep(self.poll_seconds)

    def stop(self):
        if self._thread:
            self._stop.set()
            self.attempt_registry.shutdown()
            self._thread.join(timeout=2)
            if self._thread.is_alive() or self.attempt_registry.active():
                return False
        self.connection.close()
        return True
