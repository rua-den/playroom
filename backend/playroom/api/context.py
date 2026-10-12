from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import campaigns as campaign_service
from ..context import build_context_preview, load_context_preview
from ..domain import Owner, NotFound, ValidationError
from ..db import request_connection
from ..settings import config_hash
from .auth import require_owner

router = APIRouter(prefix="/api", tags=["context"])


def _settings_hash(request: Request, config: dict) -> str:
    return config_hash({**config, "counter_id": request.app.state.context_counter_id, "counter_mode": "exact" if request.app.state.context_counter is not None else "estimated"})


class PreviewRequest(BaseModel):
    branch_id: str
    action: str = Field(min_length=1, max_length=20000)
    profile_id: str = Field(min_length=1, max_length=128)


@router.post("/campaigns/{campaign_id}/context/previews", status_code=201)
def create_preview(campaign_id: str, payload: PreviewRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    profiles = request.app.state.context_model_profiles
    config = profiles.get(payload.profile_id)
    if config is None:
        raise ValidationError("Requested context profile has no configured verified limits")
    return build_context_preview(connection, campaign_id, payload.branch_id, payload.action, config, owner_id=owner.id, settings_hash=_settings_hash(request, config), context_counter=request.app.state.context_counter, counter_id=request.app.state.context_counter_id)


@router.get("/context/previews/{preview_id}")
def get_preview(preview_id: str, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    row = connection.execute("SELECT payload_json FROM context_previews WHERE id = ? AND owner_id = ?", (preview_id, owner.id)).fetchone()
    if row is None:
        raise NotFound("Context preview not found")
    profile_id = json.loads(row["payload_json"]).get("profile_id")
    config = request.app.state.context_model_profiles.get(profile_id)
    current_hash = _settings_hash(request, config) if config is not None else config_hash({"missing_profile_id": profile_id})
    return load_context_preview(connection, preview_id, owner.id, settings_hash=current_hash)
