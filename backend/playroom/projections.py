from __future__ import annotations

import json
import sqlite3

from .domain import NotFound, require_uuid
from .timeline import load_state_checkpoint


_JOB_STATUSES = ("queued", "running", "cancelling", "interrupted", "candidate", "committed", "failed", "cancelled")
_RECOVERABLE_JOB_STATUSES = ("queued", "running", "cancelling", "interrupted", "candidate")
_JOB_FIELDS = {
    "id",
    "campaign_id",
    "branch_id",
    "checkpoint_id",
    "status",
    "mode",
    "action",
    "created_at",
    "cancel_requested",
}


def _owned_campaign(connection: sqlite3.Connection, owner_id: str, campaign_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, title, created_at, updated_at, archived_at FROM campaigns WHERE id=? AND owner_id=?",
        (require_uuid(campaign_id, "campaign_id"), require_uuid(owner_id, "owner_id")),
    ).fetchone()
    if row is None:
        raise NotFound("Campaign not found")
    return row


def _owned_branch(connection: sqlite3.Connection, owner_id: str, campaign_id: str, branch_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT b.id,b.name,b.state_version,b.head_checkpoint_id FROM branches b JOIN campaigns c ON c.id=b.campaign_id WHERE b.id=? AND b.campaign_id=? AND c.owner_id=?",
        (branch_id, campaign_id, owner_id),
    ).fetchone()
    if row is None:
        raise NotFound("Campaign branch not found")
    return row


def _profile_projection(connection: sqlite3.Connection, campaign_id: str, snapshot: dict) -> dict:
    result: dict[str, dict] = {}
    for profile_key, version_id in snapshot.get("profile_versions", {}).items():
        row = connection.execute(
            "SELECT profile_key, kind, version, data_json FROM profile_versions WHERE id=? AND campaign_id=?",
            (version_id, campaign_id),
        ).fetchone()
        if row is None or row["profile_key"] != profile_key:
            raise NotFound("Checkpoint profile is not part of this campaign")
        result[profile_key] = {
            "profile_key": row["profile_key"],
            "kind": row["kind"],
            "version": row["version"],
            "data": json.loads(row["data_json"]),
        }
    return result


def _transcript_projection(connection: sqlite3.Connection, campaign_id: str, selected_ids: list[str]) -> list[dict]:
    if not isinstance(selected_ids, list):
        raise NotFound("Checkpoint transcript is malformed")
    by_id = {}
    for offset in range(0, len(selected_ids), 500):
        chunk = selected_ids[offset:offset + 500]
        rows = connection.execute(
            "SELECT tr.id, tr.turn_id, tr.revision, tr.narrative_text, tr.output_segments_json, tr.complete, tr.selected, t.branch_id, t.sequence, t.action_text, t.input_segments_json "
            "FROM turn_revisions tr JOIN turns t ON t.id=tr.turn_id WHERE tr.id IN ({}) AND t.campaign_id=?".format(",".join("?" for _ in chunk) or "NULL"),
            [*chunk, campaign_id],
        ).fetchall()
        by_id.update({row["id"]: row for row in rows})
    if len(by_id) != len(set(selected_ids)):
        raise NotFound("Checkpoint transcript revision is not part of this campaign")
    return [
        {
            "revision_id": row["id"],
            "turn_id": row["turn_id"],
            "sequence": row["sequence"],
            "action_text": row["action_text"],
            "revision": row["revision"],
            "narrative_text": row["narrative_text"],
            "complete": bool(row["complete"]),
            "selected": bool(row["selected"]),
            "input_segments": json.loads(row["input_segments_json"]) if row["input_segments_json"] else None,
            "output_segments": json.loads(row["output_segments_json"]) if row["output_segments_json"] else None,
        }
        for revision_id in selected_ids
        for row in [by_id[revision_id]]
    ]


def list_owned_generation_jobs(connection: sqlite3.Connection, owner_id: str, campaign_id: str, branch_id: str, *, limit: int = 20) -> list[dict]:
    _owned_campaign(connection, owner_id, campaign_id)
    _owned_branch(connection, owner_id, campaign_id, branch_id)
    bounded_limit = max(1, min(int(limit), 20))
    placeholders = ",".join("?" for _ in _JOB_STATUSES)
    rows = connection.execute(
        f"SELECT id,campaign_id,branch_id,checkpoint_id,status,mode,action,created_at,cancel_requested "
        f"FROM generation_jobs WHERE owner_id=? AND campaign_id=? AND branch_id=? AND operation='generation' AND status IN ({placeholders}) "
        f"ORDER BY CASE WHEN status IN ({','.join('?' for _ in _RECOVERABLE_JOB_STATUSES)}) THEN 0 ELSE 1 END, created_at DESC, id DESC LIMIT ?",
        [owner_id, campaign_id, branch_id, *_JOB_STATUSES, *_RECOVERABLE_JOB_STATUSES, bounded_limit],
    ).fetchall()
    return [{key: (bool(row[key]) if key == "cancel_requested" else row[key]) for key in _JOB_FIELDS} for row in rows]


def get_campaign_projection(connection: sqlite3.Connection, owner_id: str, campaign_id: str, branch_id: str) -> dict:
    campaign = _owned_campaign(connection, owner_id, campaign_id)
    branch = _owned_branch(connection, owner_id, campaign_id, branch_id)
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, branch["head_checkpoint_id"], owner_id)
    snapshot = checkpoint.snapshot
    scene = None
    scene_id = snapshot.get("scene_version_id")
    if scene_id is not None:
        scene_row = connection.execute("SELECT id,version,data_json FROM scene_versions WHERE id=? AND campaign_id=? AND branch_id IN (SELECT id FROM branches WHERE campaign_id=?)", (scene_id, campaign_id, campaign_id)).fetchone()
        if scene_row is not None:
            scene = {"id": scene_row["id"], "version": scene_row["version"], "data": json.loads(scene_row["data_json"])}
    return {
        "campaign": dict(campaign),
        "branch": {"id": branch["id"], "name": branch["name"], "state_version": branch["state_version"], "checkpoint_id": branch["head_checkpoint_id"]},
        "checkpoint": {"id": checkpoint.id, "state_version": checkpoint.state_version, "parent_checkpoint_id": checkpoint.parent_checkpoint_id, "selected_revision_ids": list(snapshot.get("selected_revision_ids", [])), "retrieval_policy": snapshot.get("retrieval_policy", "auto")},
        "profiles": _profile_projection(connection, campaign_id, snapshot),
        "scene": scene,
        "transcript": _transcript_projection(connection, campaign_id, snapshot.get("selected_revision_ids", [])),
        "jobs": list_owned_generation_jobs(connection, owner_id, campaign_id, branch_id),
    }
