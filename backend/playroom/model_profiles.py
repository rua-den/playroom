from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .domain import ValidationError


@dataclass(frozen=True)
class ModelProfile:
    id: str
    version: int
    provider: str
    endpoint: str
    model: str
    context_limit: int
    output_limit: int
    credential_tier: str
    pricing_verified: bool
    structured_output: bool = False
    reasoning_parameters: tuple[str, ...] = ()
    secret_version: str | None = None

    @property
    def snapshot(self) -> dict:
        return {"id": self.id, "version": self.version, "provider": self.provider, "endpoint": self.endpoint, "model": self.model, "context_limit": self.context_limit, "output_limit": self.output_limit, "credential_tier": self.credential_tier, "pricing_verified": self.pricing_verified, "structured_output": self.structured_output, "reasoning_parameters": list(self.reasoning_parameters), "secret_version": self.secret_version}


def profile_hash(profile: dict) -> str:
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_dispatch(profile: dict, policy: str, estimated_total: int, cap: int | None = None) -> None:
    if not profile.get("endpoint") or not profile.get("model") or not profile.get("secret_version"):
        raise ValidationError("Provider profile is missing a pinned endpoint, model, or credential version")
    if not profile.get("pricing_verified") or profile.get("credential_tier") in {None, "unknown"}:
        raise ValidationError("Provider pricing and billing eligibility must be verified")
    if policy == "free_only" and profile.get("credential_tier") != "free":
        raise ValidationError("free_only requires a verified free credential tier")
    if policy == "capped_paid" and (cap is None or estimated_total > cap):
        raise ValidationError("Estimated generation allowance exceeds the confirmed cap")
