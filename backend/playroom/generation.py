from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from .context import build_candidate_pool, build_context_preview
from .db import transaction
from .domain import NotFound, StateConflict, ValidationError
from .model_profiles import profile_hash, validate_dispatch
from .provider import ProviderAdapter, ProviderFailure, ProviderResult
from .timeline import create_committed_revision, get_branch_head


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class GenerationService:
    def __init__(self, connection: sqlite3.Connection, provider: ProviderAdapter, *, profile: dict | None = None):
        self.connection, self.provider = connection, provider
        self.profile = profile or {"id": "fake-context-test", "version": 1, "provider": "fake", "endpoint": "fake://local", "model": "synthetic-fixture", "context_limit": 12000, "output_limit": 4000, "credential_tier": "free", "pricing_verified": True, "secret_version": "synthetic"}
        self._ensure_tables()

    def _ensure_tables(self):
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS generation_jobs (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, campaign_id TEXT NOT NULL, branch_id TEXT NOT NULL, operation TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, checkpoint_id TEXT NOT NULL, action TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'economy', policy TEXT NOT NULL DEFAULT 'free_only', draft TEXT NOT NULL DEFAULT '', failure_json TEXT, usage_json TEXT, created_at TEXT NOT NULL, UNIQUE(owner_id, branch_id, operation, idempotency_key));
        CREATE TABLE IF NOT EXISTS provider_attempts (id TEXT PRIMARY KEY, generation_job_id TEXT NOT NULL, stage TEXT NOT NULL, stage_key TEXT NOT NULL UNIQUE, profile_snapshot_json TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL, usage_json TEXT, output_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, finished_at TEXT);
        """)
        cols = {row[1] for row in self.connection.execute("PRAGMA table_info(generation_jobs)")}
        if "action" not in cols:
            self.connection.execute("ALTER TABLE generation_jobs ADD COLUMN action TEXT NOT NULL DEFAULT ''")

    def generate(self, owner_id: str, campaign_id: str, branch_id: str, action: str, *, idempotency_key: str, expected_checkpoint_id: str, mode: str = "economy", policy: str = "free_only", cap=None) -> dict:
        request_hash = _hash({"campaign_id": campaign_id, "branch_id": branch_id, "action": action, "mode": mode, "policy": policy, "profile": profile_hash(self.profile)})
        existing = self.connection.execute("SELECT * FROM generation_jobs WHERE owner_id=? AND branch_id=? AND operation='generation' AND idempotency_key=?", (owner_id, branch_id, idempotency_key)).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise StateConflict("Conflicting idempotency payload")
            return self._job(existing["id"])
        head = get_branch_head(self.connection, campaign_id, branch_id, owner_id)
        if head.checkpoint_id != expected_checkpoint_id:
            raise StateConflict("Generation checkpoint is stale")
        job_id = str(uuid4())
        with transaction(self.connection):
            self.connection.execute("INSERT INTO generation_jobs(id,owner_id,campaign_id,branch_id,operation,idempotency_key,request_hash,checkpoint_id,action,status,mode,policy,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, owner_id, campaign_id, branch_id, "generation", idempotency_key, request_hash, expected_checkpoint_id, action, "running", mode, policy, _now()))
        try:
            preview = build_context_preview(self.connection, campaign_id, branch_id, action, {"profile_id": self.profile["id"], "is_test_profile": True, "context_window": self.profile["context_limit"], "input_limit": self.profile["context_limit"], "output_limit": self.profile["output_limit"], "wrapper_buffer": 512, "requested_output": min(4000, self.profile["output_limit"])}, owner_id=owner_id)
            if preview["status"] != "ready":
                raise ValidationError("Generation context is not ready")
            validate_dispatch(self.profile, policy, {"input_tokens": preview["budget"].get("input_tokens"), "completion_tokens": self.profile["output_limit"]}, cap)
            if mode == "quality":
                pool = build_candidate_pool(self.connection, campaign_id, branch_id, action, checkpoint_id=expected_checkpoint_id, owner_id=owner_id)
                context_key = f"{job_id}:context"
                self.connection.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,output_text,created_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (str(uuid4()), job_id, "context", context_key, json.dumps(self.profile, sort_keys=True), _hash(pool), "completed", json.dumps({"selected_memory_ids": [item["id"] for item in pool.get("optional", [])[:20]]}), _now(), _now()))
            stage_key = f"{job_id}:narration"
            self.connection.execute("INSERT INTO provider_attempts(id,generation_job_id,stage,stage_key,profile_snapshot_json,payload_hash,status,created_at) VALUES (?,?,?,?,?,?,?,?)", (str(uuid4()), job_id, "narration", stage_key, json.dumps(self.profile, sort_keys=True), preview["payload_hash"], "dispatched", _now()))
            text_parts, result = [], None
            for event in self.provider.generate_text({"stage": "narration", "messages": preview["blocks"], "estimated_input_tokens": preview["budget"].get("input_tokens", 0), "reserved_completion_tokens": self.profile["output_limit"]}):
                if isinstance(event, ProviderFailure):
                    raise _ProviderError(event)
                if isinstance(event, ProviderResult):
                    result = event
                else:
                    text_parts.append(event)
            if result is None or result.finish_reason != "stop":
                raise _ProviderError(ProviderFailure("OUTPUT_TRUNCATED", "Provider did not return a terminal success"))
            draft = result.text or "".join(text_parts)
            self.connection.execute("UPDATE provider_attempts SET status='completed', output_text=?, usage_json=?, finished_at=? WHERE stage_key=?", (draft, json.dumps(result.usage), _now(), stage_key))
            self.connection.execute("UPDATE generation_jobs SET status='candidate', draft=?, usage_json=? WHERE id=?", (draft, json.dumps(result.usage), job_id))
        except _ProviderError as exc:
            self.connection.execute("UPDATE generation_jobs SET status='failed', failure_json=? WHERE id=?", (json.dumps({"code": exc.failure.code, "message": exc.failure.message}), job_id))
        except Exception as exc:
            self.connection.execute("UPDATE generation_jobs SET status='failed', failure_json=? WHERE id=?", (json.dumps({"code": "STATE_CONFLICT", "message": str(exc)}), job_id))
        return self._job(job_id)

    def _job(self, job_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None: raise NotFound("Generation job not found")
        attempts = self.connection.execute("SELECT stage FROM provider_attempts WHERE generation_job_id=? ORDER BY created_at", (job_id,)).fetchall()
        return {**dict(row), "attempts": [item["stage"] for item in attempts], "failure": json.loads(row["failure_json"]) if row["failure_json"] else None, "usage": json.loads(row["usage_json"]) if row["usage_json"] else None}

    def get_job(self, owner_id: str, job_id: str) -> dict:
        row = self.connection.execute("SELECT owner_id FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["owner_id"] != owner_id: raise NotFound("Generation job not found")
        return self._job(job_id)

    def commit_candidate(self, owner_id: str, job_id: str) -> dict:
        job = self.get_job(owner_id, job_id)
        if job["status"] != "candidate": raise ValidationError("Only a complete candidate can be committed")
        head = get_branch_head(self.connection, job["campaign_id"], job["branch_id"], owner_id)
        if head.checkpoint_id != job["checkpoint_id"]: raise StateConflict("Candidate is stale")
        create_committed_revision(self.connection, job["campaign_id"], job["branch_id"], job["action"], job["draft"], expected_state_version=head.state_version)
        self.connection.execute("UPDATE generation_jobs SET status='committed' WHERE id=? AND status='candidate'", (job_id,))
        return self._job(job_id)


class _ProviderError(Exception):
    def __init__(self, failure: ProviderFailure):
        self.failure = failure
