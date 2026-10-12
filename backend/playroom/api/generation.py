from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..db import request_connection
from ..domain import Owner, ValidationError
from ..generation import GenerationService
from .auth import require_owner

router = APIRouter(prefix="/api", tags=["generation"])


class GenerateRequest(BaseModel):
    branch_id: str
    action: str = Field(min_length=1, max_length=20000)
    idempotency_key: str = Field(min_length=1, max_length=256)
    checkpoint_id: str
    mode: str = "economy"
    policy: str = "free_only"
    cap: int | None = Field(default=None, ge=1)


@router.post("/campaigns/{campaign_id}/generate", status_code=201)
def generate(campaign_id: str, payload: GenerateRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    provider = getattr(request.app.state, "generation_provider", None)
    if provider is None:
        raise ValidationError("Narrative generation is not configured")
    return GenerationService(connection, provider).generate(owner.id, campaign_id, payload.branch_id, payload.action, idempotency_key=payload.idempotency_key, expected_checkpoint_id=payload.checkpoint_id, mode=payload.mode, policy=payload.policy, cap=payload.cap)
    return GenerationService(connection, provider).generate(owner.id, campaign_id, payload.branch_id, payload.action, idempotency_key=payload.idempotency_key, expected_checkpoint_id=payload.checkpoint_id, mode=payload.mode, policy=payload.policy, cap=payload.cap)


@router.get("/generation/jobs/{job_id}")
def status(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).get_job(owner.id, job_id)


@router.post("/generation/jobs/{job_id}/commit")
def commit(job_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return GenerationService(connection, FakeProvider([])).commit_candidate(owner.id, job_id)
