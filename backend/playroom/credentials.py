from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from .domain import NotFound, ValidationError


@dataclass(frozen=True)
class CredentialVersion:
    id: str
    owner_id: str
    version: int


class CredentialStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try: os.chmod(self.root, 0o700)
        except OSError: pass

    def _path(self, owner_id: str, credential_id: str) -> Path:
        if any(part in owner_id for part in ("..", "/", "\\")) or owner_id != Path(owner_id).name:
            raise ValidationError("Invalid owner ID")
        if any(part in credential_id for part in ("..", "/", "\\")) or credential_id != Path(credential_id).name:
            raise ValidationError("Invalid credential ID")
        path = (self.root / owner_id / f"{credential_id}.json").resolve()
        if self.root not in path.parents: raise ValidationError("Invalid credential path")
        return path

    def put(self, owner_id: str, secret: str) -> CredentialVersion:
        if not secret or "\n" in secret: raise ValidationError("Credential is required")
        owner_dir = self.root / owner_id; owner_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(owner_dir.glob("*.json"))
        version = len(existing) + 1; credential_id = secrets.token_hex(16)
        path = self._path(owner_id, credential_id)
        path.write_text(json.dumps({"id": credential_id, "owner_id": owner_id, "version": version, "secret": secret, "revoked": False}), encoding="utf-8")
        try: os.chmod(path, 0o600)
        except OSError: pass
        return CredentialVersion(credential_id, owner_id, version)

    def _read(self, owner_id: str, credential_id: str) -> dict:
        path = self._path(owner_id, credential_id)
        if not path.exists(): raise NotFound("Credential version not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def get(self, owner_id: str, credential_id: str) -> str:
        record = self._read(owner_id, credential_id)
        if record.get("revoked"): raise ValidationError("Credential version is revoked")
        return record["secret"]

    def masked(self, owner_id: str, credential_id: str) -> dict:
        record = self._read(owner_id, credential_id)
        secret = record.get("secret", "")
        suffix = secret[-3:] if len(secret) >= 3 else "***"
        masked = "***" if len(secret) < 3 else secret[:3] + "***" + suffix
        return {"id": record["id"], "version": record["version"], "revoked": bool(record.get("revoked")), "masked": masked, "secret": None}

    def list_masked(self, owner_id: str) -> list[dict]:
        owner_dir = self.root / owner_id
        if not owner_dir.exists():
            return []
        records = []
        for path in sorted(owner_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(self.masked(owner_id, record["id"]))
        return records

    def revoke(self, owner_id: str, credential_id: str) -> None:
        path = self._path(owner_id, credential_id)
        record = self._read(owner_id, credential_id); record["revoked"] = True
        path.write_text(json.dumps(record), encoding="utf-8")
