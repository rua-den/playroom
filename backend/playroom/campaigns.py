from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from .db import transaction
from .domain import Campaign, NotFound, StateConflict, ValidationError, require_uuid
from .timeline import _advance_checkpoint, _branch_row, load_state_checkpoint, utc_now


DEFAULT_STYLE = {
    "language": "vi",
    "length": "medium",
    "heading_level": "low",
    "emoji_level": "low",
    "viewpoint": "third_person",
    "agency_rule": "AI không tự tạo lời thoại, suy nghĩ hoặc quyết định mới cho persona người chơi.",
}


def _new_profile(connection: sqlite3.Connection, campaign_id: str, profile_key: str, kind: str, data: dict, version: int = 1, supersedes: str | None = None) -> str:
    if not isinstance(data, dict):
        raise ValidationError("Profile data must be an object")
    profile_id = str(uuid4())
    connection.execute(
        "INSERT INTO profile_versions(id, campaign_id, profile_key, kind, version, data_json, supersedes_version_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_id, campaign_id, profile_key, kind, version, json.dumps(data, ensure_ascii=False, sort_keys=True), supersedes, utc_now()),
    )
    return profile_id


def create_campaign(connection: sqlite3.Connection, owner_id: str, title: str, world: dict, characters: list[dict], persona: dict, *, style: dict | None = None) -> Campaign:
    owner_id = require_uuid(owner_id, "owner_id")
    if not title.strip():
        raise ValidationError("Campaign title is required")
    for profile in [world, persona, *(characters or [])]:
        if not isinstance(profile, dict):
            raise ValidationError("Campaign profiles must be objects")
    character_ids = [require_uuid(character.get("id"), "character id") for character in characters]
    if len(set(character_ids)) != len(character_ids):
        raise ValidationError("Character IDs must be unique")
    for index, character in enumerate(characters):
        character["id"] = character_ids[index]
        aliases = character.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ValidationError("Character aliases must be a list of strings")
    campaign_id, branch_id = str(uuid4()), str(uuid4())
    now = utc_now()
    profile_versions: dict[str, str] = {}
    profile_values = [("world", "world", world), ("persona", "persona", persona), ("style", "style", style or DEFAULT_STYLE)]
    profile_values.extend((f"character:{character['id']}", "character", character) for character in characters)
    with transaction(connection):
        if connection.execute("SELECT 1 FROM owners WHERE id = ?", (owner_id,)).fetchone() is None:
            raise NotFound("Owner not found")
        connection.execute("INSERT INTO campaigns(id, owner_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (campaign_id, owner_id, title.strip(), now, now))
        for profile_key, kind, data in profile_values:
            profile_versions[profile_key] = _new_profile(connection, campaign_id, profile_key, kind, data)
        connection.execute("INSERT INTO branches(id, campaign_id, name, state_version, created_at) VALUES (?, ?, 'main', 0, ?)", (branch_id, campaign_id, now))
        scene_id = str(uuid4())
        checkpoint_id = str(uuid4())
        connection.execute("INSERT INTO scene_versions(id, campaign_id, branch_id, version, data_json, effective_state_version, effective_checkpoint_id, created_at) VALUES (?, ?, ?, 1, ?, 0, ?, ?)", (scene_id, campaign_id, branch_id, json.dumps({"focus_scene_id": None, "scenes": {}}, ensure_ascii=False), checkpoint_id, now))
        snapshot = {
            "profile_versions": profile_versions,
            "memory_versions": {},
            "pending_memory_versions": {},
            "reviewed_memory_versions": {},
            "scene_version_id": scene_id,
            "retrieval_policy": "auto",
            "turn_id": None,
            "revision_id": None,
            "selected_revision_ids": [],
        }
        _advance_checkpoint(connection, campaign_id, branch_id, 0, snapshot, checkpoint_id=checkpoint_id)
    return Campaign(campaign_id, owner_id, title.strip(), branch_id, tuple(character_ids), profile_versions)


def list_campaigns(connection: sqlite3.Connection, owner_id: str) -> list[dict]:
    owner_id = require_uuid(owner_id, "owner_id")
    rows = connection.execute("SELECT id, title, created_at, updated_at FROM campaigns WHERE owner_id = ? ORDER BY updated_at DESC, id", (owner_id,)).fetchall()
    return [dict(row) for row in rows]


def get_campaign(connection: sqlite3.Connection, campaign_id: str, owner_id: str) -> dict:
    campaign_id, owner_id = require_uuid(campaign_id, "campaign_id"), require_uuid(owner_id, "owner_id")
    row = connection.execute("SELECT id, owner_id, title, created_at, updated_at FROM campaigns WHERE id = ? AND owner_id = ?", (campaign_id, owner_id)).fetchone()
    if row is None:
        raise NotFound("Campaign not found")
    branch = connection.execute("SELECT id, name, state_version, head_checkpoint_id FROM branches WHERE campaign_id = ? ORDER BY created_at LIMIT 1", (campaign_id,)).fetchone()
    checkpoint = load_state_checkpoint(connection, campaign_id, branch["id"], branch["head_checkpoint_id"], owner_id)
    profiles = {}
    for key, version_id in checkpoint.snapshot["profile_versions"].items():
        profile = connection.execute("SELECT kind, data_json FROM profile_versions WHERE id = ?", (version_id,)).fetchone()
        profiles[key] = {"kind": profile["kind"], "data": json.loads(profile["data_json"])}
    return {**dict(row), "branch_id": branch["id"], "state_version": branch["state_version"], "checkpoint_id": branch["head_checkpoint_id"], "profiles": profiles}


def get_effective_profile(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, profile_key: str, owner_id: str | None = None) -> dict:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position, owner_id)
    version_id = checkpoint.snapshot["profile_versions"].get(profile_key)
    if version_id is None:
        raise NotFound("Profile is not present at this state position")
    row = connection.execute("SELECT profile_key, kind, data_json FROM profile_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
    if row is None or row["profile_key"] != profile_key:
        raise NotFound("Profile version does not belong to this campaign")
    return json.loads(row["data_json"])


def update_profile(connection: sqlite3.Connection, campaign_id: str, branch_id: str, profile_key: str, data: dict, *, expected_state_version: int, owner_id: str | None = None):
    if not isinstance(data, dict):
        raise ValidationError("Profile data must be an object")
    with transaction(connection):
        branch = _branch_row(connection, campaign_id, branch_id, owner_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"], owner_id)
        old_id = checkpoint.snapshot["profile_versions"].get(profile_key)
        if old_id is None:
            raise NotFound("Profile not found")
        old = connection.execute("SELECT kind, version FROM profile_versions WHERE id = ? AND campaign_id = ?", (old_id, campaign_id)).fetchone()
        if profile_key.startswith("character:"):
            char_id = require_uuid(profile_key.partition(":")[2], "character id")
            if data.get("id") != char_id:
                raise ValidationError("A character profile cannot change its identity")
        new_id = _new_profile(connection, campaign_id, profile_key, old["kind"], data, old["version"] + 1, old_id)
        snapshot = dict(checkpoint.snapshot)
        snapshot["profile_versions"] = dict(snapshot["profile_versions"])
        snapshot["profile_versions"][profile_key] = new_id
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot)
