from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..credentials import CredentialStore
from ..domain import Owner, ValidationError
from ..db import request_connection
from ..model_profiles import get_model_profile, list_model_profiles, persist_model_profile, OpenRouterVerifier
from ..settings import get_owner_settings, save_owner_settings
from .auth import require_owner

router = APIRouter(prefix="/api/provider", tags=["provider-configuration"])


class CredentialRequest(BaseModel):
    secret: str = Field(min_length=1, max_length=4096)


class VerifyProfileRequest(BaseModel):
    credential_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=3, max_length=256)
    endpoint: str = Field(min_length=1, max_length=512)
    provider_tag: str | None = Field(default=None, max_length=256)


class SettingsRequest(BaseModel):
    context_profile_id: str
    narrator_profile_id: str
    consolidation_profile_id: str
    mode: str = "economy"
    policy: str = "free_only"
    confirmed_usd_cap: str | float | None = None


def _store(request: Request) -> CredentialStore:
    return request.app.state.credential_store


@router.post("/credentials", status_code=201)
def add_credential(payload: CredentialRequest, request: Request, owner: Owner = Depends(require_owner)):
    try:
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
    context_profile = get_model_profile(connection, owner.id, payload.context_profile_id)
    narrator_profile = get_model_profile(connection, owner.id, payload.narrator_profile_id)
    consolidation_profile = get_model_profile(connection, owner.id, payload.consolidation_profile_id)
    if not context_profile.get("structured_output") or not consolidation_profile.get("structured_output"):
        raise ValidationError("Context and consolidation roles require native structured output")
    return save_owner_settings(connection, owner.id, {"roles": {"context": payload.context_profile_id, "narrator": payload.narrator_profile_id, "consolidation": payload.consolidation_profile_id}, "mode": payload.mode, "policy": payload.policy, "confirmed_usd_cap": payload.confirmed_usd_cap})
