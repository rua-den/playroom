from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import httpx2 as httpx

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
    if policy not in {"free_only", "capped_paid"}:
        raise ValidationError("Unknown cost policy")
    if policy == "capped_paid":
        from decimal import Decimal, InvalidOperation
        if cap is None or cap <= 0: raise ValidationError("A confirmed USD cap is required")
        try: estimated_cost = Decimal(str(profile.get("estimated_cost_usd", "0")))
        except InvalidOperation as exc: raise ValidationError("Profile price is invalid") from exc
        if estimated_cost > Decimal(str(cap)):
            raise ValidationError("Estimated cost exceeds the confirmed USD cap")


class OpenRouterVerifier:
    def __init__(self, *, base_url: str = "https://openrouter.ai/api/v1", http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = http_client or httpx.Client(timeout=30)

    def verify(self, api_key: str, model: str, endpoint: str) -> dict:
        if endpoint != f"{self.base_url}/chat/completions":
            raise ValidationError("Only the pinned OpenRouter chat endpoint is supported")
        headers = {"Authorization": f"Bearer {api_key}"}
        model_response = self.client.get(f"{self.base_url}/models/{model}", headers=headers)
        key_response = self.client.get(f"{self.base_url}/key", headers=headers)
        if model_response.status_code != 200 or key_response.status_code != 200:
            raise ValidationError("OpenRouter model or credential metadata could not be verified")
        model_data, key_data = model_response.json().get("data", {}), key_response.json().get("data", {})
        pricing = model_data.get("pricing") or {}
        try: prompt = Decimal(str(pricing["prompt"])); completion = Decimal(str(pricing["completion"]))
        except (KeyError, InvalidOperation) as exc: raise ValidationError("OpenRouter pricing is unknown") from exc
        tier = "free" if key_data.get("is_free_tier") is True and prompt == 0 and completion == 0 else "paid" if key_data.get("limit") is not None else "unknown"
        if tier == "unknown": raise ValidationError("OpenRouter billing eligibility is unknown")
        return {"provider": "openrouter", "endpoint": endpoint, "model": model, "pricing": {"prompt": str(prompt), "completion": str(completion), "currency": "USD"}, "credential_tier": tier, "structured_output": bool(model_data.get("supported_parameters") and "response_format" in model_data["supported_parameters"]), "supported_parameters": model_data.get("supported_parameters", []), "metadata_source": f"{self.base_url}/models/{model}", "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "pricing_verified": True}
