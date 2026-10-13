from __future__ import annotations

from dataclasses import asdict
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import campaigns as campaign_service
from .. import memory as service
from ..domain import Owner
from ..db import request_connection
from ..timeline import get_branch_head
from .auth import require_owner

router = APIRouter(prefix="/api/campaigns/{campaign_id}", tags=["memory"])


class MemoryCreate(BaseModel):
    branch_id: str
    expected_state_version: int = Field(ge=1)
    kind: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=20000)
    source_revision_ids: list[str] = Field(default_factory=list, max_length=256)
    entity_ids: list[str] = Field(default_factory=list, max_length=64)
    pinned: bool = False
    mandatory: bool = False
    knowledge_scope: str = "public"
    known_by: list[str] = Field(default_factory=list, max_length=64)
    subject_id: str | None = None
    predicate: str | None = None
    value: str | None = None
    object_id: str | None = None
    supersedes_id: str | None = None


class RetrievalUpdate(BaseModel):
    branch_id: str
    expected_state_version: int = Field(ge=1)
    policy: str


class SceneUpdate(BaseModel):
    branch_id: str
    expected_state_version: int = Field(ge=1)
    scene_state: dict


class MemoryUpdate(BaseModel):
    branch_id: str
    expected_state_version: int = Field(ge=1)
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    pinned: bool | None = None
    entity_ids: list[str] | None = Field(default=None, max_length=64)
    knowledge_scope: str | None = None
    known_by: list[str] | None = Field(default=None, max_length=64)
    subject_id: str | None = None
    predicate: str | None = None
    value: str | None = None
    object_id: str | None = None
    supersedes_id: str | None = None


@router.get("/memory")
def list_memory(campaign_id: str, branch_id: str, connection: sqlite3.Connection = Depends(request_connection), position: str | None = None, owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return [asdict(item) for item in service.list_memory_library(connection, campaign_id, branch_id, position, owner_id=owner.id)]


@router.get("/memory/proposals")
def proposals(campaign_id: str, branch_id: str, connection: sqlite3.Connection = Depends(request_connection), position: str | None = None, owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return [asdict(item) for item in service.list_memory_proposals(connection, campaign_id, branch_id, position, owner_id=owner.id)]


@router.get("/memory/{memory_id}/history")
def history(campaign_id: str, memory_id: str, branch_id: str, connection: sqlite3.Connection = Depends(request_connection), position: str | None = None, owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return [asdict(item) for item in service.list_memory_history(connection, campaign_id, branch_id, memory_id, position, owner_id=owner.id)]


@router.patch("/memory/{memory_id}")
def edit_memory(campaign_id: str, memory_id: str, payload: MemoryUpdate, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    fields = payload.model_fields_set
    update = {name: getattr(payload, name) for name in ("text", "pinned", "entity_ids", "knowledge_scope", "known_by", "subject_id", "predicate", "value", "object_id", "supersedes_id") if name in fields}
    return asdict(service.update_memory(connection, campaign_id, payload.branch_id, memory_id, expected_state_version=payload.expected_state_version, **update))


@router.post("/memory", status_code=201)
def add_memory(campaign_id: str, payload: MemoryCreate, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    item = service.append_memory_version(
        connection,
        campaign_id,
        payload.branch_id,
        payload.kind,
        payload.text,
        origin="user",
        expected_state_version=payload.expected_state_version,
        source_revision_ids=payload.source_revision_ids,
        entity_ids=payload.entity_ids,
        pinned=payload.pinned,
        mandatory=payload.mandatory,
        knowledge_scope=payload.knowledge_scope,
        known_by=payload.known_by,
        subject_id=payload.subject_id,
        predicate=payload.predicate,
        value=payload.value,
        object_id=payload.object_id,
        supersedes_id=payload.supersedes_id,
    )
    return asdict(item)


@router.post("/memory/{memory_id}/approve")
def approve_memory(campaign_id: str, memory_id: str, branch_id: str, expected_state_version: int, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return asdict(service.approve_memory(connection, campaign_id, branch_id, memory_id, expected_state_version=expected_state_version))


@router.post("/memory/{memory_id}/reject")
def reject_memory(campaign_id: str, memory_id: str, branch_id: str, expected_state_version: int, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return asdict(service.reject_memory(connection, campaign_id, branch_id, memory_id, expected_state_version=expected_state_version))


@router.delete("/memory/{memory_id}")
def delete_memory(campaign_id: str, memory_id: str, branch_id: str, expected_state_version: int, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return asdict(service.delete_memory(connection, campaign_id, branch_id, memory_id, expected_state_version=expected_state_version))


@router.get("/scene")
def scene(campaign_id: str, branch_id: str, connection: sqlite3.Connection = Depends(request_connection), position: str | None = None, owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    return service.get_effective_scene(connection, campaign_id, branch_id, position, owner_id=owner.id)


@router.put("/scene")
def edit_scene(campaign_id: str, payload: SceneUpdate, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    checkpoint = service.update_scene(connection, campaign_id, payload.branch_id, payload.scene_state, expected_state_version=payload.expected_state_version)
    return {"state_version": checkpoint.state_version, "checkpoint_id": checkpoint.id}


@router.put("/retrieval-policy")
def retrieval_policy(campaign_id: str, payload: RetrievalUpdate, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    checkpoint = service.set_retrieval_policy(connection, campaign_id, payload.branch_id, payload.policy, expected_state_version=payload.expected_state_version)
    return {"state_version": checkpoint.state_version, "checkpoint_id": checkpoint.id, "policy": checkpoint.snapshot["retrieval_policy"]}
