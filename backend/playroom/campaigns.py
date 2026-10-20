from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from uuid import uuid4

from .db import assert_branch_mutable, transaction
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


def _validate_character(data: dict, expected_id: str | None = None) -> dict:
    if not isinstance(data, dict):
        raise ValidationError("Character profile must be an object")
    character_id = require_uuid(data.get("id"), "character id")
    if expected_id is not None and character_id != expected_id:
        raise ValidationError("A character profile cannot change its identity")
    aliases = data.get("aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
        raise ValidationError("Character aliases must be a list of strings")
    return {**data, "id": character_id, "aliases": aliases}


def create_campaign(connection: sqlite3.Connection, owner_id: str, title: str, world: dict, characters: list[dict], persona: dict, *, style: dict | None = None, _within_transaction: bool = False) -> Campaign:
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
    # Import uses one outer BEGIN IMMEDIATE across campaign and all selected turns.
    with (nullcontext() if _within_transaction else transaction(connection)):
        if connection.execute("SELECT 1 FROM owners WHERE id = ?", (owner_id,)).fetchone() is None:
            raise NotFound("Owner not found")
        connection.execute("INSERT INTO campaigns(id, owner_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (campaign_id, owner_id, title.strip(), now, now))
        for profile_key, kind, data in profile_values:
            profile_versions[profile_key] = _new_profile(connection, campaign_id, profile_key, kind, data)
        connection.execute("INSERT INTO branches(id, campaign_id, name, state_version, created_at) VALUES (?, ?, 'main', 0, ?)", (branch_id, campaign_id, now))
        scene_id = str(uuid4())
        checkpoint_id = str(uuid4())
        connection.execute("INSERT INTO scene_versions(id, campaign_id, branch_id, version, data_json, effective_state_version, effective_checkpoint_id, created_at) VALUES (?, ?, ?, 1, ?, 1, ?, ?)", (scene_id, campaign_id, branch_id, json.dumps({"focus_scene_id": None, "scenes": {}}, ensure_ascii=False), checkpoint_id, now))
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


def _campaign_summary(row: sqlite3.Row) -> dict:
    return dict(row)


def list_campaigns(connection: sqlite3.Connection, owner_id: str, *, trashed: bool = False) -> list[dict]:
    owner_id = require_uuid(owner_id, "owner_id")
    if trashed:
        predicate = "deleted_at IS NOT NULL"
    else:
        predicate = "deleted_at IS NULL"
    rows = connection.execute(f"SELECT id, title, created_at, updated_at, archived_at, deleted_at FROM campaigns WHERE owner_id = ? AND {predicate} ORDER BY archived_at IS NOT NULL, updated_at DESC, id", (owner_id,)).fetchall()
    return [_campaign_summary(row) for row in rows]


def get_campaign(connection: sqlite3.Connection, campaign_id: str, owner_id: str) -> dict:
    campaign_id, owner_id = require_uuid(campaign_id, "campaign_id"), require_uuid(owner_id, "owner_id")
    row = connection.execute("SELECT id, owner_id, title, created_at, updated_at, archived_at, deleted_at FROM campaigns WHERE id = ? AND owner_id = ? AND deleted_at IS NULL", (campaign_id, owner_id)).fetchone()
    if row is None:
        raise NotFound("Campaign not found")
    branch = connection.execute("SELECT id, name, state_version, head_checkpoint_id FROM branches WHERE campaign_id = ? ORDER BY created_at LIMIT 1", (campaign_id,)).fetchone()
    checkpoint = load_state_checkpoint(connection, campaign_id, branch["id"], branch["head_checkpoint_id"], owner_id)
    profiles = {}
    for key, version_id in checkpoint.snapshot["profile_versions"].items():
        profile = connection.execute("SELECT kind, data_json FROM profile_versions WHERE id = ?", (version_id,)).fetchone()
        profiles[key] = {"kind": profile["kind"], "data": json.loads(profile["data_json"])}
    return {**dict(row), "branch_id": branch["id"], "state_version": branch["state_version"], "checkpoint_id": branch["head_checkpoint_id"], "profiles": profiles}


def trash_campaign(connection: sqlite3.Connection, campaign_id: str, owner_id: str) -> dict:
    campaign_id, owner_id = require_uuid(campaign_id, "campaign_id"), require_uuid(owner_id, "owner_id")
    with transaction(connection):
        row = connection.execute("SELECT id, title, created_at, updated_at, archived_at, deleted_at FROM campaigns WHERE id=? AND owner_id=?", (campaign_id, owner_id)).fetchone()
        if row is None:
            raise NotFound("Campaign not found")
        if connection.execute("SELECT 1 FROM generation_branch_guards g JOIN branches b ON b.id=g.branch_id WHERE b.campaign_id=? LIMIT 1", (campaign_id,)).fetchone() is not None:
            raise StateConflict("Campaign has an active generation")
        if connection.execute("SELECT 1 FROM generation_jobs WHERE campaign_id=? AND status IN ('queued','running','cancelling','interrupted','candidate') LIMIT 1", (campaign_id,)).fetchone() is not None:
            raise StateConflict("Campaign has an active generation")
        deleted_at = row["deleted_at"] or utc_now()
        connection.execute("UPDATE campaigns SET deleted_at=? WHERE id=? AND owner_id=?", (deleted_at, campaign_id, owner_id))
        updated = connection.execute("SELECT id, title, created_at, updated_at, archived_at, deleted_at FROM campaigns WHERE id=? AND owner_id=?", (campaign_id, owner_id)).fetchone()
        return _campaign_summary(updated)


def restore_campaign(connection: sqlite3.Connection, campaign_id: str, owner_id: str) -> dict:
    campaign_id, owner_id = require_uuid(campaign_id, "campaign_id"), require_uuid(owner_id, "owner_id")
    with transaction(connection):
        row = connection.execute("SELECT id, title, created_at, updated_at, archived_at, deleted_at FROM campaigns WHERE id=? AND owner_id=?", (campaign_id, owner_id)).fetchone()
        if row is None:
            raise NotFound("Campaign not found")
        connection.execute("UPDATE campaigns SET deleted_at=NULL WHERE id=? AND owner_id=?", (campaign_id, owner_id))
        updated = connection.execute("SELECT id, title, created_at, updated_at, archived_at, deleted_at FROM campaigns WHERE id=? AND owner_id=?", (campaign_id, owner_id)).fetchone()
        return _campaign_summary(updated)


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
        assert_branch_mutable(connection, branch_id)
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
            data = _validate_character(data, char_id)
        new_id = _new_profile(connection, campaign_id, profile_key, old["kind"], data, old["version"] + 1, old_id)
        snapshot = dict(checkpoint.snapshot)
        snapshot["profile_versions"] = dict(snapshot["profile_versions"])
        snapshot["profile_versions"][profile_key] = new_id
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot)


def rename_campaign(connection: sqlite3.Connection, campaign_id: str, branch_id: str, title: str, *, expected_state_version: int, owner_id: str) -> dict:
    if not title.strip():
        raise ValidationError("Campaign title is required")
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        branch = _branch_row(connection, campaign_id, branch_id, owner_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"], owner_id)
        connection.execute("UPDATE campaigns SET title = ?, updated_at = ? WHERE id = ? AND owner_id = ?", (title.strip(), utc_now(), campaign_id, owner_id))
        saved = _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, dict(checkpoint.snapshot))
        return {"title": title.strip(), "state_version": saved.state_version, "checkpoint_id": saved.id}


def archive_campaign(connection: sqlite3.Connection, campaign_id: str, branch_id: str, *, expected_state_version: int, owner_id: str) -> dict:
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        branch = _branch_row(connection, campaign_id, branch_id, owner_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"], owner_id)
        connection.execute("UPDATE campaigns SET archived_at = COALESCE(archived_at, ?), updated_at = ? WHERE id = ? AND owner_id = ?", (utc_now(), utc_now(), campaign_id, owner_id))
        saved = _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, dict(checkpoint.snapshot))
        return {"archived": True, "state_version": saved.state_version, "checkpoint_id": saved.id}


def add_character(connection: sqlite3.Connection, campaign_id: str, branch_id: str, character: dict, *, expected_state_version: int, owner_id: str):
    character = _validate_character(character)
    character_id = character["id"]
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        branch = _branch_row(connection, campaign_id, branch_id, owner_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"], owner_id)
        key = f"character:{character_id}"
        if key in checkpoint.snapshot["profile_versions"]:
            raise StateConflict("Character is already active in this campaign")
        latest = connection.execute("SELECT id, version FROM profile_versions WHERE campaign_id = ? AND profile_key = ? ORDER BY version DESC LIMIT 1", (campaign_id, key)).fetchone()
        version_id = _new_profile(connection, campaign_id, key, "character", character, (latest["version"] + 1) if latest else 1, latest["id"] if latest else None)
        snapshot = dict(checkpoint.snapshot)
        snapshot["profile_versions"] = dict(snapshot["profile_versions"])
        snapshot["profile_versions"][key] = version_id
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot)


def remove_profile(connection: sqlite3.Connection, campaign_id: str, branch_id: str, profile_key: str, *, expected_state_version: int, owner_id: str):
    if profile_key in {"world", "persona", "style"}:
        raise ValidationError(f"The required {profile_key} profile cannot be removed")
    if not profile_key.startswith("character:"):
        raise ValidationError("Only optional character profiles can be removed")
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        branch = _branch_row(connection, campaign_id, branch_id, owner_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"], owner_id)
        if profile_key not in checkpoint.snapshot["profile_versions"]:
            raise NotFound("Character profile is not active")
        character_id = require_uuid(profile_key.partition(":")[2], "character id")
        scene_row = connection.execute("SELECT data_json FROM scene_versions WHERE id = ? AND campaign_id = ?", (checkpoint.snapshot.get("scene_version_id"), campaign_id)).fetchone()
        if scene_row and any(character_id in scene.get("present_ids", []) for scene in json.loads(scene_row["data_json"]).get("scenes", {}).values()):
            raise StateConflict("Character is referenced by the current scene; remove those references first")
        memory_ids = [*checkpoint.snapshot.get("memory_versions", {}).values(), *checkpoint.snapshot.get("pending_memory_versions", {}).values()]
        for memory_version_id in memory_ids:
            memory = connection.execute("SELECT entity_ids_json, known_by_json, subject_id, object_id, status FROM memory_versions WHERE id = ? AND campaign_id = ?", (memory_version_id, campaign_id)).fetchone()
            if memory and memory["status"] != "deleted" and (character_id in json.loads(memory["entity_ids_json"]) or character_id in json.loads(memory["known_by_json"]) or character_id in {memory["subject_id"], memory["object_id"]}):
                raise StateConflict("Character is referenced by effective memory; remove those references first")
        snapshot = dict(checkpoint.snapshot)
        snapshot["profile_versions"] = dict(snapshot["profile_versions"])
        del snapshot["profile_versions"][profile_key]
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot)
