from __future__ import annotations

"""Durable generation orchestration.

SQLite owns reservations and stage state. Provider I/O always runs outside a
transaction, so a browser disconnect cannot cancel or duplicate work.
"""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from jsonschema import Draft202012Validator

from .context import build_candidate_pool, build_context_preview, _profiles
from .db import migrate, transaction
from .domain import NotFound, StateConflict, ValidationError
from .model_profiles import estimate_cost_usd, validate_dispatch
from .provider import ProviderAdapter, ProviderFailure, ProviderResult
from .context_director import deterministic_selection, validate_director_plan
from .timeline import _create_committed_revision_in_transaction, get_branch_head, load_state_checkpoint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


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

    def __init__(self, connection: sqlite3.Connection, provider: ProviderAdapter, *, profile: dict | None = None, settings: dict | None = None, timeout_seconds: float = 300.0):
        self.connection, self.provider = connection, provider
        self.timeout_seconds = timeout_seconds
        self.profile = _copy(profile or DEFAULT_PROFILE)
        self.settings = _copy(settings or {})
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        migrate(self.connection)
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS generation_branch_guards (branch_id TEXT PRIMARY KEY, generation_job_id TEXT NOT NULL, acquired_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS generation_events (id INTEGER PRIMARY KEY AUTOINCREMENT, generation_job_id TEXT NOT NULL, stage TEXT, event_type TEXT NOT NULL, offset INTEGER, content TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_generation_events_job ON generation_events(generation_job_id, id);
        CREATE TABLE IF NOT EXISTS execution_epochs (id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, created_at TEXT NOT NULL);
        INSERT OR IGNORE INTO execution_epochs(id, epoch, created_at) VALUES (1, lower(hex(randomblob(16))), strftime('%Y-%m-%dT%H:%M:%fZ','now'));
        """)

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

    def _request_hash(self, campaign_id, branch_id, action, checkpoint_id, idempotency_key, mode, policy, cap, settings, profiles):
        return _hash({"campaign_id": campaign_id, "branch_id": branch_id, "action": action, "checkpoint_id": checkpoint_id, "idempotency_key": idempotency_key, "mode": mode, "policy": policy, "cap": str(cap) if cap is not None else None, "settings": settings, "profiles": profiles})

    def generate(self, owner_id: str, campaign_id: str, branch_id: str, action: str, *, idempotency_key: str, expected_checkpoint_id: str, mode: str = "economy", policy: str = "free_only", cap=None, execute: bool = True) -> dict:
        if mode not in {"economy", "quality"}:
            raise ValidationError("Unknown generation mode")
        if not action.strip() or not idempotency_key.strip():
            raise ValidationError("Action and idempotency key are required")
        profiles = self._profiles()
        settings = _copy(self.settings)
        settings.update({"mode": mode, "policy": policy, "confirmed_usd_cap": str(cap) if cap is not None else settings.get("confirmed_usd_cap")})
        request_hash = self._request_hash(campaign_id, branch_id, action, expected_checkpoint_id, idempotency_key, mode, policy, cap, settings, profiles)
        existing = self.connection.execute("SELECT id,request_hash FROM generation_jobs WHERE owner_id=? AND branch_id=? AND operation='generation' AND idempotency_key=?", (owner_id, branch_id, idempotency_key)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise StateConflict("Conflicting idempotency payload")
            return self._job(existing["id"])
        head = get_branch_head(self.connection, campaign_id, branch_id, owner_id)
        if head.checkpoint_id != expected_checkpoint_id:
            raise StateConflict("Generation checkpoint is stale")
        job_id, created = str(uuid4()), _now()
        with transaction(self.connection):
            if self.connection.execute("SELECT 1 FROM generation_branch_guards WHERE branch_id=?", (branch_id,)).fetchone():
                raise StateConflict("A generation is already active on this branch")
            # A persistent count prevents multiple application workers from
            # exceeding the two upstream attempt contract.
            count = self.connection.execute("SELECT COUNT(*) AS n FROM provider_attempts WHERE status='dispatched'").fetchone()["n"]
            if count >= 2:
                raise StateConflict("Provider concurrency limit reached")
            self.connection.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,action,status,mode,policy,created_at,settings_snapshot_json,profile_snapshot_json,execution_epoch,cancel_requested) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, owner_id, campaign_id, branch_id, "generation", idempotency_key, request_hash, expected_checkpoint_id, action, "queued", mode, policy, created, json.dumps(settings, sort_keys=True), json.dumps(profiles, sort_keys=True), self._epoch(), 0))
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
            self._fail(job_id, ProviderFailure("GENERATION_FAILED", str(exc)))
        return self._job(job_id)

    def _execute(self, job) -> None:
        profiles, settings = json.loads(job["profile_snapshot_json"]), json.loads(job["settings_snapshot_json"])
        narrator, context = profiles["narrator"], profiles["context"]
        config = {"profile_id": narrator.get("id"), "context_window": narrator.get("context_limit", 12000), "input_limit": narrator.get("context_limit", 12000), "output_limit": narrator.get("output_limit", 4000), "wrapper_buffer": narrator.get("wrapper_buffer", 512), "requested_output": min(4000, narrator.get("output_limit", 4000)), "is_test_profile": bool(narrator.get("is_test_profile")), "capabilities_verified": bool(narrator.get("capabilities_verified", True))}
        preview = build_context_preview(self.connection, job["campaign_id"], job["branch_id"], job["action"], config, owner_id=job["owner_id"], settings_hash=_hash(settings))
        if preview["checkpoint_id"] != job["checkpoint_id"] or preview["status"] == "stale":
            raise StateConflict("Generation checkpoint is stale")
        pool = build_candidate_pool(self.connection, job["campaign_id"], job["branch_id"], job["action"], checkpoint_id=job["checkpoint_id"], owner_id=job["owner_id"])
        plan = deterministic_selection(pool, pool["checkpoint_id"], pool["action_hash"])
        final_preview = preview
        if job["mode"] == "quality":
            self._check_dispatch(job, context, narrator, preview, aggregate=True)
            request = {"stage": "context", "messages": self._director_messages(job["action"], pool), "reserved_completion_tokens": min(4000, int(context.get("output_limit", 4000))), "model": context.get("model"), "checkpoint_id": pool["checkpoint_id"], "action_hash": pool["action_hash"]}
            key = f"{job['id']}:context"
            self._insert_attempt(job, "context", key, _hash(request), context, request)
            self._mark_dispatched(key)
            self._event(job["id"], "context", "phase_changed", None, "", {"phase": "context_dispatched"})
            result = self.provider.generate_structured(request, SELECTION_SCHEMA)
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
            final_preview = self._pack_selected(preview, plan, narrator)
            self._finish_attempt(key, "completed", result, json.dumps(plan, ensure_ascii=False, sort_keys=True))
            self._save_context_run(job, final_preview, result.usage)
            self._event(job["id"], "context", "phase_changed", None, "", {"phase": "context_completed", "selected_memory_ids": plan["selected_memory_ids"]})
            self._check_dispatch(job, context, narrator, final_preview, aggregate=False)
        else:
            final_preview = self._pack_selected(preview, plan, narrator)
        self._narrate(job, narrator, final_preview)

    def _check_dispatch(self, job, context, narrator, preview, *, aggregate: bool):
        tokens = int((preview.get("budget") or {}).get("input_tokens") or 0)
        out = min(4000, int(narrator.get("output_limit", 4000)))
        if job["policy"] == "capped_paid":
            cap = json.loads(job["settings_snapshot_json"]).get("confirmed_usd_cap")
            if cap is None:
                raise ValidationError("A confirmed USD cap is required")
            chosen = [context, narrator] if aggregate else [narrator]
            total = sum((estimate_cost_usd(p, tokens, out) for p in chosen), Decimal("0"))
            if total > Decimal(str(cap)):
                raise ValidationError("Aggregate generation estimate exceeds the confirmed USD cap")
            for profile in chosen:
                validate_dispatch(profile, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, cap)
        else:
            validate_dispatch(narrator, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, None)
            if job["mode"] == "quality":
                validate_dispatch(context, job["policy"], {"input_tokens": tokens, "completion_tokens": out}, None)

    def _director_messages(self, action, pool):
        payload = {"action": action, "checkpoint_id": pool["checkpoint_id"], "candidate_pool": {"mandatory": pool.get("mandatory", []), "optional": pool.get("optional", []), "scene_ids": pool.get("scene_ids", []), "omission_reasons": pool.get("omission_reasons", [])}}
        return [{"role": "system", "content": "Return only a SelectionPlan JSON. Select supplied IDs and cite each source."}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]

    def _pack_selected(self, preview, plan, profile):
        blocks, known = list(preview.get("blocks", [])), {b["id"] for b in preview.get("blocks", [])}
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

    def _narrate(self, job, profile, preview):
        key = f"{job['id']}:narration"
        request = {"stage": "narration", "messages": [{"role": "system", "content": "Continue the story in Vietnamese using only supplied context."}, {"role": "user", "content": json.dumps({"blocks": preview.get("blocks", []), "action": preview["action"], "selected_memory_ids": preview.get("selected_memory_ids", [])}, ensure_ascii=False, sort_keys=True)}], "reserved_completion_tokens": min(4000, int(profile.get("output_limit", 4000))), "model": profile.get("model"), "payload_hash": preview["payload_hash"]}
        self._insert_attempt(job, "narration", key, preview["payload_hash"], profile, request)
        self._mark_dispatched(key)
        self._event(job["id"], "narration", "phase_changed", None, "", {"phase": "narration_dispatched"})
        parts, result = [], None
        started = time.monotonic()
        try:
            for event in self.provider.generate_text(request):
                if time.monotonic() - started > self.timeout_seconds:
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
            self._finish_attempt(key, "completed", result, draft)
            self.connection.execute("UPDATE generation_jobs SET status='candidate',draft=?,usage_json=? WHERE id=?", (draft, json.dumps(result.usage or {"status": "unknown"}, ensure_ascii=False), job["id"]))
            self._event(job["id"], "narration", "completed", len(draft), "", {"usage": result.usage or {"status": "unknown"}})
        except _ProviderError as exc:
            self._finish_attempt(key, "interrupted" if exc.failure.code == "CANCELLED" else "failed", exc.failure, "".join(parts))
            raise

    def _append_output(self, job_id, stage, text, parts):
        parts.append(text)
        output = "".join(parts)
        row = self.connection.execute("SELECT stage_key FROM provider_attempts WHERE generation_job_id=? AND stage=?", (job_id, stage)).fetchone()
        self.connection.execute("UPDATE provider_attempts SET output_text=?,output_offset=? WHERE stage_key=?", (output, len(output), row["stage_key"]))
        self.connection.execute("UPDATE generation_jobs SET draft=? WHERE id=?", (output, job_id))
        self._event(job_id, stage, "delta", len(output), text, {})

    def _insert_attempt(self, job, stage, key, payload_hash, profile, request):
        self.connection.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,request_json,output_text,output_offset,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), job["id"], stage, key, json.dumps(_copy(profile), sort_keys=True), payload_hash, "queued", json.dumps(_copy(request), ensure_ascii=False, sort_keys=True), "", 0, _now()))

    def _mark_dispatched(self, key):
        self.connection.execute("UPDATE provider_attempts SET status='dispatched',dispatched_at=? WHERE stage_key=? AND status='queued'", (_now(), key))

    def _finish_attempt(self, key, status, result, output):
        usage = result.usage if isinstance(result, ProviderResult) else {"status": "unknown"}
        failure = result if isinstance(result, ProviderFailure) else None
        self.connection.execute("UPDATE provider_attempts SET status=?,output_text=?,output_offset=?,usage_json=?,failure_json=?,finished_at=? WHERE stage_key=?", (status, output, len(output), json.dumps(usage or {"status": "unknown"}), json.dumps({"code": failure.code, "message": failure.message}) if failure else None, _now(), key))

    def _fail(self, job_id, failure):
        self.connection.execute("UPDATE generation_jobs SET status=?,failure_json=? WHERE id=?", ("cancelled" if failure.code == "CANCELLED" else "failed", json.dumps({"code": failure.code, "message": failure.message}, ensure_ascii=False), job_id))
        self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
        self._event(job_id, None, "failed", None, "", {"code": failure.code, "message": failure.message})

    def _cancel_requested(self, job_id):
        row = self.connection.execute("SELECT cancel_requested FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def cancel(self, owner_id, job_id):
        self.get_job(owner_id, job_id)
        with transaction(self.connection):
            self.connection.execute("UPDATE generation_jobs SET cancel_requested=1,status='cancelled' WHERE id=? AND owner_id=? AND status IN ('queued','running','candidate')", (job_id, owner_id))
            self.connection.execute("UPDATE provider_attempts SET status='interrupted',finished_at=? WHERE generation_job_id=? AND status IN ('queued','dispatched')", (_now(), job_id))
            self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job_id,))
        self._event(job_id, None, "cancelled", None, "", {})
        return self._job(job_id)

    def recover_after_restart(self):
        with transaction(self.connection):
            jobs = self.connection.execute("SELECT generation_job_id FROM provider_attempts WHERE status='dispatched'").fetchall()
            self.connection.execute("UPDATE provider_attempts SET status='interrupted',failure_json=?,finished_at=? WHERE status='dispatched'", (json.dumps({"code": "PROVIDER_INTERRUPTED", "message": "Process restarted while provider call was ambiguous"}), _now()))
            self.connection.execute("UPDATE generation_jobs SET status='interrupted' WHERE status='running'")
            for job in jobs:
                self.connection.execute("DELETE FROM generation_branch_guards WHERE generation_job_id=?", (job["generation_job_id"],))

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
        return {"job_id": job_id, "status": job["status"], "draft": job.get("draft", ""), "offset": len(job.get("draft", "")), "failure": job.get("failure")}

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

    def __init__(self, database_url, provider, *, profile=None, poll_seconds: float = 0.05):
        from threading import Event, Thread
        from .db import connect
        self._connect = connect
        self.connection = connect(database_url)
        self.service = GenerationService(self.connection, provider, profile=profile)
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
                # transient database lock should leave queued work durable.
                pass
            sleep(self.poll_seconds)

    def stop(self):
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=2)
        self.connection.close()
