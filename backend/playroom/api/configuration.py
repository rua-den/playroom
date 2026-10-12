from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..credentials import CredentialStore
from ..domain import Owner, ValidationError
from ..db import request_connection
from ..model_profiles import get_model_profile, list_model_profiles, persist_model_profile, OpenRouterVerifier, profile_hash
from ..settings import get_owner_settings, save_owner_settings
from .auth import require_owner

router = APIRouter(prefix="/api/provider", tags=["provider-configuration"])


class CredentialRequest(BaseModel):
    secret: str


class VerifyProfileRequest(BaseModel):
    credential_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=3, max_length=256)
    endpoint: str = Field(min_length=1, max_length=512)
    provider_tag: str = Field(min_length=1, max_length=256)


class SettingsRequest(BaseModel):
    context_profile_id: str | None = None
    narrator_profile_id: str
    consolidation_profile_id: str | None = None
    mode: str = "economy"
    policy: str = "free_only"
    confirmed_usd_cap: str | float | None = None


def _store(request: Request) -> CredentialStore:
    return request.app.state.credential_store


@router.post("/credentials", status_code=201)
def add_credential(payload: CredentialRequest, request: Request, owner: Owner = Depends(require_owner)):
    try:
        if not payload.secret or len(payload.secret) > 4096 or "\n" in payload.secret:
            raise ValidationError("Credential format is invalid")
        record = _store(request).put(owner.id, payload.secret)
        return _store(request).masked(owner.id, record.id)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Credential could not be stored") from exc


@router.get("/credentials")
def credentials(request: Request, owner: Owner = Depends(require_owner)):
    return _store(request).list_masked(owner.id)


@router.get("/profiles")
def profiles(connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return list_model_profiles(connection, owner.id)


@router.post("/profiles/verify", status_code=201)
def verify_profile(payload: VerifyProfileRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    try:
        secret = _store(request).get(owner.id, payload.credential_id)
        verifier = request.app.state.provider_verifier
        snapshot = verifier.verify(secret, payload.model, payload.endpoint, provider_tag=payload.provider_tag)
        snapshot["secret_version"] = payload.credential_id
        return persist_model_profile(connection, owner.id, snapshot)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Provider metadata could not be verified") from exc


@router.get("/settings")
def settings(connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return get_owner_settings(connection, owner.id)


@router.put("/settings")
def update_settings(payload: SettingsRequest, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    narrator_profile = get_model_profile(connection, owner.id, payload.narrator_profile_id)
    def binding(profile):
        return {"id": profile["id"], "version": profile["version"], "profile_hash": profile.get("profile_hash") or profile_hash({key: value for key, value in profile.items() if key not in {"version", "profile_hash"}})}
    roles = {"narrator": binding(narrator_profile)}
    if payload.mode == "quality":
        if not payload.context_profile_id or not payload.consolidation_profile_id:
            raise ValidationError("Quality mode requires context and consolidation profiles")
        context_profile = get_model_profile(connection, owner.id, payload.context_profile_id)
        consolidation_profile = get_model_profile(connection, owner.id, payload.consolidation_profile_id)
        if not all(profile.get("structured_output") and profile.get("native_structured_output") and profile.get("structured_schema_parameter") for profile in (context_profile, consolidation_profile)):
            raise ValidationError("Context and consolidation roles require native strict schema support")
        roles.update({"context": binding(context_profile), "consolidation": binding(consolidation_profile)})
    return save_owner_settings(connection, owner.id, {"roles": roles, "mode": payload.mode, "policy": payload.policy, "confirmed_usd_cap": payload.confirmed_usd_cap})
