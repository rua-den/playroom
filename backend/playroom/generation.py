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
from threading import Event
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from jsonschema import Draft202012Validator

from .context import build_candidate_pool, build_context_preview, _profiles
from .db import transaction
from .domain import NotFound, StateConflict, ValidationError
from .model_profiles import estimate_cost_usd, validate_dispatch
from .provider import ProviderAdapter, ProviderFailure, ProviderResult
from .context_director import deterministic_selection, validate_director_plan
from .timeline import _create_committed_revision_in_transaction, get_branch_head, load_state_checkpoint

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
    "required": ["checkpoint_id", "action_hash", "selected_memory_ids", "reasons", "reason_sources", "scene_ids", "conflict_flags"],
    "properties": {
        "checkpoint_id": {"type": "string"}, "action_hash": {"type": "string"},
        "selected_memory_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "uniqueItems": True},
        "reasons": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 180}},
        "reason_sources": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        "scene_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "conflict_flags": {"type": "array", "items": {"type": "string", "maxLength": 160}},
    },
}


class _ProviderError(Exception):
    def __init__(self, failure: ProviderFailure):
        self.failure = failure


class GenerationService:
    """Durable worker with one immutable parent and one attempt per stage."""

    def __init__(self, connection: sqlite3.Connection, provider: ProviderAdapter, *, profile: dict | None = None, settings: dict | None = None, timeout_seconds: float = 300.0, provider_factory=None, credential_resolver=None):
        self.connection, self.provider = connection, provider
        self.timeout_seconds = timeout_seconds
        self.profile = _copy(profile or DEFAULT_PROFILE)
        self.settings = _copy(settings or {})
        self.provider_factory = provider_factory
        self.credential_resolver = credential_resolver
        self._attempt_cancel_events: dict[str, Event] = {}
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

    def _epoch(self) -> str:
        return self.connection.execute("SELECT epoch FROM execution_epochs WHERE id=1").fetchone()["epoch"]

    def _reservation(self, profiles: dict, mode: str, policy: str, cap) -> dict:
        stages = ["narration"] if mode == "economy" else ["context", "narration"]
        entries, total = {}, Decimal("0")
        for stage in stages:
            profile = profiles["context" if stage == "context" else "narrator"]
            input_tokens = 12000
            output_tokens = min(4000, int(profile.get("output_limit", 4000)))
            if policy == "free_only":
                validate_dispatch(profile, policy, {"input_tokens": 0, "completion_tokens": output_tokens}, None)
            elif policy == "capped_paid":
                if cap is None:
                    raise ValidationError("A confirmed USD cap is required")
                total += estimate_cost_usd(profile, input_tokens, output_tokens)
            entries[stage] = {"reserved_input_tokens": input_tokens, "reserved_output_tokens": output_tokens, "estimated_cost_usd": str(estimate_cost_usd(profile, input_tokens, output_tokens)), "actual_cost_usd": None, "usage": None}
        if policy == "capped_paid" and total > Decimal(str(cap)):
            raise ValidationError("Aggregate generation estimate exceeds the confirmed USD cap")
        return {"policy": policy, "cap": str(cap) if cap is not None else None, "stages": entries, "reserved_total_usd": str(total), "actual_total_usd": None}

    def _request_hash(self, campaign_id, branch_id, action, checkpoint_id, preview_id, idempotency_key, mode, policy, cap):
        # Recovery identity is derived only from the submitted request. Live
        # settings/profiles/keys are intentionally absent and may change later.
        return _hash({"campaign_id": campaign_id, "branch_id": branch_id, "action": action, "checkpoint_id": checkpoint_id, "preview_id": preview_id, "idempotency_key": idempotency_key, "mode": mode, "policy": policy, "cap": str(cap) if cap is not None else None})

    def generate(self, owner_id: str, campaign_id: str, branch_id: str, action: str, *, idempotency_key: str, expected_checkpoint_id: str, preview_id: str | None = None, mode: str = "economy", policy: str = "free_only", cap=None, execute: bool = True) -> dict:
        if mode not in {"economy", "quality"}:
            raise ValidationError("Unknown generation mode")
        if not action.strip() or not idempotency_key.strip():
            raise ValidationError("Action and idempotency key are required")
        request_hash = self._request_hash(campaign_id, branch_id, action, expected_checkpoint_id, preview_id, idempotency_key, mode, policy, cap)
        existing = self.connection.execute("SELECT id,request_hash FROM generation_jobs WHERE owner_id=? AND branch_id=? AND operation='generation' AND idempotency_key=?", (owner_id, branch_id, idempotency_key)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise StateConflict("Conflicting idempotency payload")
            return self._job(existing["id"])
        preview_snapshot = None
        if preview_id is not None:
            preview_row = self.connection.execute("SELECT payload_json FROM context_previews WHERE id=? AND owner_id=?", (preview_id, owner_id)).fetchone()
            if preview_row is None:
                raise NotFound("Context preview not found")
            preview_snapshot = json.loads(preview_row["payload_json"])
            if (preview_snapshot.get("campaign_id"), preview_snapshot.get("branch_id"), preview_snapshot.get("action"), preview_snapshot.get("checkpoint_id")) != (campaign_id, branch_id, action, expected_checkpoint_id):
                raise StateConflict("Submitted context preview does not match generation identity")
            if preview_snapshot.get("status") != "ready":
                raise ValidationError("Only a ready context preview can be submitted")
        profiles = self._profiles()
        settings = _copy(self.settings)
        settings.update({"mode": mode, "policy": policy, "confirmed_usd_cap": str(cap) if cap is not None else settings.get("confirmed_usd_cap")})
        head = get_branch_head(self.connection, campaign_id, branch_id, owner_id)
        if head.checkpoint_id != expected_checkpoint_id:
            raise StateConflict("Generation checkpoint is stale")
        job_id, created = str(uuid4()), _now()
        with transaction(self.connection):
            # Recheck ownership/head while the reservation lock is held.
            locked_head = get_branch_head(self.connection, campaign_id, branch_id, owner_id)
            if locked_head.checkpoint_id != expected_checkpoint_id:
                raise StateConflict("Generation checkpoint is stale")
            if self.connection.execute("SELECT 1 FROM generation_branch_guards WHERE branch_id=?", (branch_id,)).fetchone():
                raise StateConflict("A generation is already active on this branch")
            # A persistent count prevents multiple application workers from
            # exceeding the two upstream attempt contract.
            count = self.connection.execute("SELECT COUNT(*) AS n FROM provider_attempts WHERE status='dispatched'").fetchone()["n"]
            if count >= 2:
                raise StateConflict("Provider concurrency limit reached")
            if preview_snapshot is None:
                narrator = profiles["narrator"]
                preview_config = {"profile_id": narrator.get("id"), "context_window": narrator.get("context_limit", 12000), "input_limit": narrator.get("context_limit", 12000), "output_limit": narrator.get("output_limit", 4000), "wrapper_buffer": narrator.get("wrapper_buffer", 512), "requested_output": min(4000, narrator.get("output_limit", 4000)), "is_test_profile": bool(narrator.get("is_test_profile")), "capabilities_verified": bool(narrator.get("capabilities_verified", True))}
                preview_snapshot = build_context_preview(self.connection, campaign_id, branch_id, action, preview_config, owner_id=owner_id, settings_hash=_hash(settings))
            if preview_snapshot.get("checkpoint_id") != expected_checkpoint_id or preview_snapshot.get("action") != action:
                raise StateConflict("Submitted context preview is stale")
            if preview_snapshot.get("status") == "blocked":
                raise ValidationError(preview_snapshot.get("failure") or "Required context exceeds the verified input budget")
            reservation = self._reservation(profiles, mode, policy, cap)
            self.connection.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,action,status,mode,policy,created_at,settings_snapshot_json,profile_snapshot_json,execution_epoch,cancel_requested,reserved_cost_json,preview_id,preview_snapshot_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, owner_id, campaign_id, branch_id, "generation", idempotency_key, request_hash, expected_checkpoint_id, action, "queued", mode, policy, created, json.dumps(settings, sort_keys=True), json.dumps(profiles, sort_keys=True), self._epoch(), 0, json.dumps(reservation, sort_keys=True), preview_id, json.dumps(preview_snapshot, ensure_ascii=False, sort_keys=True)))
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

    def _execute(self, job) -> None:
        profiles, settings = json.loads(job["profile_snapshot_json"]), json.loads(job["settings_snapshot_json"])
        narrator, context = profiles["narrator"], profiles["context"]
        saved_preview = job["preview_snapshot_json"] if "preview_snapshot_json" in job.keys() else None
        if saved_preview:
            preview = json.loads(saved_preview)
        else:
            config = {"profile_id": narrator.get("id"), "context_window": narrator.get("context_limit", 12000), "input_limit": narrator.get("context_limit", 12000), "output_limit": narrator.get("output_limit", 4000), "wrapper_buffer": narrator.get("wrapper_buffer", 512), "requested_output": min(4000, narrator.get("output_limit", 4000)), "is_test_profile": bool(narrator.get("is_test_profile")), "capabilities_verified": bool(narrator.get("capabilities_verified", True))}
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
        if job["mode"] == "quality" and context_attempt and context_attempt["status"] == "completed" and saved_context:
            final_preview = json.loads(saved_context)
        elif job["mode"] == "quality":
            self._check_dispatch(job, context, narrator, preview, aggregate=True)
            request = {"stage": "context", "messages": self._director_messages(job["action"], pool), "reserved_completion_tokens": min(4000, int(context.get("output_limit", 4000))), "model": context.get("model"), "checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"]}
            key = f"{job['id']}:context"
            request["cancel_event"] = Event()
            self._attempt_cancel_events[key] = request["cancel_event"]
            self._insert_attempt(job, "context", key, _hash(_serializable_request(request)), context, request)
            self._mark_dispatched(key)
            self._event(job["id"], "context", "phase_changed", None, "", {"phase": "context_dispatched"})
            context_provider = self._provider_for(job, "context", context)
            context_started = time.monotonic()
            result = context_provider.generate_structured(request, SELECTION_SCHEMA)
            if time.monotonic() - context_started > self.timeout_seconds:
                context_provider.cancel(request)
                raise _ProviderError(ProviderFailure("PROVIDER_TIMEOUT", "Context director exceeded its timeout"))
            self._require_active(key, job["id"])
            if isinstance(result, ProviderFailure):
                self._finish_attempt(key, "failed", result, "")
                raise _ProviderError(result)
            try:
                value = json.loads(result.text)
                Draft202012Validator(SELECTION_SCHEMA).validate(value)
                plan = validate_director_plan(pool, pool["checkpoint_id"], pool["action_hash"], value)
            except Exception as exc:
                failure = ProviderFailure("SCHEMA_INVALID", str(exc))
                self._finish_attempt(key, "failed", failure, "")
                raise _ProviderError(failure)
            final_preview = self._pack_selected(preview, plan, narrator, director_selected_only=True)
            with transaction(self.connection):
                self._require_active(key, job["id"])
                if self._finish_attempt(key, "completed", result, json.dumps(plan, ensure_ascii=False, sort_keys=True)) != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))
                self._save_context_run(job, final_preview, result.usage)
            self._event(job["id"], "context", "phase_changed", None, "", {"phase": "context_completed", "selected_memory_ids": plan["selected_memory_ids"]})
            self._check_dispatch(job, context, narrator, final_preview, aggregate=False)
        else:
            final_preview = self._pack_selected(preview, plan, narrator)
            self._save_context_run(job, final_preview, {"status": "not_called", "mode": "economy"})
        self._check_dispatch(job, context, narrator, final_preview, aggregate=False)
        self._narrate(job, narrator, final_preview)

    def _check_dispatch(self, job, context, narrator, preview, *, aggregate: bool):
        tokens = int((preview.get("budget") or {}).get("input_tokens") or 0)
        out = min(4000, int(narrator.get("output_limit", 4000)))
        wire = json.dumps({"system": "Continue the story in Vietnamese using only supplied context.", "action": preview.get("action", ""), "blocks": preview.get("blocks", [])}, ensure_ascii=False, sort_keys=True)
        wire_tokens = max(tokens, (len(wire) + 3) // 4)
        input_cap = min(int(narrator.get("input_limit", narrator.get("context_limit", 12000))), int(narrator.get("context_limit", 12000)) - out - int(narrator.get("wrapper_buffer", 512)))
        if wire_tokens > input_cap:
            raise ValidationError("Final serialized provider wire exceeds the verified input budget")
        tokens = wire_tokens
        if job["policy"] == "capped_paid":
            cap = json.loads(job["settings_snapshot_json"]).get("confirmed_usd_cap")
            if cap is None:
                raise ValidationError("A confirmed USD cap is required")
            chosen = [context, narrator] if aggregate else [narrator]
            total = sum((estimate_cost_usd(p, tokens, out) for p in chosen), Decimal("0"))
            remaining = Decimal(str(cap))
            if not aggregate and job["mode"] == "quality":
                ledger = json.loads(job["reserved_cost_json"] or "{}")
                context_entry = (ledger.get("stages") or {}).get("context") or {}
                # Unknown director usage retains its conservative reservation.
                remaining -= Decimal(str(context_entry.get("actual_cost_usd") or context_entry.get("estimated_cost_usd") or "0"))
            if total > remaining:
                raise ValidationError("Aggregate generation estimate exceeds the confirmed USD cap")
            for profile in chosen:
                validate_dispatch(profile, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, remaining)
        else:
            validate_dispatch(narrator, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, None)
            if job["mode"] == "quality":
                validate_dispatch(context, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, None)

    def _director_messages(self, action, pool):
        payload = {"action": action, "checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"], "candidate_pool": {"mandatory": pool.get("mandatory", []), "optional": pool.get("optional", []), "scene_ids": pool.get("scene_ids", []), "omission_reasons": pool.get("omission_reasons", [])}}
        # The director gets bounded, source-grounded recent raw history in
        # addition to the candidate pool; it never receives an unbounded DB.
        payload["recent_context"] = pool.get("recent_context", [])[-8:]
        return [{"role": "system", "content": "Return only a SelectionPlan JSON. Select supplied IDs and cite each source."}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]

    def _provider_for(self, job, stage, profile):
        secret = None
        if self.credential_resolver is not None and (self.provider_factory is not None or self.provider.__class__.__name__ != "FakeProvider"):
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

    def _pack_selected(self, preview, plan, profile, *, director_selected_only=False):
        base = [b for b in preview.get("blocks", []) if b.get("mandatory")] if director_selected_only else list(preview.get("blocks", []))
        blocks, known = base, {b["id"] for b in base}
        by_id = {item["id"]: item for item in plan.get("optional", [])}
        for memory_id in plan.get("selected_memory_ids", []):
            item = by_id.get(memory_id)
            if item and memory_id not in known:
                blocks.append({"id": memory_id, "type": "memory", "text": item["text"], "source_ids": [item.get("version_id"), *item.get("source_revision_ids", [])], "mandatory": False, "why": plan["reasons"][memory_id], "knowledge_scope": item.get("knowledge_scope"), "known_by": item.get("known_by", []), "as_of_cursor": item.get("effective_cursor")})
                actor_ids = {*item.get("entity_ids", []), *item.get("known_by", [])}
                checkpoint = load_state_checkpoint(self.connection, preview["campaign_id"], preview["branch_id"], preview["checkpoint_id"])
                for actor in _profiles(self.connection, preview["campaign_id"], checkpoint.snapshot):
                    if actor["kind"] == "character" and actor["key"].partition(":")[2] in actor_ids and actor["id"] not in known:
                        blocks.append({"id": actor["id"], "type": "character", "text": actor["text"], "source_ids": actor["source_ids"], "mandatory": False, "why": "Character profile required by selected memory association.", "actor_id": actor["key"].partition(":")[2], "dependent_memory_id": memory_id})
                        known.add(actor["id"])
        packed = _copy(preview)
        packed["blocks"], packed["selected_memory_ids"] = blocks, list(plan.get("selected_memory_ids", []))
        packed["payload_hash"] = _hash({"blocks": blocks, "action": preview["action"], "profile": profile})
        packed["budget"] = {**preview.get("budget", {}), "selected_memory_ids": packed["selected_memory_ids"]}
        return packed

    def _save_context_run(self, job, preview, usage):
        source_ids = [source for block in preview.get("blocks", []) for source in block.get("source_ids", [])]
        self.connection.execute("INSERT INTO context_runs(id,campaign_id,branch_id,checkpoint_id,settings_revision,source_ids_json,omission_reasons_json,token_budget_json,payload_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), job["campaign_id"], job["branch_id"], job["checkpoint_id"], json.loads(job["settings_snapshot_json"]).get("settings_revision", 0), json.dumps(sorted(set(source_ids))), json.dumps(preview.get("omission_reasons", []), ensure_ascii=False), json.dumps({**preview.get("budget", {}), "director_usage": usage or {"status": "unknown"}}, ensure_ascii=False), preview["payload_hash"], _now()))
        updated = self.connection.execute("UPDATE generation_jobs SET final_context_json=? WHERE id=? AND status='running' AND cancel_requested=0", (json.dumps(preview, ensure_ascii=False, sort_keys=True), job["id"]))
        if updated.rowcount != 1:
            raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))

    def _narrate(self, job, profile, preview):
        key = f"{job['id']}:narration"
        request = {"stage": "narration", "messages": [{"role": "system", "content": "Continue the story in Vietnamese using only supplied context."}, {"role": "user", "content": json.dumps({"blocks": preview.get("blocks", []), "action": preview["action"], "selected_memory_ids": preview.get("selected_memory_ids", [])}, ensure_ascii=False, sort_keys=True)}], "reserved_completion_tokens": min(4000, int(profile.get("output_limit", 4000))), "model": profile.get("model"), "payload_hash": preview["payload_hash"]}
        request["cancel_event"] = Event()
        self._attempt_cancel_events[key] = request["cancel_event"]
        self._insert_attempt(job, "narration", key, preview["payload_hash"], profile, request)
        self._mark_dispatched(key)
        self._event(job["id"], "narration", "phase_changed", None, "", {"phase": "narration_dispatched"})
        parts, result = [], None
        started = time.monotonic()
        narration_provider = self._provider_for(job, "narration", profile)
        try:
            for event in narration_provider.generate_text(request):
                if time.monotonic() - started > self.timeout_seconds:
                    narration_provider.cancel(request)
                    raise _ProviderError(ProviderFailure("PROVIDER_TIMEOUT", "Narration attempt exceeded its timeout"))
                if self._cancel_requested(job["id"]):
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))
                if isinstance(event, ProviderFailure):
                    raise _ProviderError(event)
                if isinstance(event, ProviderResult):
                    result = event
                    if not parts and event.text:
                        self._append_output(job["id"], "narration", event.text, parts)
                elif isinstance(event, str) and event:
                    self._append_output(job["id"], "narration", event, parts)
            if result is None:
                raise _ProviderError(ProviderFailure("MISSING_TERMINAL", "Provider did not return a terminal result"))
            if result.failure:
                raise _ProviderError(result.failure)
            if result.finish_reason != "stop":
                raise _ProviderError(ProviderFailure("OUTPUT_TRUNCATED" if result.finish_reason in {"length", "max_tokens"} else "MODEL_REFUSED", "Provider did not complete normally"))
            draft = "".join(parts)
            if not draft:
                raise _ProviderError(ProviderFailure("MISSING_TERMINAL", "Provider returned empty narrative"))
            with transaction(self.connection):
                self._require_active(key, job["id"])
                self._finish_attempt(key, "completed", result, draft)
                changed = self.connection.execute("UPDATE generation_jobs SET status='candidate',draft=?,usage_json=? WHERE id=? AND status='running' AND cancel_requested=0 AND execution_epoch=(SELECT epoch FROM execution_epochs WHERE id=1)", (draft, json.dumps(result.usage or {"status": "unknown"}, ensure_ascii=False), job["id"]))
                if changed.rowcount != 1:
                    raise _ProviderError(ProviderFailure("CANCELLED", "Generation was cancelled"))
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job["id"],))
            self._event(job["id"], "narration", "completed", self._offset(draft), "", {"usage": result.usage or {"status": "unknown"}, "offset_unit": "utf16_code_units"})
        except _ProviderError as exc:
            self._finish_attempt(key, "interrupted" if exc.failure.code == "CANCELLED" else "failed", exc.failure, "".join(parts))
            raise

    def _append_output(self, job_id, stage, text, parts):
        parts.append(text)
        output = "".join(parts)
        row = self.connection.execute("SELECT stage_key FROM provider_attempts WHERE generation_job_id=? AND stage=?", (job_id, stage)).fetchone()
        self._require_active(row["stage_key"], job_id)
        self.connection.execute("UPDATE provider_attempts SET output_text=?,output_offset=? WHERE stage_key=? AND status='dispatched'", (output, self._offset(output), row["stage_key"]))
        self.connection.execute("UPDATE generation_jobs SET draft=? WHERE id=?", (output, job_id))
        self._event(job_id, stage, "delta", self._offset(output), text, {"offset_unit": "utf16_code_units"})

    def _insert_attempt(self, job, stage, key, payload_hash, profile, request):
        updated = self.connection.execute("UPDATE provider_attempts SET profile_snapshot_json=?,payload_hash=?,request_json=? WHERE generation_job_id=? AND stage=? AND status='queued'", (json.dumps(_copy(profile), sort_keys=True), payload_hash, json.dumps(_serializable_request(request), ensure_ascii=False, sort_keys=True), job["id"], stage))
        if updated.rowcount == 0:
            self.connection.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,request_json,output_text,output_offset,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), job["id"], stage, key, json.dumps(_copy(profile), sort_keys=True), payload_hash, "queued", json.dumps(_serializable_request(request), ensure_ascii=False, sort_keys=True), "", 0, _now()))

    def _mark_dispatched(self, key):
        self.connection.execute("UPDATE provider_attempts SET status='dispatched',dispatched_at=?,claim_epoch=(SELECT epoch FROM execution_epochs WHERE id=1) WHERE stage_key=? AND status='queued'", (_now(), key))

    @staticmethod
    def _offset(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    def _require_active(self, key, job_id):
        row = self.connection.execute("SELECT a.status,a.claim_epoch,j.execution_epoch,j.cancel_requested FROM provider_attempts a JOIN generation_jobs j ON j.id=a.generation_job_id WHERE a.stage_key=? AND j.id=?", (key, job_id)).fetchone()
        current = self._epoch()
        if row is None or row["status"] != "dispatched" or row["claim_epoch"] != current or row["execution_epoch"] != current or row["cancel_requested"]:
            raise _ProviderError(ProviderFailure("CANCELLED", "Generation attempt is no longer active"))

    def _finish_attempt(self, key, status, result, output):
        usage = result.usage if isinstance(result, ProviderResult) else {"status": "unknown"}
        failure = result if isinstance(result, ProviderFailure) else None
        changed = self.connection.execute("UPDATE provider_attempts SET status=?,output_text=?,output_offset=?,usage_json=?,failure_json=?,finished_at=? WHERE stage_key=? AND status='dispatched' AND claim_epoch=(SELECT epoch FROM execution_epochs WHERE id=1)", (status, output, self._offset(output), json.dumps(usage or {"status": "unknown"}), json.dumps({"code": failure.code, "message": failure.message}) if failure else None, _now(), key)).rowcount
        self._attempt_cancel_events.pop(key, None)
        return changed

    def _fail(self, job_id, failure):
        self.connection.execute("UPDATE generation_jobs SET status=?,failure_json=? WHERE id=?", ("cancelled" if failure.code == "CANCELLED" else "failed", json.dumps({"code": failure.code, "message": failure.message}, ensure_ascii=False), job_id))
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
            active = self.connection.execute("SELECT COUNT(*) AS n FROM provider_attempts WHERE generation_job_id=? AND status='dispatched'", (job_id,)).fetchone()["n"]
            status = "cancelling" if active else "cancelled"
            self.connection.execute("UPDATE generation_jobs SET cancel_requested=1,status=? WHERE id=? AND owner_id=? AND status IN ('queued','running','candidate')", (status, job_id, owner_id))
            for key, event in self._attempt_cancel_events.items():
                if key.startswith(f"{job_id}:"):
                    event.set()
            self.connection.execute("UPDATE provider_attempts SET status='interrupted',finished_at=? WHERE generation_job_id=? AND status='queued'", (_now(), job_id))
            if not active:
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
        self._event(job_id, None, "cancelled", None, "", {})
        return self._job(job_id)

    def edit_draft(self, owner_id, job_id, draft: str):
        job = self.get_job(owner_id, job_id)
        if job["status"] in {"candidate", "committed"}:
            raise ValidationError("Complete candidates cannot be edited as drafts")
        if not isinstance(draft, str):
            raise ValidationError("Draft must be text")
        self.connection.execute("UPDATE generation_jobs SET draft=? WHERE id=? AND owner_id=? AND status NOT IN ('candidate','committed')", (draft, job_id, owner_id))
        self._event(job_id, None, "draft_edited", self._offset(draft), "", {"offset_unit": "utf16_code_units"})
        return self._job(job_id)

    def recover_after_restart(self):
        with transaction(self.connection):
            jobs = self.connection.execute("SELECT generation_job_id FROM provider_attempts WHERE status='dispatched'").fetchall()
            self.connection.execute("UPDATE provider_attempts SET status='interrupted',failure_json=?,finished_at=? WHERE status='dispatched'", (json.dumps({"code": "PROVIDER_INTERRUPTED", "message": "Process restarted while provider call was ambiguous"}), _now()))
            running = self.connection.execute("SELECT id,final_context_json FROM generation_jobs WHERE status='running'").fetchall()
            self.connection.execute("UPDATE generation_jobs SET status='interrupted' WHERE status='running'")
            for job in jobs:
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job["generation_job_id"],))
            for job in running:
                queued = self.connection.execute("SELECT 1 FROM provider_attempts WHERE generation_job_id=? AND status='queued'", (job["id"],)).fetchone()
                dispatched = self.connection.execute("SELECT 1 FROM provider_attempts WHERE generation_job_id=? AND status='dispatched'", (job["id"],)).fetchone()
                if queued and not dispatched and job["final_context_json"]:
                    self.connection.execute("UPDATE generation_jobs SET status='queued' WHERE id=?", (job["id"],))

    startup_recover = recover_after_restart

    def _event(self, job_id, stage, event_type, offset, content, payload):
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
        values["settings_snapshot"] = json.loads(values.get("settings_snapshot_json") or "{}")
        values["profile_snapshot"] = json.loads(values.get("profile_snapshot_json") or "{}")
        attempts = self.connection.execute("SELECT stage,status,stage_key,output_offset,output_text,usage_json,failure_json,payload_hash,profile_snapshot_json FROM provider_attempts WHERE generation_job_id=? ORDER BY created_at", (job_id,)).fetchall()
        values["attempts"] = [item["stage"] for item in attempts]
        values["attempt_details"] = [{**dict(item), "usage": json.loads(item["usage_json"]) if item["usage_json"] else None, "failure": json.loads(item["failure_json"]) if item["failure_json"] else None, "profile_snapshot": json.loads(item["profile_snapshot_json"])} for item in attempts]
        values["events"] = self._events_raw(job_id)
        return values

    def get_job(self, owner_id, job_id):
        row = self.connection.execute("SELECT owner_id FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["owner_id"] != owner_id:
            raise NotFound("Generation job not found")
        return self._job(job_id)

    def commit_candidate(self, owner_id, job_id):
        job = self.get_job(owner_id, job_id)
        if job["status"] == "committed":
            return job
        if job["status"] != "candidate":
            raise ValidationError("Only a complete candidate can be committed")
        with transaction(self.connection):
            head = get_branch_head(self.connection, job["campaign_id"], job["branch_id"], owner_id)
            if head.checkpoint_id != job["checkpoint_id"]:
                raise StateConflict("Candidate is stale")
            _create_committed_revision_in_transaction(self.connection, job["campaign_id"], job["branch_id"], job["action"], job["draft"], expected_state_version=head.state_version)
            if self.connection.execute("UPDATE generation_jobs SET status='committed' WHERE id=? AND status='candidate'", (job_id,)).rowcount != 1:
                raise StateConflict("Candidate was already committed")
            self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
            self._event(job_id, "narration", "committed", len(job["draft"]), "", {})
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

    def __init__(self, database_url, provider, *, profile=None, provider_factory=None, credential_resolver=None, poll_seconds: float = 0.05):
        from threading import Event, Thread
        from .db import connect
        self._connect = connect
        self.connection = connect(database_url)
        self.service = GenerationService(self.connection, provider, profile=profile, provider_factory=provider_factory, credential_resolver=credential_resolver)
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
            self._thread.join(timeout=2)
        self.connection.close()
