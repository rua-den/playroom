from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx2 as httpx

from .domain import NotFound, ValidationError


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
    provider_tag: str | None = None
    supported_parameters: tuple[str, ...] = ()
    pricing: dict | None = None

    @property
    def snapshot(self) -> dict:
        return {"id": self.id, "version": self.version, "provider": self.provider, "endpoint": self.endpoint, "model": self.model, "context_limit": self.context_limit, "output_limit": self.output_limit, "credential_tier": self.credential_tier, "pricing_verified": self.pricing_verified, "structured_output": self.structured_output, "reasoning_parameters": list(self.reasoning_parameters), "secret_version": self.secret_version, "provider_tag": self.provider_tag, "supported_parameters": list(self.supported_parameters), "pricing": self.pricing}


def profile_hash(profile: dict) -> str:
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _money(value: object, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"Verified {field} price is invalid") from exc
    if not result.is_finite() or result < 0:
        raise ValidationError(f"Verified {field} price is invalid")
    return result


def estimate_cost_usd(profile: dict, reserved_input_tokens: int, reserved_completion_tokens: int) -> Decimal:
    pricing = profile.get("pricing") or {}
    prompt = _money(pricing.get("prompt"), field="prompt")
    completion = _money(pricing.get("completion"), field="completion")
    try:
        reserved_input_tokens = int(reserved_input_tokens)
        reserved_completion_tokens = int(reserved_completion_tokens)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Reserved token allowances are invalid") from exc
    if reserved_input_tokens < 0 or reserved_completion_tokens < 0:
        raise ValidationError("Reserved token allowances must be nonnegative")
    return (prompt * Decimal(reserved_input_tokens) + completion * Decimal(reserved_completion_tokens)) / Decimal(1_000_000)


def validate_dispatch(profile: dict, policy: str, estimated_total, cap: Decimal | int | str | None = None) -> None:
    if not profile.get("endpoint") or not profile.get("model") or not profile.get("secret_version"):
        raise ValidationError("Provider profile is missing a pinned endpoint, model, or credential version")
    if not profile.get("pricing_verified") or profile.get("credential_tier") in {None, "unknown"}:
        raise ValidationError("Provider pricing and billing eligibility must be verified")
    if policy not in {"free_only", "capped_paid"}:
        raise ValidationError("Unknown cost policy")
    if policy == "free_only" and profile.get("credential_tier") != "free":
        raise ValidationError("free_only requires a verified free credential tier")
    if policy == "capped_paid":
        if cap is None:
            raise ValidationError("A confirmed USD cap is required")
        try:
            confirmed_cap = Decimal(str(cap))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("A confirmed USD cap is required") from exc
        if not confirmed_cap.is_finite() or confirmed_cap <= 0:
            raise ValidationError("A confirmed USD cap is required")
        if isinstance(estimated_total, dict):
            input_key = "input_tokens" if "input_tokens" in estimated_total else "reserved_input_tokens"
            completion_key = "completion_tokens" if "completion_tokens" in estimated_total else "reserved_completion_tokens"
            if input_key not in estimated_total or completion_key not in estimated_total:
                raise ValidationError("Reserved token allowance is unknown")
            try:
                input_tokens = int(estimated_total[input_key])
                completion_tokens = int(estimated_total[completion_key])
            except (TypeError, ValueError) as exc:
                raise ValidationError("Reserved token allowance is invalid") from exc
            estimated_cost = estimate_cost_usd(profile, input_tokens, completion_tokens)
        elif "pricing" in profile:
            input_tokens, completion_tokens = int(estimated_total), int(profile.get("reserved_completion_tokens", 0))
            estimated_cost = estimate_cost_usd(profile, input_tokens, completion_tokens)
        elif "estimated_cost_usd" in profile:
            try:
                estimated_cost = _money(profile["estimated_cost_usd"], field="estimated")
            except ValidationError as exc:
                raise ValidationError("Estimated cost or verified prices is invalid") from exc
        else:
            raise ValidationError("Estimated cost or verified prices is invalid")
        if estimated_cost > confirmed_cap:
            raise ValidationError("Estimated cost exceeds the confirmed USD cap")


def _model_parts(model: str) -> tuple[str, str]:
    base = model[:-5] if model.endswith(":free") else model
    author, separator, slug = base.partition("/")
    if not separator or not author or not slug:
        raise ValidationError("OpenRouter model must use author/slug form")
    return author, slug


class OpenRouterVerifier:
    def __init__(self, *, base_url: str = "https://openrouter.ai/api/v1", http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = http_client or httpx.Client(timeout=30)

    def verify(self, api_key: str, model: str, endpoint: str, *, provider_tag: str | None = None) -> dict:
        if endpoint != f"{self.base_url}/chat/completions":
            raise ValidationError("Only the pinned OpenRouter chat endpoint is supported")
        if not api_key:
            raise ValidationError("Provider credential could not be verified")
        author, slug = _model_parts(model)
        headers = {"Authorization": f"Bearer {api_key}"}
        source = f"{self.base_url}/models/{quote(author, safe='')}/{quote(slug, safe=':')}/endpoints"
        try:
            endpoint_response = self.client.get(source, headers=headers)
            key_response = self.client.get(f"{self.base_url}/key", headers=headers)
        except Exception as exc:
            raise ValidationError("OpenRouter metadata could not be reached") from exc
        if endpoint_response.status_code != 200 or key_response.status_code != 200:
            raise ValidationError("OpenRouter model or credential metadata could not be verified")
        raw_endpoints = endpoint_response.json().get("data", [])
        if isinstance(raw_endpoints, dict):
            raw_endpoints = raw_endpoints.get("endpoints", [])
        candidates = [item for item in raw_endpoints if isinstance(item, dict)]
        if provider_tag is not None:
            candidates = [item for item in candidates if item.get("provider_id") == provider_tag or item.get("provider_name") == provider_tag or item.get("tag") == provider_tag]
        if not candidates:
            raise ValidationError("Requested provider endpoint is unavailable")
        selected = candidates[0]
        selected_tag = selected.get("provider_id") or selected.get("tag") or selected.get("provider_name")
        if not selected_tag:
            raise ValidationError("Provider endpoint identity is unknown")
        pricing = selected.get("pricing") or {}
        prompt = _money(pricing.get("prompt"), field="prompt")
        completion = _money(pricing.get("completion"), field="completion")
        supported = tuple(str(item) for item in (selected.get("supported_parameters") or []))
        key_data = key_response.json().get("data", {})
        free_variant = model.endswith(":free") and prompt == 0 and completion == 0
        key_flag = key_data.get("is_free_tier")
        if not isinstance(key_flag, bool):
            raise ValidationError("OpenRouter billing eligibility is unknown")
        if free_variant:
            tier = "free"
        elif key_flag is False:
            tier = "paid"
        else:
            raise ValidationError("OpenRouter billing eligibility is unknown")
        context_limit = selected.get("context_length", selected.get("context_window"))
        output_limit = selected.get("max_completion_tokens", selected.get("output_limit"))
        if not isinstance(context_limit, int) or not isinstance(output_limit, int) or context_limit <= 0 or output_limit <= 0:
            raise ValidationError("OpenRouter endpoint limits are unknown")
        return {"provider": "openrouter", "endpoint": endpoint, "endpoint_id": selected.get("id") or selected_tag, "model": model, "provider_tag": selected_tag, "context_limit": context_limit, "output_limit": output_limit, "pricing": {"prompt": str(prompt), "completion": str(completion), "currency": "USD"}, "credential_tier": tier, "structured_output": "response_format" in supported or "structured_outputs" in supported, "supported_parameters": list(supported), "reasoning_parameters": [item for item in supported if "reason" in item], "data_policy": selected.get("data_policy"), "metadata_source": source, "credential_metadata": {"is_free_tier": key_flag, "free_model_daily_requests": key_data.get("free_model_daily_requests")}, "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "pricing_verified": True}


def ensure_profile_tables(connection) -> None:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS model_profile_versions (
        id TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, profile_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(owner_id, id, version)
    );
    CREATE TRIGGER IF NOT EXISTS prevent_model_profile_update BEFORE UPDATE ON model_profile_versions BEGIN SELECT RAISE(ABORT, 'model profiles are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS prevent_model_profile_delete BEFORE DELETE ON model_profile_versions BEGIN SELECT RAISE(ABORT, 'model profiles are immutable'); END;
    """)


def persist_model_profile(connection, owner_id: str, profile: dict) -> dict:
    from .timeline import utc_now
    ensure_profile_tables(connection)
    snapshot = json.loads(json.dumps(profile, sort_keys=True, ensure_ascii=False))
    if not snapshot.get("id"):
        identity = {key: snapshot.get(key) for key in ("provider", "model", "endpoint", "provider_tag", "endpoint_id")}
        snapshot["id"] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]
    digest = profile_hash(snapshot)
    row = connection.execute("SELECT version, snapshot_json FROM model_profile_versions WHERE owner_id=? AND id=? ORDER BY version DESC LIMIT 1", (owner_id, snapshot["id"])).fetchone()
    if row:
        existing = json.loads(row["snapshot_json"])
        existing_base = {key: value for key, value in existing.items() if key not in {"version", "profile_hash"}}
        if profile_hash(existing_base) == digest:
            return existing
    version = (row["version"] if row else 0) + 1
    saved = {**snapshot, "version": version, "profile_hash": digest}
    connection.execute("INSERT INTO model_profile_versions(id,owner_id,version,snapshot_json,profile_hash,created_at) VALUES(?,?,?,?,?,?)", (snapshot["id"], owner_id, version, json.dumps(saved, sort_keys=True, ensure_ascii=False), digest, utc_now()))
    return saved


def list_model_profiles(connection, owner_id: str) -> list[dict]:
    ensure_profile_tables(connection)
    rows = connection.execute("SELECT p.snapshot_json FROM model_profile_versions p WHERE p.owner_id=? AND p.version=(SELECT MAX(p2.version) FROM model_profile_versions p2 WHERE p2.owner_id=p.owner_id AND p2.id=p.id) ORDER BY p.id", (owner_id,)).fetchall()
    return [json.loads(row["snapshot_json"]) for row in rows]


def get_model_profile(connection, owner_id: str, profile_id: str, version: int | None = None) -> dict:
    ensure_profile_tables(connection)
    row = connection.execute("SELECT snapshot_json FROM model_profile_versions WHERE owner_id=? AND id=? AND (? IS NULL OR version=?) ORDER BY version DESC LIMIT 1", (owner_id, profile_id, version, version)).fetchone()
    if row is None:
        raise NotFound("Model profile not found")
    return json.loads(row["snapshot_json"])
