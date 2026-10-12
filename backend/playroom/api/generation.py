from __future__ import annotations

import sqlite3
import json
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..db import request_connection
from ..domain import Owner, ValidationError
from ..generation import GenerationRuntime, GenerationService
from ..provider import FakeProvider
from ..auth import SESSION_COOKIE, session_valid
from ..db import connect
from ..model_profiles import get_model_profile
from ..settings import get_owner_settings
from .auth import require_owner

router = APIRouter(prefix="/api", tags=["generation"])


def _service(request: Request, connection: sqlite3.Connection, owner: Owner) -> GenerationService:
    provider = getattr(request.app.state, "generation_provider", None)
    provider_factory = getattr(request.app.state, "generation_provider_factory", None)
    if provider is None and provider_factory is None:
        raise ValidationError("Narrative generation is not configured")
    settings = get_owner_settings(connection, owner.id)
    roles = {}
    for role, binding in (settings.get("roles") or {}).items():
        if not binding:
            continue
        roles[role] = get_model_profile(connection, owner.id, binding["id"], binding.get("version"))
    if getattr(request.app.state, "generation_runtime", None) is None:
        request.app.state.generation_runtime = GenerationRuntime(request.app.state.database_url, provider, provider_factory=provider_factory, credential_resolver=request.app.state.generation_credential_resolver, attempt_registry=request.app.state.generation_attempt_registry)
        request.app.state.generation_runtime.start()
    # Keep explicit fake/demo injection usable without requiring a credential
    # file; production profiles still pin their immutable secret version.
    return GenerationService(connection, provider, profile={"roles": roles} if roles else None, settings=settings)


class GenerateRequest(BaseModel):
    branch_id: str
    action: str = Field(min_length=1, max_length=20000)
    idempotency_key: str = Field(min_length=1, max_length=256)
    checkpoint_id: str
    preview_id: str | None = None
    mode: str | None = None
    policy: str | None = None
    cap: Decimal | None = Field(default=None, gt=0)


class DraftRequest(BaseModel):
    draft: str = Field(max_length=100000)


@router.post("/campaigns/{campaign_id}/generate", status_code=201)
def generate(campaign_id: str, payload: GenerateRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    fields = getattr(payload, "model_fields_set", None)
    if fields is None:
        fields = getattr(payload, "__fields_set__", set())
    submitted_identity = {
        "mode": {"present": "mode" in fields, "value": payload.mode},
        "policy": {"present": "policy" in fields, "value": payload.policy},
        "cap": {"present": "cap" in fields, "value": str(payload.cap) if payload.cap is not None else None},
    }
    probe = GenerationService(connection, FakeProvider([]))
    existing = probe.existing_for_submitted_request(owner.id, campaign_id, payload.branch_id, payload.action, idempotency_key=payload.idempotency_key, expected_checkpoint_id=payload.checkpoint_id, preview_id=payload.preview_id, submitted_identity=submitted_identity)
    if existing is not None:
        return existing
    configured = get_owner_settings(connection, owner.id)
    mode = payload.mode or configured.get("mode", "economy")
    policy = payload.policy or configured.get("policy", "free_only")
    cap = payload.cap if payload.cap is not None else configured.get("confirmed_usd_cap")
    return _service(request, connection, owner).generate(owner.id, campaign_id, payload.branch_id, payload.action, idempotency_key=payload.idempotency_key, expected_checkpoint_id=payload.checkpoint_id, preview_id=payload.preview_id, mode=mode, policy=policy, cap=cap, execute=False, submitted_identity=submitted_identity)


@router.get("/generation/jobs/by-key")
def status_by_key(branch_id: str, idempotency_key: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).get_job_by_key(owner.id, branch_id, idempotency_key)


@router.get("/generation/jobs/{job_id}")
def status(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).get_job(owner.id, job_id)


@router.get("/generation/jobs/{job_id}/content")
def content(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).content(owner.id, job_id)


@router.get("/generation/jobs/{job_id}/events")
def events(job_id: str, after: int = Query(default=0, ge=0), connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return {"events": GenerationService(connection, FakeProvider([])).events(owner.id, job_id, after=after)}


@router.get("/generation/jobs/{job_id}/events/stream")
def events_stream(job_id: str, request: Request, after: int = Query(default=0, ge=0), connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    GenerationService(connection, FakeProvider([])).get_job(owner.id, job_id)
    token = request.cookies.get(SESSION_COOKIE)

    def stream():
        cursor = after
        while True:
            poll = connect(request.app.state.database_url)
            try:
                current_owner = session_valid(poll, token)
                if current_owner is None or current_owner.id != owner.id:
                    yield "event: session_expired\ndata: {}\n\n"
                    return
                service = GenerationService(poll, FakeProvider([]))
                items = service.events(owner.id, job_id, after=cursor)
                for item in items:
                    cursor = item["id"]
                    yield f"id: {cursor}\nevent: {item['event_type']}\ndata: {json.dumps(item, ensure_ascii=False, sort_keys=True)}\n\n"
                job = service.get_job(owner.id, job_id)
                if job["status"] in {"candidate", "committed", "failed", "cancelled", "interrupted"}:
                    return
                yield ": keep-alive\n\n"
            finally:
                poll.close()
            time.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/generation/jobs/{job_id}/cancel")
def cancel(job_id: str, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([]), attempt_registry=request.app.state.generation_attempt_registry).cancel(owner.id, job_id)


@router.put("/generation/jobs/{job_id}/draft")
def edit_draft(job_id: str, payload: DraftRequest, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).edit_draft(owner.id, job_id, payload.draft)


@router.post("/generation/jobs/{job_id}/commit")
def commit(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).commit_candidate(owner.id, job_id)
