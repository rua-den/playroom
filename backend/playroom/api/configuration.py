from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..credentials import CredentialStore
from ..domain import Owner, ValidationError
from ..db import request_connection
from ..model_profiles import get_model_profile, list_model_profiles, persist_model_profile, OpenRouterVerifier, OllamaCloudVerifier, OLLAMA_CLOUD_ENDPOINT, OLLAMA_CLOUD_MODEL, profile_hash, validate_custom_profile
from ..settings import get_owner_settings, save_owner_settings
from ..paid_trials import create_trial_authorization, revoke_trial_authorization, get_trial_summary
from .auth import require_owner

router = APIRouter(prefix="/api/provider", tags=["provider-configuration"])


class CredentialRequest(BaseModel):
    secret: str


class VerifyProfileRequest(BaseModel):
    provider: str = Field(default="openrouter", min_length=1, max_length=64)
    credential_id: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=3, max_length=256)
    endpoint: str = Field(default="https://openrouter.ai/api/v1/chat/completions", min_length=1, max_length=512)
    provider_tag: str | None = Field(default=None, max_length=256)


class CustomProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=256)
    credential_id: str | None = Field(default=None, max_length=128)


class SettingsRequest(BaseModel):
    context_profile_id: str | None = None
    narrator_profile_id: str | None = None
    consolidation_profile_id: str | None = None
    mode: str | None = None
    policy: str | None = None
    confirmed_usd_cap: str | float | None = None
    budgets: dict[str, dict[str, int]] | None = None


class PaidTrialRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    total_cap_usd: str = Field(min_length=1, max_length=48)
    per_send_cap_usd: str = Field(min_length=1, max_length=48)
    max_jobs: int = Field(ge=1, le=100)
    expires_at: str = Field(min_length=10, max_length=80)


@router.get("/trials/current")
def current_paid_trial(connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return get_trial_summary(connection, owner.id)


@router.post("/trials", status_code=201)
def create_paid_trial(payload: PaidTrialRequest, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return create_trial_authorization(
        connection, owner.id, profile_id=payload.profile_id,
        profile_version=payload.profile_version, total_cap_usd=payload.total_cap_usd,
        per_send_cap_usd=payload.per_send_cap_usd, max_jobs=payload.max_jobs,
        expires_at=payload.expires_at,
    )


@router.post("/trials/{trial_id}/revoke")
def revoke_paid_trial(trial_id: str, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return revoke_trial_authorization(connection, owner.id, trial_id)


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
        if payload.provider not in {"openrouter", "ollama"}:
            raise ValidationError("Unknown provider")
        secret = _store(request).get(owner.id, payload.credential_id)
        if payload.provider == "ollama":
            verifier = OllamaCloudVerifier()
            if payload.endpoint != OLLAMA_CLOUD_ENDPOINT:
                raise ValidationError("Only the pinned Ollama Cloud endpoint is supported")
            if payload.provider_tag is not None:
                raise ValidationError("An Ollama Cloud provider tag is unsupported")
            endpoint, model = OLLAMA_CLOUD_ENDPOINT, payload.model
        else:
            verifier = request.app.state.provider_verifier
            endpoint, model = payload.endpoint, payload.model
        snapshot = verifier.verify(secret, model, endpoint, provider_tag=payload.provider_tag)
        snapshot["secret_version"] = payload.credential_id
        return persist_model_profile(connection, owner.id, snapshot)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Provider metadata could not be verified") from exc


@router.post("/profiles/custom", status_code=201)
def create_custom_profile(payload: CustomProfileRequest, request: Request, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    try:
        secret_version = None
        if payload.credential_id:
            _store(request).get(owner.id, payload.credential_id)
            secret_version = payload.credential_id
        profile = validate_custom_profile(
            endpoint=payload.endpoint, model=payload.model,
            secret_version=secret_version,
        )
        return persist_model_profile(connection, owner.id, profile)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Custom provider profile could not be saved") from exc


@router.get("/settings")
def settings(connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return get_owner_settings(connection, owner.id)


@router.put("/settings")
def update_settings(payload: SettingsRequest, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    existing = get_owner_settings(connection, owner.id)
    existing_roles = existing.get("roles") or {}
    narrator_binding = existing_roles.get("narrator") or {}
    narrator_id = payload.narrator_profile_id or narrator_binding.get("id")
    if not narrator_id:
        raise ValidationError("A narrator profile is required")

    def load_binding(role: str, requested_id: str | None):
        previous = existing_roles.get(role) or {}
        profile_id = requested_id or previous.get("id")
        if not profile_id:
            return None
        # A budget/mode-only update keeps the exact immutable version already
        # selected.  An explicit profile id is the user's intentional switch
        # and may resolve the latest verified version for that id.
        version = None if requested_id else previous.get("version")
        return get_model_profile(connection, owner.id, profile_id, version)

    narrator_profile = load_binding("narrator", payload.narrator_profile_id)
    def binding(profile):
        return {"id": profile["id"], "version": profile["version"], "profile_hash": profile.get("profile_hash") or profile_hash({key: value for key, value in profile.items() if key not in {"version", "profile_hash"}})}
    roles = {"narrator": binding(narrator_profile)}
    context_id = payload.context_profile_id or ((existing_roles.get("context") or {}).get("id"))
    if context_id:
        context_profile = load_binding("context", payload.context_profile_id)
        if not context_profile.get("structured_output") or not context_profile.get("native_structured_output") or not context_profile.get("structured_schema_parameter"):
            raise ValidationError("Context role requires native strict schema support")
        roles["context"] = binding(context_profile)
    consolidation_id = payload.consolidation_profile_id or ((existing_roles.get("consolidation") or {}).get("id"))
    if consolidation_id:
        consolidation_profile = load_binding("consolidation", payload.consolidation_profile_id)
        if not consolidation_profile.get("structured_output") or not consolidation_profile.get("native_structured_output") or not consolidation_profile.get("structured_schema_parameter"):
            raise ValidationError("Consolidation role requires native strict schema support")
        roles["consolidation"] = binding(consolidation_profile)
    mode = payload.mode or existing.get("mode", "economy")
    policy = payload.policy or existing.get("policy", "free_only")
    cap = payload.confirmed_usd_cap if payload.confirmed_usd_cap is not None else existing.get("confirmed_usd_cap")
    budgets = payload.budgets if payload.budgets is not None else (existing.get("budgets") if existing.get("budgets_configured") else {})
    if mode == "quality":
        if "context" not in roles:
            raise ValidationError("Quality mode requires a context profile")
    return save_owner_settings(connection, owner.id, {"roles": roles, "mode": mode, "policy": policy, "confirmed_usd_cap": cap, "budgets": budgets or {}})
