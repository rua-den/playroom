from __future__ import annotations

import sqlite3
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..db import request_connection
from ..domain import Owner, ValidationError
from ..generation import GenerationRuntime, GenerationService
from ..provider import FakeProvider
from ..model_profiles import get_model_profile
from ..settings import get_owner_settings
from .auth import require_owner

router = APIRouter(prefix="/api", tags=["generation"])


def _service(request: Request, connection: sqlite3.Connection, owner: Owner) -> GenerationService:
    provider = getattr(request.app.state, "generation_provider", None)
    if provider is None:
        raise ValidationError("Narrative generation is not configured")
    settings = get_owner_settings(connection, owner.id)
    roles = {}
    for role, binding in (settings.get("roles") or {}).items():
        if not binding:
            continue
        roles[role] = get_model_profile(connection, owner.id, binding["id"], binding.get("version"))
        if not isinstance(provider, FakeProvider) and roles[role].get("secret_version"):
            # Resolve the pinned version immediately before dispatch. A
            # rotated/revoked key must fail this request rather than silently
            # selecting a mutable replacement.
            request.app.state.credential_store.get(owner.id, roles[role]["secret_version"])
    if getattr(request.app.state, "generation_runtime", None) is None:
        request.app.state.generation_runtime = GenerationRuntime(request.app.state.database_url, provider)
        request.app.state.generation_runtime.start()
    # Keep explicit fake/demo injection usable without requiring a credential
    # file; production profiles still pin their immutable secret version.
    return GenerationService(connection, provider, profile={"roles": roles} if roles else None, settings=settings)


class GenerateRequest(BaseModel):
    branch_id: str
    action: str = Field(min_length=1, max_length=20000)
    idempotency_key: str = Field(min_length=1, max_length=256)
    checkpoint_id: str
    mode: str = "economy"
    policy: str = "free_only"
    cap: Decimal | None = Field(default=None, gt=0)


class GenerationEventsQuery(BaseModel):
    after: int = Field(default=0, ge=0)


@router.post("/campaigns/{campaign_id}/generate", status_code=201)
def generate(campaign_id: str, payload: GenerateRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return _service(request, connection, owner).generate(owner.id, campaign_id, payload.branch_id, payload.action, idempotency_key=payload.idempotency_key, expected_checkpoint_id=payload.checkpoint_id, mode=payload.mode, policy=payload.policy, cap=payload.cap, execute=False)


@router.get("/generation/jobs/{job_id}")
def status(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).get_job(owner.id, job_id)


@router.get("/generation/jobs/by-key")
def status_by_key(branch_id: str, idempotency_key: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).get_job_by_key(owner.id, branch_id, idempotency_key)


@router.get("/generation/jobs/{job_id}/content")
def content(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).content(owner.id, job_id)


@router.get("/generation/jobs/{job_id}/events")
def events(job_id: str, after: int = 0, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return {"events": GenerationService(connection, FakeProvider([])).events(owner.id, job_id, after=after)}


@router.post("/generation/jobs/{job_id}/cancel")
def cancel(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).cancel(owner.id, job_id)


@router.post("/generation/jobs/{job_id}/commit")
def commit(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).commit_candidate(owner.id, job_id)
