from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .domain import ValidationError


# Internal deterministic fixture profile. It is not a provider model or a claim
# about any external model's capabilities; live profiles require verified caps.
DEFAULT_TEST_CONTEXT_PROFILE = {
    "profile_id": "fake-context-test",
    "label": "Synthetic fixture only",
    "is_test_profile": True,
    "input_limit": 12000,
    "context_window": 16512,
    "output_limit": 4000,
    "wrapper_buffer": 512,
    "requested_output": 4000,
    "token_count_mode": "estimated",
}

DEFAULT_NARRATOR_PROFILE = {
    "profile_id": "fake-narrator-test",
    "label": "Synthetic fixture narrator",
    "provider": "fake",
    "endpoint": "fake://local",
    "model": "synthetic-fixture",
    "context_limit": 12000,
    "output_limit": 4000,
    "credential_tier": "free",
    "pricing_verified": True,
    "secret_version": "synthetic",
    "is_test_profile": True,
}


def config_hash(config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_configuration_tables(connection) -> None:
    try:
        connection.execute("SELECT 1 FROM owner_settings_versions LIMIT 0")
    except Exception as exc:
        raise RuntimeError("Configuration schema must be created by startup migration") from exc


def _validated_settings(settings: dict) -> dict:
    mode = settings.get("mode", "economy")
    policy = settings.get("policy", "free_only")
    if mode not in {"economy", "quality"} or policy not in {"free_only", "capped_paid"}:
        raise ValidationError("Unknown runtime mode or cost policy")
    roles = settings.get("roles") or {}
    required = {"narrator"} if mode == "economy" else {"context", "narrator", "consolidation"}
    if not required.issubset(roles) or not all(isinstance(roles[name], dict) for name in required):
        raise ValidationError("Selected runtime roles require immutable profile version bindings")
    if mode == "economy":
        roles = {"context": None, "narrator": roles["narrator"], "consolidation": None}
    elif set(roles) != {"context", "narrator", "consolidation"} or not all(isinstance(roles[name], dict) for name in roles):
        raise ValidationError("Three immutable context, narrator, and consolidation bindings are required")
    cap = settings.get("confirmed_usd_cap")
    if policy == "capped_paid":
        try:
            cap_value = Decimal(str(cap))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValidationError("A confirmed USD cap is required") from exc
        if not cap_value.is_finite() or cap_value <= 0:
            raise ValidationError("A confirmed USD cap is required")
        cap = format(cap_value, "f")
    else:
        cap = None
    return {"roles": roles, "mode": mode, "policy": policy, "confirmed_usd_cap": cap}


def save_owner_settings(connection, owner_id: str, settings: dict) -> dict:
    ensure_configuration_tables(connection)
    validated = _validated_settings(settings)
    row = connection.execute("SELECT COALESCE(MAX(revision), 0) AS revision FROM owner_settings_versions WHERE owner_id=?", (owner_id,)).fetchone()
    revision = int(row["revision"]) + 1
    digest = config_hash(validated)
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    connection.execute("INSERT INTO owner_settings_versions(owner_id,revision,settings_json,settings_hash,created_at) VALUES(?,?,?,?,?)", (owner_id, revision, json.dumps(validated, sort_keys=True), digest, created))
    return {**validated, "settings_revision": revision, "settings_hash": digest, "created_at": created}


def get_owner_settings(connection, owner_id: str) -> dict:
    ensure_configuration_tables(connection)
    row = connection.execute("SELECT revision, settings_json, settings_hash, created_at FROM owner_settings_versions WHERE owner_id=? ORDER BY revision DESC LIMIT 1", (owner_id,)).fetchone()
    if row is None:
        return {"settings_revision": 0, "settings_hash": config_hash({}), "roles": {}, "mode": "economy", "policy": "free_only", "confirmed_usd_cap": None}
    return {**json.loads(row["settings_json"]), "settings_revision": row["revision"], "settings_hash": row["settings_hash"], "created_at": row["created_at"]}
