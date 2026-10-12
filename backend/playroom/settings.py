from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .domain import NotFound, ValidationError


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
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS owner_settings_versions (
        owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, settings_json TEXT NOT NULL, settings_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(owner_id, revision)
    );
    CREATE TRIGGER IF NOT EXISTS prevent_owner_settings_update BEFORE UPDATE ON owner_settings_versions BEGIN SELECT RAISE(ABORT, 'owner settings are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS prevent_owner_settings_delete BEFORE DELETE ON owner_settings_versions BEGIN SELECT RAISE(ABORT, 'owner settings are immutable'); END;
    """)


def _validated_settings(settings: dict) -> dict:
    roles = settings.get("roles") or {}
    if set(roles) != {"context", "narrator", "consolidation"} or not all(isinstance(roles[name], str) and roles[name] for name in roles):
        raise ValidationError("Three context, narrator, and consolidation role bindings are required")
    mode = settings.get("mode", "economy")
    policy = settings.get("policy", "free_only")
    if mode not in {"economy", "quality"} or policy not in {"free_only", "capped_paid"}:
        raise ValidationError("Unknown runtime mode or cost policy")
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
    return {"roles": dict(roles), "mode": mode, "policy": policy, "confirmed_usd_cap": cap}


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
