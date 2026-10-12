from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import campaigns as service
from ..campaigns import get_effective_profile, update_profile
from ..domain import Owner
from ..db import request_connection
from ..timeline import get_branch_head
from .auth import require_owner

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    world: dict
    characters: list[dict] = Field(default_factory=list, max_length=128)
    persona: dict
    style: dict | None = None


class ProfileUpdate(BaseModel):
    branch_id: str
    expected_state_version: int = Field(ge=1)
    data: dict


@router.get("")
def campaigns(connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return service.list_campaigns(connection, owner.id)


@router.post("", status_code=201)
def create(payload: CampaignCreate, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    created = service.create_campaign(connection, owner.id, payload.title, payload.world, payload.characters, payload.persona, style=payload.style)
    return {"id": created.id, "title": created.title, "branch_id": created.initial_branch_id, "character_ids": list(created.character_ids)}


@router.get("/{campaign_id}")
def get(campaign_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return service.get_campaign(connection, campaign_id, owner.id)


@router.get("/{campaign_id}/profiles/{profile_key:path}")
def profile(campaign_id: str, profile_key: str, branch_id: str, connection: sqlite3.Connection = Depends(request_connection), position: str | None = None, owner: Owner = Depends(require_owner)):
    service.get_campaign(connection, campaign_id, owner.id)
    return get_effective_profile(connection, campaign_id, branch_id, position, profile_key, owner.id)


@router.patch("/{campaign_id}/profiles/{profile_key:path}")
def edit_profile(campaign_id: str, profile_key: str, payload: ProfileUpdate, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    service.get_campaign(connection, campaign_id, owner.id)
    head = get_branch_head(connection, campaign_id, payload.branch_id, owner.id)
    updated = update_profile(connection, campaign_id, payload.branch_id, profile_key, payload.data, expected_state_version=payload.expected_state_version, owner_id=owner.id)
    return {"state_version": updated.state_version, "checkpoint_id": updated.id, "previous_state_version": head.state_version}
