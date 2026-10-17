from __future__ import annotations

import json
from typing import Any
import sqlite3
from uuid import uuid4

from .db import assert_branch_mutable, transaction
from .domain import MemoryVersion, NotFound, StateConflict, ValidationError, require_uuid
from .timeline import _advance_checkpoint, _branch_row, load_state_checkpoint, utc_now, validate_source_revisions

RETRIEVAL_POLICIES = {"auto", "important_only", "disabled"}
_UNSET = object()


def _json_list(values, field: str, *, uuid_values: bool = False) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValidationError(f"{field} must be a list")
    result = [require_uuid(value, field) if uuid_values else str(value) for value in values]
    if len(set(result)) != len(result):
        raise ValidationError(f"{field} values must be unique")
    return result


def _to_memory(row: sqlite3.Row, state_version: int, checkpoint_id: str) -> MemoryVersion:
    return MemoryVersion(
        row["memory_id"], row["id"], row["version"], row["kind"], row["text"], tuple(json.loads(row["entity_ids_json"])), row["origin"], row["status"], bool(row["pinned"]), bool(row["mandatory"]), row["knowledge_scope"], tuple(json.loads(row["known_by_json"])), tuple(json.loads(row["source_revision_ids_json"])), row["subject_id"], row["predicate"], row["value"], row["object_id"], row["supersedes_memory_id"], row["effective_state_version"], row["effective_checkpoint_id"], state_version, checkpoint_id,
    )


def _effective_characters(connection: sqlite3.Connection, campaign_id: str, snapshot: dict) -> set[str]:
    """Known-by and presence may reference the player persona, not only NPCs.

    This does not register the player as an NPC or authorize narrator agency.
    """
    ids = {key.partition(":")[2] for key in snapshot["profile_versions"] if key.startswith("character:")}
    persona_version = snapshot["profile_versions"].get("persona")
    if persona_version:
        row = connection.execute(
            "SELECT data_json FROM profile_versions WHERE id=? AND campaign_id=? AND profile_key='persona'",
            (persona_version, campaign_id),
        ).fetchone()
        if row:
            player_id = json.loads(row["data_json"]).get("id")
            if isinstance(player_id, str):
                try:
                    ids.add(require_uuid(player_id, "persona id"))
                except ValidationError:
                    pass  # Legacy/imported personas without IDs remain allowed.
    return ids


def _append_memory_in_transaction(
    connection: sqlite3.Connection,
    campaign_id: str,
    branch_id: str,
    kind: str,
    text: str,
    *,
    origin: str,
    expected_state_version: int,
    source_revision_ids: list[str],
    memory_id: str | None = None,
    entity_ids: list[str] | None = None,
    status: str | None = None,
    pinned: bool = False,
    mandatory: bool = False,
    knowledge_scope: str | None = None,
    known_by: list[str] | None = None,
    subject_id: str | None = None,
    predicate: str | None = None,
    value: str | None = None,
    object_id: str | None = None,
    supersedes_id: str | None = None,
    allow_ai_approval: bool = False,
    clear_fields: set[str] | None = None,
) -> MemoryVersion:
    if origin not in {"user", "import", "ai"}:
        raise ValidationError("Memory origin must be user, import or ai")
    if not kind.strip() or not text.strip():
        raise ValidationError("Memory kind and text are required")
    if knowledge_scope not in {None, "public", "known_by", "narrator_only"}:
        raise ValidationError("Unknown knowledge scope")
    memory_id = require_uuid(memory_id, "memory_id") if memory_id else str(uuid4())
    entity_ids = _json_list(entity_ids, "entity_ids", uuid_values=True) if entity_ids is not None else None
    known_by = _json_list(known_by, "known_by", uuid_values=True) if known_by is not None else None
    source_revision_ids = _json_list(source_revision_ids, "source_revision_ids", uuid_values=True)
    if subject_id:
        subject_id = require_uuid(subject_id, "subject_id")
    if object_id:
        object_id = require_uuid(object_id, "object_id")
    if supersedes_id:
        supersedes_id = require_uuid(supersedes_id, "supersedes_id")
    if supersedes_id == memory_id:
        raise StateConflict("A memory cannot supersede itself")
    branch = _branch_row(connection, campaign_id, branch_id)
    if branch["state_version"] != expected_state_version:
        raise StateConflict("Campaign state changed; reload before saving")
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"])
    valid_entities = _effective_characters(connection, campaign_id, checkpoint.snapshot)
    if any(entity_id not in valid_entities for entity_id in [*(entity_ids or []), *(known_by or []), *([subject_id] if subject_id else []), *([object_id] if object_id else [])]):
        raise ValidationError("Memory entity IDs must identify characters in this campaign checkpoint")
    validate_source_revisions(connection, campaign_id, branch_id, source_revision_ids)

    item = connection.execute("SELECT campaign_id FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
    if item is not None and item["campaign_id"] != campaign_id:
        raise ValidationError("Memory ID belongs to another campaign")
    prior_version = connection.execute("SELECT COALESCE(MAX(version), 0) FROM memory_versions WHERE memory_id = ?", (memory_id,)).fetchone()[0]
    prior_row = None
    if prior_version:
        prior_id = checkpoint.snapshot["memory_versions"].get(memory_id) or checkpoint.snapshot.get("pending_memory_versions", {}).get(memory_id)
        if prior_id is None:
            raise StateConflict("Memory does not exist at the current state position")
        prior_row = connection.execute("SELECT * FROM memory_versions WHERE id = ? AND memory_id = ?", (prior_id, memory_id)).fetchone()
        if prior_row is None:
            raise NotFound("Memory version not found")
        if kind != prior_row["kind"]:
            raise ValidationError("A memory edit cannot change its kind")
        if status is None and origin == prior_row["origin"]:
            status = prior_row["status"]
        if pinned is False and prior_row["pinned"] and origin == prior_row["origin"]:
            # Explicit unpinning is represented by passing pinned=False; no implicit carry-forward.
            pass
        if origin == prior_row["origin"] and knowledge_scope is None:
            knowledge_scope = prior_row["knowledge_scope"]
        if known_by is None:
            known_by = json.loads(prior_row["known_by_json"])
        if entity_ids is None:
            entity_ids = json.loads(prior_row["entity_ids_json"])
        if subject_id is None and "subject_id" not in (clear_fields or set()):
            subject_id = prior_row["subject_id"]
        if predicate is None and "predicate" not in (clear_fields or set()):
            predicate = prior_row["predicate"]
        if value is None and "value" not in (clear_fields or set()):
            value = prior_row["value"]
        if object_id is None and "object_id" not in (clear_fields or set()):
            object_id = prior_row["object_id"]
    if knowledge_scope is None:
        knowledge_scope = "public"
    entity_ids = entity_ids or []
    known_by = known_by or []
    if knowledge_scope == "known_by" and not known_by:
        raise ValidationError("known_by scope requires at least one character ID")
    if status is None:
        status = "approved" if origin == "user" else "pending"
    if status not in {"pending", "approved", "rejected", "deleted"}:
        raise ValidationError("Unknown memory approval state")
    if origin == "ai" and status == "approved" and not allow_ai_approval:
        raise ValidationError("AI-created memory must be reviewed before approval")
    if origin != "user" and status == "approved" and not allow_ai_approval:
        raise ValidationError("Only a player action may approve a memory")
    if status == "deleted" and origin == "ai":
        raise ValidationError("AI cannot delete memory")
    if status == "deleted" and prior_row is None:
        raise NotFound("Cannot tombstone a memory that does not exist")

    active_slot = None
    if subject_id and predicate:
        for current_version_id in checkpoint.snapshot["memory_versions"].values():
            current = connection.execute("SELECT * FROM memory_versions WHERE id = ?", (current_version_id,)).fetchone()
            if current and current["status"] == "approved" and current["subject_id"] == subject_id and current["predicate"] == predicate:
                active_slot = current
                break
    reapplying_supersession = not (prior_row is not None and prior_row["status"] == "approved" and prior_row["supersedes_memory_id"] == supersedes_id)
    if active_slot and active_slot["memory_id"] != memory_id and active_slot["value"] != value:
        if supersedes_id != active_slot["memory_id"]:
            raise StateConflict("Conflicting value for single-valued memory slot; specify supersedes_id for review")
        if active_slot["memory_id"] not in checkpoint.snapshot["memory_versions"]:
            raise StateConflict("Superseded memory is not effective at this checkpoint")
    elif supersedes_id and reapplying_supersession and (active_slot is None or active_slot["memory_id"] != supersedes_id):
        raise StateConflict("supersedes_id must identify the currently effective value for this slot")

    version = prior_version + 1
    version_id = str(uuid4())
    if item is None:
        connection.execute("INSERT INTO memory_items(id, campaign_id, created_at) VALUES (?, ?, ?)", (memory_id, campaign_id, utc_now()))
    next_checkpoint_id = str(uuid4())
    connection.execute(
        "INSERT INTO memory_versions(id, memory_id, campaign_id, branch_id, version, kind, text, entity_ids_json, origin, status, pinned, mandatory, knowledge_scope, known_by_json, source_revision_ids_json, subject_id, predicate, value, object_id, supersedes_memory_id, effective_state_version, effective_checkpoint_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (version_id, memory_id, campaign_id, branch_id, version, kind, text, json.dumps(entity_ids), origin, status, int(pinned), int(mandatory), knowledge_scope, json.dumps(known_by), json.dumps(source_revision_ids), subject_id, predicate, value, object_id, supersedes_id, expected_state_version + 1, next_checkpoint_id, utc_now()),
    )
    snapshot = dict(checkpoint.snapshot)
    snapshot["memory_versions"] = dict(snapshot["memory_versions"])
    snapshot["pending_memory_versions"] = dict(snapshot.get("pending_memory_versions", {}))
    snapshot["reviewed_memory_versions"] = dict(snapshot.get("reviewed_memory_versions", {}))
    if status == "approved":
        if supersedes_id:
            snapshot["memory_versions"].pop(supersedes_id, None)
        snapshot["memory_versions"][memory_id] = version_id
        snapshot["pending_memory_versions"].pop(memory_id, None)
        snapshot["reviewed_memory_versions"].pop(memory_id, None)
    elif status == "pending":
        snapshot["pending_memory_versions"][memory_id] = version_id
    elif status == "rejected":
        snapshot["pending_memory_versions"].pop(memory_id, None)
        snapshot["reviewed_memory_versions"][memory_id] = version_id
    else:
        snapshot["memory_versions"][memory_id] = version_id
        snapshot["pending_memory_versions"].pop(memory_id, None)
    new_checkpoint = _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot, checkpoint_id=next_checkpoint_id)
    row = connection.execute("SELECT * FROM memory_versions WHERE id = ?", (version_id,)).fetchone()
    return _to_memory(row, new_checkpoint.state_version, new_checkpoint.id)


def append_memory_version(connection: sqlite3.Connection, campaign_id: str, branch_id: str, kind: str, text: str, *, origin: str, expected_state_version: int, source_revision_ids: list[str], memory_id: str | None = None, entity_ids: list[str] | None = None, status: str | None = None, pinned: bool = False, mandatory: bool = False, knowledge_scope: str | None = None, known_by: list[str] | None = None, subject_id: str | None = None, predicate: str | None = None, value: str | None = None, object_id: str | None = None, supersedes_id: str | None = None) -> MemoryVersion:
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        return _append_memory_in_transaction(connection, campaign_id, branch_id, kind, text, origin=origin, expected_state_version=expected_state_version, source_revision_ids=source_revision_ids, memory_id=memory_id, entity_ids=entity_ids, status=status, pinned=pinned, mandatory=mandatory, knowledge_scope=knowledge_scope, known_by=known_by, subject_id=subject_id, predicate=predicate, value=value, object_id=object_id, supersedes_id=supersedes_id)


def list_effective_memory(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, *, owner_id: str | None = None) -> list[MemoryVersion]:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position, owner_id)
    policy = checkpoint.snapshot["retrieval_policy"]
    rows = []
    for version_id in checkpoint.snapshot["memory_versions"].values():
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is None or row["status"] != "approved":
            continue
        optional_event = row["kind"] in {"event", "promise", "relationship", "lore", "summary"}
        if policy == "important_only" and optional_event and not row["pinned"]:
            continue
        if policy == "disabled" and optional_event and not (row["pinned"] or row["mandatory"]):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (not bool(row["pinned"]), row["created_at"], row["memory_id"]))
    return [_to_memory(row, checkpoint.state_version, checkpoint.id) for row in rows]


def list_memory_library(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, *, owner_id: str | None = None) -> list[MemoryVersion]:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position, owner_id)
    result = []
    for version_id in checkpoint.snapshot["memory_versions"].values():
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is not None and row["status"] == "approved":
            result.append(_to_memory(row, checkpoint.state_version, checkpoint.id))
    return result


def list_memory_history(connection: sqlite3.Connection, campaign_id: str, branch_id: str, memory_id: str, position: str | None, *, owner_id: str | None = None) -> list[MemoryVersion]:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position, owner_id)
    memory_id = require_uuid(memory_id, "memory_id")
    if memory_id not in set(checkpoint.snapshot["memory_versions"]) | set(checkpoint.snapshot.get("pending_memory_versions", {})) | set(checkpoint.snapshot.get("reviewed_memory_versions", {})):
        raise NotFound("Memory not found at this checkpoint")
    rows = connection.execute("SELECT * FROM memory_versions WHERE memory_id = ? AND campaign_id = ? AND branch_id = ? AND effective_state_version <= ? ORDER BY version", (memory_id, campaign_id, branch_id, checkpoint.state_version)).fetchall()
    return [_to_memory(row, checkpoint.state_version, checkpoint.id) for row in rows]


def list_memory_proposals(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, *, owner_id: str | None = None) -> list[MemoryVersion]:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position, owner_id)
    proposals = []
    for version_id in checkpoint.snapshot.get("pending_memory_versions", {}).values():
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is not None:
            proposals.append(_to_memory(row, checkpoint.state_version, checkpoint.id))
    return proposals


def approve_memory(connection: sqlite3.Connection, campaign_id: str, branch_id: str, memory_id: str, *, expected_state_version: int) -> MemoryVersion:
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        head = load_state_checkpoint(connection, campaign_id, branch_id, None)
        version_id = head.snapshot.get("pending_memory_versions", {}).get(require_uuid(memory_id, "memory_id"))
        if not version_id:
            raise NotFound("Memory not found")
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ?", (version_id,)).fetchone()
        if row["status"] != "pending":
            raise StateConflict("Only pending memory can be approved")
        return _append_memory_in_transaction(connection, campaign_id, branch_id, row["kind"], row["text"], origin=row["origin"], expected_state_version=expected_state_version, source_revision_ids=json.loads(row["source_revision_ids_json"]), memory_id=row["memory_id"], entity_ids=json.loads(row["entity_ids_json"]), status="approved", pinned=bool(row["pinned"]), mandatory=bool(row["mandatory"]), knowledge_scope=row["knowledge_scope"], known_by=json.loads(row["known_by_json"]), subject_id=row["subject_id"], predicate=row["predicate"], value=row["value"], object_id=row["object_id"], supersedes_id=row["supersedes_memory_id"], allow_ai_approval=True)


def reject_memory(connection: sqlite3.Connection, campaign_id: str, branch_id: str, memory_id: str, *, expected_state_version: int) -> MemoryVersion:
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        head = load_state_checkpoint(connection, campaign_id, branch_id, None)
        version_id = head.snapshot.get("pending_memory_versions", {}).get(require_uuid(memory_id, "memory_id"))
        if not version_id:
            raise NotFound("Memory not found")
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ?", (version_id,)).fetchone()
        if row["status"] != "pending":
            raise StateConflict("Only pending memory can be rejected")
        return _append_memory_in_transaction(connection, campaign_id, branch_id, row["kind"], row["text"], origin=row["origin"], expected_state_version=expected_state_version, source_revision_ids=json.loads(row["source_revision_ids_json"]), memory_id=row["memory_id"], entity_ids=json.loads(row["entity_ids_json"]), status="rejected", pinned=bool(row["pinned"]), mandatory=bool(row["mandatory"]), knowledge_scope=row["knowledge_scope"], known_by=json.loads(row["known_by_json"]), subject_id=row["subject_id"], predicate=row["predicate"], value=row["value"], object_id=row["object_id"], supersedes_id=row["supersedes_memory_id"], allow_ai_approval=True)


def delete_memory(connection: sqlite3.Connection, campaign_id: str, branch_id: str, memory_id: str, *, expected_state_version: int) -> MemoryVersion:
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        head = load_state_checkpoint(connection, campaign_id, branch_id, None)
        version_id = head.snapshot["memory_versions"].get(require_uuid(memory_id, "memory_id"))
        if not version_id:
            raise NotFound("Memory not found")
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ?", (version_id,)).fetchone()
        return _append_memory_in_transaction(connection, campaign_id, branch_id, row["kind"], row["text"], origin="user", expected_state_version=expected_state_version, source_revision_ids=json.loads(row["source_revision_ids_json"]), memory_id=row["memory_id"], entity_ids=json.loads(row["entity_ids_json"]), status="deleted", pinned=bool(row["pinned"]), mandatory=bool(row["mandatory"]), knowledge_scope=row["knowledge_scope"], known_by=json.loads(row["known_by_json"]), subject_id=row["subject_id"], predicate=row["predicate"], value=row["value"], object_id=row["object_id"])


def update_memory(connection: sqlite3.Connection, campaign_id: str, branch_id: str, memory_id: str, *, expected_state_version: int, text: str | None = None, pinned: bool | None = None, entity_ids: list[str] | None = None, knowledge_scope: str | None = None, known_by: list[str] | None = None, subject_id: str | None | Any = _UNSET, predicate: str | None | Any = _UNSET, value: str | None | Any = _UNSET, object_id: str | None | Any = _UNSET, supersedes_id: str | None | Any = _UNSET) -> MemoryVersion:
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        head = load_state_checkpoint(connection, campaign_id, branch_id, None)
        version_id = head.snapshot["memory_versions"].get(require_uuid(memory_id, "memory_id"))
        if version_id is None:
            raise NotFound("Approved memory not found")
        row = connection.execute("SELECT * FROM memory_versions WHERE id = ?", (version_id,)).fetchone()
        clear_fields = {name for name, value in (("subject_id", subject_id), ("predicate", predicate), ("value", value), ("object_id", object_id), ("supersedes_id", supersedes_id)) if value is None}
        return _append_memory_in_transaction(connection, campaign_id, branch_id, row["kind"], text if text is not None else row["text"], origin="user", expected_state_version=expected_state_version, source_revision_ids=json.loads(row["source_revision_ids_json"]), memory_id=memory_id, entity_ids=entity_ids if entity_ids is not None else json.loads(row["entity_ids_json"]), status="approved", pinned=pinned if pinned is not None else bool(row["pinned"]), mandatory=bool(row["mandatory"]), knowledge_scope=knowledge_scope if knowledge_scope is not None else row["knowledge_scope"], known_by=known_by if known_by is not None else json.loads(row["known_by_json"]), subject_id=row["subject_id"] if subject_id is _UNSET else subject_id, predicate=row["predicate"] if predicate is _UNSET else predicate, value=row["value"] if value is _UNSET else value, object_id=row["object_id"] if object_id is _UNSET else object_id, supersedes_id=row["supersedes_memory_id"] if supersedes_id is _UNSET else supersedes_id, clear_fields=clear_fields)


def set_retrieval_policy(connection: sqlite3.Connection, campaign_id: str, branch_id: str, policy: str, *, expected_state_version: int):
    if policy not in RETRIEVAL_POLICIES:
        raise ValidationError("Retrieval policy must be auto, important_only or disabled")
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        branch = _branch_row(connection, campaign_id, branch_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"])
        snapshot = dict(checkpoint.snapshot)
        snapshot["retrieval_policy"] = policy
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot)


def update_scene(connection: sqlite3.Connection, campaign_id: str, branch_id: str, scene_state: dict, *, expected_state_version: int):
    if not isinstance(scene_state, dict) or not isinstance(scene_state.get("scenes"), list):
        raise ValidationError("Scene state must contain a list of scenes")
    focus_id = scene_state.get("focus_scene_id")
    scenes = {}
    for scene in scene_state["scenes"]:
        if not isinstance(scene, dict):
            raise ValidationError("Scene entry must be an object")
        scene_id = require_uuid(scene.get("id"), "scene id")
        present_ids = _json_list(scene.get("present_ids", []), "present_ids", uuid_values=True)
        if scene_id in scenes:
            raise ValidationError("Scene IDs must be unique")
        scenes[scene_id] = {**scene, "id": scene_id, "present_ids": present_ids}
    if focus_id is not None:
        focus_id = require_uuid(focus_id, "focus_scene_id")
        if focus_id not in scenes:
            raise ValidationError("Focus scene must exist in this scene state")
    with transaction(connection):
        assert_branch_mutable(connection, branch_id)
        branch = _branch_row(connection, campaign_id, branch_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before saving")
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"])
        valid_characters = _effective_characters(connection, campaign_id, checkpoint.snapshot)
        if any(character_id not in valid_characters for scene in scenes.values() for character_id in scene["present_ids"]):
            raise ValidationError("Scene presence must reference a character in this campaign")
        old = connection.execute("SELECT COALESCE(MAX(version), 0) FROM scene_versions WHERE branch_id = ?", (branch_id,)).fetchone()[0]
        scene_version_id = str(uuid4())
        saved = {"focus_scene_id": focus_id, "scenes": scenes}
        checkpoint_id = str(uuid4())
        connection.execute("INSERT INTO scene_versions(id, campaign_id, branch_id, version, data_json, effective_state_version, effective_checkpoint_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (scene_version_id, campaign_id, branch_id, old + 1, json.dumps(saved, ensure_ascii=False, sort_keys=True), expected_state_version + 1, checkpoint_id, utc_now()))
        snapshot = dict(checkpoint.snapshot)
        snapshot["scene_version_id"] = scene_version_id
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot, checkpoint_id=checkpoint_id)


def get_effective_scene(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, *, owner_id: str | None = None) -> dict:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position, owner_id)
    row = connection.execute("SELECT data_json, effective_state_version, effective_checkpoint_id FROM scene_versions WHERE id = ? AND campaign_id = ?", (checkpoint.snapshot["scene_version_id"], campaign_id)).fetchone()
    if row is None:
        raise NotFound("Scene version does not belong to this checkpoint")
    return {**json.loads(row["data_json"]), "effective_cursor": {"state_version": row["effective_state_version"], "checkpoint_id": row["effective_checkpoint_id"]}, "read_cursor": {"state_version": checkpoint.state_version, "checkpoint_id": checkpoint.id}}
