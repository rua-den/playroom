from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import campaigns as campaign_service
from ..context import build_context_preview, load_context_preview
from ..domain import Owner, NotFound, ValidationError
from ..db import request_connection
from ..model_profiles import get_model_profile, is_immutable_profile
from ..settings import config_hash, get_owner_settings
from ..wire_cost import normalized_budget
from .auth import require_owner

router = APIRouter(prefix="/api", tags=["context"])


def _settings_hash(request: Request, config: dict) -> str:
    return config_hash({**config, "counter_id": request.app.state.context_counter_id, "counter_mode": "exact" if request.app.state.context_counter is not None else "estimated"})


def _profile_config(connection: sqlite3.Connection, request: Request, owner: Owner, profile_id: str) -> dict:
    configured = request.app.state.context_model_profiles
    if request.app.state.context_model_profiles_explicit:
        config = configured.get(profile_id)
        if config is None:
            raise ValidationError("Requested context profile has no configured verified limits")
        return dict(config)
    settings = get_owner_settings(connection, owner.id)
    roles = settings.get("roles") or {}
    mode = settings.get("mode", "economy")
    narrator_binding = roles.get("narrator")
    context_binding = roles.get("context")
    if mode == "economy":
        role, binding = "narrator", narrator_binding
    elif isinstance(context_binding, dict) and context_binding.get("id") == profile_id:
        role, binding = "context", context_binding
    else:
        role, binding = "narrator", narrator_binding
    if not isinstance(binding, dict) or binding.get("id") != profile_id:
        raise ValidationError("Requested context profile is not the owner's active generation role")
    profile = get_model_profile(connection, owner.id, profile_id, binding.get("version"))
    context_limit = profile.get("context_limit")
    output_limit = profile.get("output_limit")
    custom_defaults = profile.get("provider") == "custom" and profile.get("custom_billing") == "provider_managed" and profile.get("limits_source") == "application_default" and profile.get("pricing_verified") is False and profile.get("capabilities_verified") is False and is_immutable_profile(profile)
    if not isinstance(context_limit, int) or not isinstance(output_limit, int) or context_limit <= 0 or output_limit <= 0 or (not profile.get("pricing_verified") and not custom_defaults):
        raise ValidationError("Requested context profile has no configured verified limits")
    role_budget = (settings.get("budgets") or {}).get(role) or {}
    budget = normalized_budget(profile, role_budget)
    return {
        "profile_id": profile["id"],
        "profile_version": profile.get("version"),
        "profile_hash": profile.get("profile_hash"),
        "settings_revision": settings.get("settings_revision"),
        "owner_settings_hash": settings.get("settings_hash"),
        "role": role,
        "context_window": context_limit,
        "input_limit": budget["input_limit"],
        "output_limit": output_limit,
        "wrapper_buffer": budget["wrapper_buffer"],
        "requested_output": budget["requested_output"],
        "capabilities_verified": False if custom_defaults else True,
        "limits_source": "application_default" if custom_defaults else None,
        "token_count_mode": "estimated",
    }


class PreviewRequest(BaseModel):
    branch_id: str
    action: str = Field(min_length=1, max_length=20000)
    profile_id: str = Field(min_length=1, max_length=128)


@router.post("/campaigns/{campaign_id}/context/previews", status_code=201)
def create_preview(campaign_id: str, payload: PreviewRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    campaign_service.get_campaign(connection, campaign_id, owner.id)
    config = _profile_config(connection, request, owner, payload.profile_id)
    return build_context_preview(connection, campaign_id, payload.branch_id, payload.action, config, owner_id=owner.id, settings_hash=_settings_hash(request, config), context_counter=request.app.state.context_counter, counter_id=request.app.state.context_counter_id)


@router.get("/context/previews/{preview_id}")
def get_preview(preview_id: str, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    row = connection.execute("SELECT payload_json FROM context_previews WHERE id = ? AND owner_id = ?", (preview_id, owner.id)).fetchone()
    if row is None:
        raise NotFound("Context preview not found")
    profile_id = json.loads(row["payload_json"]).get("profile_id")
    try:
        config = _profile_config(connection, request, owner, profile_id)
    except ValidationError:
        config = None
    current_hash = _settings_hash(request, config) if config is not None else config_hash({"missing_profile_id": profile_id})
    return load_context_preview(connection, preview_id, owner.id, settings_hash=current_hash)
