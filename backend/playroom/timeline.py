from __future__ import annotations

import json
import sqlite3
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from .db import transaction
from .domain import BranchHead, NotFound, StateCheckpoint, StateConflict, ValidationError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _branch_row(connection: sqlite3.Connection, campaign_id: str, branch_id: str, owner_id: str | None = None) -> sqlite3.Row:
    sql = "SELECT b.* FROM branches b JOIN campaigns c ON c.id = b.campaign_id WHERE b.campaign_id = ? AND b.id = ?"
    args: list[str] = [campaign_id, branch_id]
    if owner_id is not None:
        sql += " AND c.owner_id = ?"
        args.append(owner_id)
    row = connection.execute(sql, args).fetchone()
    if row is None:
        raise NotFound("Campaign branch not found")
    return row


def get_branch_head(connection: sqlite3.Connection, campaign_id: str, branch_id: str, owner_id: str | None = None) -> BranchHead:
    row = _branch_row(connection, campaign_id, branch_id, owner_id)
    if not row["head_checkpoint_id"]:
        raise NotFound("Campaign branch has no state checkpoint")
    return BranchHead(campaign_id, branch_id, row["state_version"], row["head_checkpoint_id"], row["head_turn_id"], row["head_revision_id"])


def load_state_checkpoint(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, owner_id: str | None = None) -> StateCheckpoint:
    branch = _branch_row(connection, campaign_id, branch_id, owner_id)
    checkpoint_id = position or branch["head_checkpoint_id"]
    row = connection.execute(
        "SELECT * FROM state_checkpoints WHERE id = ? AND campaign_id = ? AND branch_id = ?",
        (checkpoint_id, campaign_id, branch_id),
    ).fetchone()
    if row is None:
        raise NotFound("Checkpoint does not belong to this campaign branch")
    return StateCheckpoint(row["id"], row["campaign_id"], row["branch_id"], row["state_version"], row["parent_checkpoint_id"], json.loads(row["snapshot_json"]))


def _advance_checkpoint(
    connection: sqlite3.Connection,
    campaign_id: str,
    branch_id: str,
    expected_state_version: int,
    snapshot: dict,
    *,
    turn_id: str | None = None,
    revision_id: str | None = None,
    checkpoint_id: str | None = None,
) -> StateCheckpoint:
    branch = _branch_row(connection, campaign_id, branch_id)
    if branch["state_version"] != expected_state_version:
        raise StateConflict("Campaign state changed; reload before saving")
    _validate_snapshot(connection, campaign_id, branch_id, snapshot)
    new_version = expected_state_version + 1
    checkpoint_id = checkpoint_id or str(uuid4())
    connection.execute(
        "INSERT INTO state_checkpoints(id, campaign_id, branch_id, state_version, parent_checkpoint_id, turn_id, revision_id, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (checkpoint_id, campaign_id, branch_id, new_version, branch["head_checkpoint_id"], turn_id, revision_id, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), utc_now()),
    )
    updated = connection.execute(
        "UPDATE branches SET state_version = ?, head_checkpoint_id = ?, head_turn_id = COALESCE(?, head_turn_id), head_revision_id = COALESCE(?, head_revision_id) WHERE id = ? AND campaign_id = ? AND state_version = ?",
        (new_version, checkpoint_id, turn_id, revision_id, branch_id, campaign_id, expected_state_version),
    )
    if updated.rowcount != 1:
        raise StateConflict("Campaign state changed; reload before saving")
    return StateCheckpoint(checkpoint_id, campaign_id, branch_id, new_version, branch["head_checkpoint_id"], snapshot)


def _fork_snapshot(connection: sqlite3.Connection, campaign_id: str, branch_id: str) -> dict | None:
    branch = _branch_row(connection, campaign_id, branch_id)
    if branch["parent_branch_id"] is None:
        if branch["fork_checkpoint_id"] is not None:
            raise ValidationError("Root branch cannot reference a fork checkpoint")
        return None
    row = connection.execute(
        "SELECT sc.snapshot_json FROM state_checkpoints sc JOIN branches parent ON parent.id = sc.branch_id WHERE sc.id = ? AND sc.campaign_id = ? AND parent.id = ? AND parent.campaign_id = ?",
        (branch["fork_checkpoint_id"], campaign_id, branch["parent_branch_id"], campaign_id),
    ).fetchone()
    if row is None:
        raise ValidationError("Branch fork checkpoint must belong to its parent branch")
    return json.loads(row["snapshot_json"])


def _validate_snapshot(connection: sqlite3.Connection, campaign_id: str, branch_id: str, snapshot: dict) -> None:
    if snapshot.get("retrieval_policy") not in {"auto", "important_only", "disabled"}:
        raise ValidationError("Checkpoint has an invalid retrieval policy")
    profile_versions = snapshot.get("profile_versions")
    memory_versions = snapshot.get("memory_versions")
    pending_memory_versions = snapshot.get("pending_memory_versions", {})
    reviewed_memory_versions = snapshot.get("reviewed_memory_versions", {})
    if not isinstance(profile_versions, dict) or not isinstance(memory_versions, dict) or not isinstance(pending_memory_versions, dict) or not isinstance(reviewed_memory_versions, dict):
        raise ValidationError("Checkpoint profile and memory membership must be maps")
    inherited = _fork_snapshot(connection, campaign_id, branch_id) or {}
    inherited_memory_ids = set(inherited.get("memory_versions", {}).values())
    inherited_scene_ids = {inherited.get("scene_version_id")} - {None}
    inherited_revision_ids = set(inherited.get("selected_revision_ids", []))
    for profile_key, version_id in profile_versions.items():
        row = connection.execute("SELECT profile_key FROM profile_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is None or row["profile_key"] != profile_key:
            raise ValidationError("Checkpoint profile reference is outside this campaign")
    for memory_id, version_id in memory_versions.items():
        row = connection.execute("SELECT memory_id, branch_id FROM memory_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is None or row["memory_id"] != memory_id or (row["branch_id"] != branch_id and version_id not in inherited_memory_ids):
            raise ValidationError("Checkpoint memory reference is outside this branch")
    for membership, expected_status in ((pending_memory_versions, "pending"), (reviewed_memory_versions, "rejected")):
        for memory_id, version_id in membership.items():
            row = connection.execute("SELECT memory_id, branch_id, status FROM memory_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
            if row is None or row["memory_id"] != memory_id or row["status"] != expected_status or (row["branch_id"] != branch_id and version_id not in inherited_memory_ids):
                raise ValidationError("Checkpoint proposal reference is outside this branch")
    scene_id = snapshot.get("scene_version_id")
    if scene_id is not None:
        row = connection.execute("SELECT branch_id FROM scene_versions WHERE id = ? AND campaign_id = ?", (scene_id, campaign_id)).fetchone()
        if row is None or (row["branch_id"] != branch_id and scene_id not in inherited_scene_ids):
            raise ValidationError("Checkpoint scene reference is outside this branch")
    selected_ids = snapshot.get("selected_revision_ids", [])
    if not isinstance(selected_ids, list) or len(set(selected_ids)) != len(selected_ids):
        raise ValidationError("Checkpoint selected revision membership is malformed")
    allowed_selected = set(inherited_revision_ids)
    allowed_selected.update(row[0] for row in connection.execute("SELECT revision_id FROM selected_revisions WHERE branch_id = ?", (branch_id,)))
    if not set(selected_ids).issubset(allowed_selected):
        raise ValidationError("Checkpoint revision membership is outside this branch lineage")
    revision_id = snapshot.get("revision_id")
    if revision_id is not None:
        if revision_id not in selected_ids or connection.execute("SELECT 1 FROM turn_revisions tr JOIN turns t ON t.id = tr.turn_id WHERE tr.id = ? AND t.campaign_id = ?", (revision_id, campaign_id)).fetchone() is None:
            raise ValidationError("Checkpoint revision reference is not selected on this branch")


def create_state_checkpoint(
    connection: sqlite3.Connection,
    campaign_id: str,
    branch_id: str,
    snapshot: dict,
    expected_state_version: int,
) -> StateCheckpoint:
    with transaction(connection):
        head = get_branch_head(connection, campaign_id, branch_id)
        current = load_state_checkpoint(connection, campaign_id, branch_id, head.checkpoint_id)
        for membership_key in ("profile_versions", "memory_versions", "pending_memory_versions", "reviewed_memory_versions", "scene_version_id", "selected_revision_ids"):
            if snapshot.get(membership_key) != current.snapshot.get(membership_key):
                raise ValidationError("Public checkpoint creation cannot change version membership")
        return _advance_checkpoint(connection, campaign_id, branch_id, expected_state_version, snapshot)


def create_committed_revision(connection: sqlite3.Connection, campaign_id: str, branch_id: str, action_text: str, narrative_text: str, *, expected_state_version: int) -> tuple[str, str]:
    if not action_text.strip() or not narrative_text.strip():
        raise ValidationError("A committed turn needs both player action and complete narrative")
    with transaction(connection):
        branch = _branch_row(connection, campaign_id, branch_id)
        if branch["state_version"] != expected_state_version:
            raise StateConflict("Campaign state changed; reload before committing the turn")
        head = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"])
        sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM turns WHERE branch_id = ?", (branch_id,)).fetchone()[0]
        turn_id, revision_id = str(uuid4()), str(uuid4())
        now = utc_now()
        connection.execute("INSERT INTO turns(id, campaign_id, branch_id, sequence, action_text, created_at) VALUES (?, ?, ?, ?, ?, ?)", (turn_id, campaign_id, branch_id, sequence, action_text, now))
        connection.execute("INSERT INTO turn_revisions(id, turn_id, revision, narrative_text, complete, selected, created_at) VALUES (?, ?, 1, ?, 1, 1, ?)", (revision_id, turn_id, narrative_text, now))
        connection.execute("INSERT INTO selected_revisions(branch_id, turn_id, revision_id) VALUES (?, ?, ?)", (branch_id, turn_id, revision_id))
        snapshot = dict(head.snapshot)
        snapshot["turn_id"] = turn_id
        snapshot["revision_id"] = revision_id
        snapshot["selected_revision_ids"] = list(snapshot.get("selected_revision_ids", [])) + [revision_id]
        _advance_checkpoint(connection, campaign_id, branch_id, head.state_version, snapshot, turn_id=turn_id, revision_id=revision_id)
        return turn_id, revision_id


def validate_source_revisions(connection: sqlite3.Connection, campaign_id: str, branch_id: str, revision_ids: list[str]) -> None:
    if len(set(revision_ids)) != len(revision_ids):
        raise ValidationError("Source revision IDs must be unique")
    head = get_branch_head(connection, campaign_id, branch_id)
    effective_revisions = set(load_state_checkpoint(connection, campaign_id, branch_id, head.checkpoint_id).snapshot.get("selected_revision_ids", []))
    for revision_id in revision_ids:
        if revision_id not in effective_revisions:
            raise ValidationError("Source revision is not a committed revision at this branch checkpoint")
        row = connection.execute("SELECT 1 FROM turn_revisions WHERE id = ? AND complete = 1", (revision_id,)).fetchone()
        if row is None:
            raise ValidationError("Source revision is not complete")


def _normalize_alias(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def resolve_character_alias(connection: sqlite3.Connection, campaign_id: str, branch_id: str, position: str | None, alias: str) -> list[dict]:
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, position)
    target = _normalize_alias(alias)
    matches = []
    for profile_key, version_id in checkpoint.snapshot["profile_versions"].items():
        if not profile_key.startswith("character:"):
            continue
        row = connection.execute("SELECT data_json FROM profile_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is None:
            continue
        data = json.loads(row["data_json"])
        aliases = [data.get("name", ""), *data.get("aliases", [])]
        if target and any(_normalize_alias(item) == target for item in aliases):
            matches.append({"id": profile_key.partition(":")[2], **data})
    return matches
