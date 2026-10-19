"""Import exactly one owner-selected ChatGPT conversation, without model calls.

The source archive remains private and is not merged into approved canon.
Current-node traversal is mandatory: mapping iteration includes alternate AI
regenerations and unrelated tool branches and MUST NOT be used as chronology.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import NAMESPACE_URL, uuid4, uuid5

from .campaigns import create_campaign
from .db import transaction
from .domain import ValidationError
from .timeline import _create_committed_revision_in_transaction
from .timeline import get_branch_head

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_NODES = 12000
MAX_TURNS = 5000
IMPORT_CHUNK_TURNS = 100


def import_review(connection: sqlite3.Connection, owner_id: str, campaign_id: str, current_checkpoint_id: str | None = None) -> dict:
    source = connection.execute(
        "SELECT source_conversation_id, paired_turns, warnings_json, skipped_messages, "
        "import_status, imported_turns FROM chatgpt_import_sources WHERE owner_id=? AND campaign_id=?",
        (owner_id, campaign_id),
    ).fetchone()
    legacy = connection.execute(
        "SELECT canon_count, event_count, excerpt_count, warnings_json, selected_source_json FROM legacy_import_sources WHERE owner_id=? AND campaign_id=?",
        (owner_id, campaign_id),
    ).fetchone()
    source_meta = {}
    if legacy:
        try:
            legacy_warnings = json.loads(legacy["warnings_json"])
        except (TypeError, ValueError):
            legacy_warnings = ["Legacy history is incomplete"]
        source_meta = {
            "source_kind": "legacy_bundle", "source_conversation_id": None, "paired_turns": 0,
            "skipped_messages": None, "warnings": legacy_warnings,
            "legacy_counts": {"canon_facts": legacy["canon_count"], "timeline_events": legacy["event_count"], "player_excerpts": legacy["excerpt_count"]},
        }
        try:
            selected = json.loads(legacy["selected_source_json"] or "{}")
        except (TypeError, ValueError):
            selected = {}
        if isinstance(selected, dict):
            source_meta["source_provenance"] = {
                key: selected.get(key) for key in ("format", "schema_version", "is_app_export", "can_roundtrip_app_export", "title")
                if key in selected
            }
            checkpoint = selected.get("resume_checkpoint")
            focus = checkpoint.get("focus_scene") if isinstance(checkpoint, dict) else None
            if isinstance(checkpoint, dict):
                source_meta["resume_checkpoint"] = {
                    key: checkpoint.get(key) for key in ("chapter_last_completed", "next_chapter_number", "next_chapter_written")
                    if key in checkpoint
                }
                if isinstance(focus, dict):
                    source_meta["resume_checkpoint"]["focus_scene"] = {
                        key: focus.get(key) for key in ("scene_id", "location", "relative_time", "present_character_ids")
                        if key in focus
                    }
            queue = selected.get("gaps_and_review_queue")
            if isinstance(queue, list):
                source_meta["review_queue"] = []
                for item in queue[:500]:
                    if not isinstance(item, dict):
                        continue
                    clean_item = {}
                    for key in ("issue", "policy"):
                        value = item.get(key)
                        if not isinstance(value, str):
                            continue
                        clean_item[key] = value if len(value) <= 2000 else f"{value[:1987]}… [truncated]"
                    source_meta["review_queue"].append(clean_item)
    if source:
        try:
            warnings = json.loads(source["warnings_json"] or "[]")
            if not isinstance(warnings, list):
                warnings = []
        except (TypeError, ValueError):
            warnings = []
        skipped = source["skipped_messages"]
        if skipped is None:
            warnings = [*warnings, "Skipped-message count unavailable for this legacy import"]
        source_meta = {
            "source_conversation_id": source["source_conversation_id"],
            "paired_turns": source["paired_turns"],
            "import_status": source["import_status"],
            "imported_turns": source["imported_turns"],
            "skipped_messages": skipped,
            "skipped_messages_known": skipped is not None,
            "warnings": sorted(set(warnings)),
        }
    row = connection.execute("SELECT source_checkpoint_id, approved_checkpoint_id, review_json, approved_at FROM import_review_checkpoints WHERE owner_id=? AND campaign_id=?", (owner_id, campaign_id)).fetchone()
    if row is None:
        return {"required": source is not None or legacy is not None, "approved": source is None and legacy is None, "approved_checkpoint_id": None, "review": {}, **source_meta}
    approved = row["approved_checkpoint_id"] is not None
    if approved and current_checkpoint_id:
        cursor = current_checkpoint_id
        approved = False
        while cursor:
            if cursor == row["approved_checkpoint_id"]:
                approved = True
                break
            parent = connection.execute("SELECT parent_checkpoint_id FROM state_checkpoints WHERE id=?", (cursor,)).fetchone()
            cursor = parent[0] if parent else None
    return {"required": not approved, "approved": approved, "source_checkpoint_id": row["source_checkpoint_id"], "approved_checkpoint_id": row["approved_checkpoint_id"], "approved_at": row["approved_at"], "review": json.loads(row["review_json"] or "{}"), **source_meta}


def assert_import_review_approved(connection: sqlite3.Connection, owner_id: str, campaign_id: str, checkpoint_id: str) -> None:
    row = connection.execute("SELECT approved_checkpoint_id, review_json FROM import_review_checkpoints WHERE owner_id=? AND campaign_id=?", (owner_id, campaign_id)).fetchone()
    source = connection.execute("SELECT 1 FROM chatgpt_import_sources WHERE owner_id=? AND campaign_id=?", (owner_id, campaign_id)).fetchone()
    legacy = connection.execute(
        "SELECT 1 FROM legacy_import_sources WHERE owner_id=? AND campaign_id=?",
        (owner_id, campaign_id),
    ).fetchone()
    if source is None and legacy is None:
        return
    if row is None or row["approved_checkpoint_id"] is None:
        from .domain import StateConflict
        raise StateConflict("Imported campaign requires owner review approval for this checkpoint")
    if legacy and json.loads(row["review_json"] or "{}").get("provider_data") is not True:
        from .domain import StateConflict
        raise StateConflict("Legacy provider-data consent is required before Send")
    cursor = checkpoint_id
    while cursor:
        if cursor == row["approved_checkpoint_id"]:
            return
        parent = connection.execute("SELECT parent_checkpoint_id FROM state_checkpoints WHERE id=?", (cursor,)).fetchone()
        cursor = parent[0] if parent else None
    from .domain import StateConflict
    raise StateConflict("Imported campaign requires owner review approval for this checkpoint")


def approve_import_review(connection: sqlite3.Connection, owner_id: str, campaign_id: str, branch_id: str, expected_checkpoint_id: str, review: dict) -> dict:
    from .domain import NotFound, StateConflict
    required = {"persona", "npc_voice_presence", "canon_known_by_narrator_only", "missing_history"}
    if not isinstance(review, dict) or not required.issubset(review) or any(review[key] is not True for key in required):
        raise ValidationError("Import review must cover persona, NPC presence, canon visibility and missing history")
    head = get_branch_head(connection, campaign_id, branch_id, owner_id)
    if head.checkpoint_id != expected_checkpoint_id:
        raise StateConflict("Import review checkpoint is stale")
    with transaction(connection):
        row = connection.execute("SELECT 1 FROM import_review_checkpoints WHERE owner_id=? AND campaign_id=?", (owner_id, campaign_id)).fetchone()
        if row is None:
            raise NotFound("Import review checkpoint not found")
        locked = get_branch_head(connection, campaign_id, branch_id, owner_id)
        if locked.checkpoint_id != expected_checkpoint_id:
            raise StateConflict("Import review checkpoint is stale")
        approved_checkpoint = expected_checkpoint_id
        legacy = connection.execute(
            "SELECT 1 FROM legacy_import_sources WHERE owner_id=? AND campaign_id=?",
            (owner_id, campaign_id),
        ).fetchone()
        if legacy:
            if review.get("provider_data") is not True:
                raise ValidationError("Legacy provider-data consent must be explicit before unlocking Send")
            # No imported summary/fact becomes approved until these exact source
            # proposals were displayed and the owner approved the checkpoint.
            from .memory import _append_memory_in_transaction
            from .timeline import load_state_checkpoint
            snapshot = load_state_checkpoint(connection, campaign_id, branch_id, None).snapshot
            for memory_id, version_id in list(snapshot.get("pending_memory_versions", {}).items()):
                proposal = connection.execute(
                    "SELECT * FROM memory_versions WHERE id=? AND memory_id=? AND campaign_id=? AND branch_id=?",
                    (version_id, memory_id, campaign_id, branch_id),
                ).fetchone()
                if proposal is None or proposal["origin"] != "import" or proposal["status"] != "pending":
                    continue
                head = get_branch_head(connection, campaign_id, branch_id, owner_id)
                _append_memory_in_transaction(
                    connection, campaign_id, branch_id, proposal["kind"], proposal["text"],
                    origin="import", status="approved", allow_ai_approval=True,
                    expected_state_version=head.state_version, source_revision_ids=[],
                    memory_id=memory_id, entity_ids=json.loads(proposal["entity_ids_json"]),
                    knowledge_scope=proposal["knowledge_scope"], known_by=json.loads(proposal["known_by_json"]),
                    pinned=bool(proposal["pinned"]), mandatory=bool(proposal["mandatory"]),
                )
            approved_checkpoint = get_branch_head(connection, campaign_id, branch_id, owner_id).checkpoint_id
        connection.execute("UPDATE import_review_checkpoints SET approved_checkpoint_id=?, review_json=?, approved_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE owner_id=? AND campaign_id=?", (approved_checkpoint, json.dumps(review, ensure_ascii=False, sort_keys=True), owner_id, campaign_id))
    return import_review(connection, owner_id, campaign_id)


def _serialized_source(source: dict) -> str:
    try:
        serialized = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValidationError("ChatGPT conversation JSON is invalid") from exc
    if len(serialized.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValidationError("Selected conversation exceeds the 20 MiB import limit")
    return serialized


def preview_conversation(source: dict) -> dict:
    if not isinstance(source, dict):
        raise ValidationError("A ChatGPT conversation must be an object")
    mapping = source.get("mapping")
    current = source.get("current_node")
    if not isinstance(mapping, dict) or not 0 < len(mapping) <= MAX_NODES or not isinstance(current, str) or not current:
        raise ValidationError("ChatGPT mapping and current_node are required")
    title = source.get("title")
    source_id = source.get("id") or source.get("conversation_id")
    if not isinstance(source_id, str) or not source_id or len(source_id) > 256:
        raise ValidationError("ChatGPT conversation id is missing")
    if not isinstance(title, str) or len(title) > 160:
        raise ValidationError("ChatGPT conversation title is invalid")
    _serialized_source(source)

    path: list[dict] = []
    seen: set[str] = set()
    while current is not None:
        if not isinstance(current, str) or not current:
            raise ValidationError("ChatGPT node parent is invalid")
        if current in seen:
            raise ValidationError("ChatGPT mapping has a cycle")
        seen.add(current)
        node = mapping.get(current)
        if not isinstance(node, dict):
            raise ValidationError("ChatGPT mapping references a missing parent node")
        path.append(node)
        current = node.get("parent")
    path.reverse()

    messages, skipped, reasons = [], 0, []
    for node in path:
        message = node.get("message")
        if message is None:
            continue
        if not isinstance(message, dict):
            raise ValidationError("ChatGPT message shape is invalid")
        role = (message.get("author") or {}).get("role") if isinstance(message.get("author"), dict) else None
        recipient = message.get("recipient") or "all"
        metadata = message.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        content = message.get("content") or {}
        if not isinstance(content, dict):
            content = {}
        parts = content.get("parts")
        channel = message.get("channel") or metadata.get("channel")
        if role not in {"user", "assistant"} or recipient != "all" or metadata.get("is_visually_hidden_from_conversation") or channel in {"analysis", "commentary"}:
            skipped += 1
            continue
        if (content.get("content_type") not in {None, "text"} or not isinstance(parts, list)
                or not parts or any(not isinstance(part, str) for part in parts)):
            skipped += 1
            reasons.append("At least one non-text message was omitted from playable pairs")
            continue
        text = "\n".join(parts)
        if not text.strip():
            skipped += 1
            continue
        messages.append({"role": role, "text": text, "source_message_id": message.get("id")})

    pending = None
    turns = []
    for entry in messages:
        if entry["role"] == "user":
            if pending is not None:
                skipped += 1
                reasons.append("Consecutive player messages need review")
            pending = entry
        elif pending is not None:
            turns.append({
                "action_text": pending["text"], "narrative_text": entry["text"],
                "source_user_message_id": pending["source_message_id"],
                "source_assistant_message_id": entry["source_message_id"],
            })
            pending = None
        else:
            skipped += 1
            reasons.append("An assistant message lacks a preceding player message")
    if pending is not None:
        skipped += 1
        reasons.append("Final player message has no completed assistant response")
    if not turns:
        raise ValidationError("No usable complete user/assistant pairs in the selected conversation")
    if len(turns) > MAX_TURNS:
        raise ValidationError(f"Conversation has more than {MAX_TURNS} turns; import in supported chunks without truncating")
    return {
        "conversation_id": source_id, "title": title, "turn_count": len(turns),
        "skipped_messages": skipped, "warnings": sorted(set(reasons)),
        "turns": turns,
    }


def _validated_config(config: dict, owner_id: str, source_id: str) -> tuple[str, dict, dict, list[dict]]:
    if not isinstance(config, dict):
        raise ValidationError("Import settings are required")
    title = config.get("title")
    world = config.get("world")
    persona = config.get("persona")
    characters = config.get("characters", [])
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160:
        raise ValidationError("Import title must be 1-160 characters")
    for label, value in (("world", world), ("persona", persona)):
        if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"].strip() or len(value["name"]) > 160:
            raise ValidationError(f"Import {label} name is invalid")
    if not isinstance(characters, list) or len(characters) > 128:
        raise ValidationError("Import characters list is invalid")
    normalized = []
    for index, item in enumerate(characters):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValidationError("Imported character name is invalid")
        ident = item.get("id") or str(uuid5(NAMESPACE_URL, f"playroom:{owner_id}:{source_id}:{index}:{item['name']}"))
        normalized.append({**item, "id": ident, "aliases": item.get("aliases", [])})
    return title.strip(), world, persona, normalized


def _import_progress(row: sqlite3.Row, *, already_imported: bool, resumed: bool) -> dict:
    total = int(row["paired_turns"])
    imported = int(row["imported_turns"])
    complete = row["import_status"] == "complete"
    return {
        "campaign_id": row["campaign_id"],
        "branch_id": row["branch_id"],
        "turn_count": total,
        "imported_turns": imported,
        "complete": complete,
        "already_imported": already_imported,
        "resumed": resumed,
    }


def import_conversation(connection: sqlite3.Connection, owner_id: str, source: dict, config: dict, import_key: str) -> dict:
    """Import at most one bounded chunk and durably resume on repeated calls.

    The selected source and normalized config are hashed together. A repeated
    request with the same import key must match that hash; a new key carrying
    the identical payload resumes the existing source instead of creating a
    second campaign. Each chunk and its progress marker commit atomically.
    """
    from .domain import require_uuid

    key = require_uuid(import_key, "import key")
    parsed = preview_conversation(source)
    title, world, persona, characters = _validated_config(config, owner_id, parsed["conversation_id"])
    original = _serialized_source(source)
    config_json = json.dumps(
        {"title": title, "world": world, "persona": persona, "characters": characters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256((original + "\n" + config_json).encode("utf-8")).hexdigest()
    created_new = False

    with transaction(connection):
        row = connection.execute(
            "SELECT campaign_id, branch_id, payload_hash, paired_turns, imported_turns, import_status "
            "FROM chatgpt_import_sources WHERE owner_id=? AND import_key=?",
            (owner_id, key),
        ).fetchone()
        if row is not None:
            if row["payload_hash"] != digest:
                raise ValidationError("Import key was already used for a different payload")
        else:
            row = connection.execute(
                "SELECT campaign_id, branch_id, payload_hash, paired_turns, imported_turns, import_status "
                "FROM chatgpt_import_sources WHERE owner_id=? AND payload_hash=?",
                (owner_id, digest),
            ).fetchone()

        if row is None:
            created = create_campaign(
                connection,
                owner_id,
                title,
                world,
                [dict(character) for character in characters],
                persona,
                _within_transaction=True,
            )
            connection.execute(
                "INSERT INTO chatgpt_import_sources("
                "id,owner_id,campaign_id,branch_id,import_key,payload_hash,source_conversation_id,"
                "selected_source_json,paired_turns,warnings_json,imported_at,skipped_messages,"
                "import_status,imported_turns,import_updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),?,"
                "'importing',0,strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (
                    str(uuid4()),
                    owner_id,
                    created.id,
                    created.initial_branch_id,
                    key,
                    digest,
                    parsed["conversation_id"],
                    original,
                    len(parsed["turns"]),
                    json.dumps(parsed["warnings"], ensure_ascii=False),
                    parsed["skipped_messages"],
                ),
            )
            row = connection.execute(
                "SELECT campaign_id, branch_id, payload_hash, paired_turns, imported_turns, import_status "
                "FROM chatgpt_import_sources WHERE owner_id=? AND campaign_id=?",
                (owner_id, created.id),
            ).fetchone()
            created_new = True

    if row is None:
        raise RuntimeError("ChatGPT import source was not created")
    if int(row["paired_turns"]) != len(parsed["turns"]):
        raise ValidationError("Stored import progress does not match the selected conversation")
    if row["import_status"] == "complete":
        result = _import_progress(row, already_imported=True, resumed=False)
        result["skipped_messages"] = parsed["skipped_messages"]
        result["warnings"] = parsed["warnings"]
        return result

    campaign_id = row["campaign_id"]
    branch_id = row["branch_id"]
    resumed = not created_new

    with transaction(connection):
        locked = connection.execute(
            "SELECT campaign_id, branch_id, payload_hash, paired_turns, imported_turns, import_status "
            "FROM chatgpt_import_sources WHERE owner_id=? AND campaign_id=?",
            (owner_id, campaign_id),
        ).fetchone()
        if locked is None or locked["payload_hash"] != digest:
            raise ValidationError("Stored import progress no longer matches the selected conversation")
        if int(locked["paired_turns"]) != len(parsed["turns"]):
            raise ValidationError("Stored import progress does not match the selected conversation")

        if locked["import_status"] == "complete":
            row = locked
        else:
            imported = int(locked["imported_turns"])
            if imported < 0 or imported > len(parsed["turns"]):
                raise ValidationError("Stored import progress is invalid")
            stop = min(imported + IMPORT_CHUNK_TURNS, len(parsed["turns"]))
            head = get_branch_head(connection, campaign_id, branch_id, owner_id)
            version = head.state_version
            for turn in parsed["turns"][imported:stop]:
                _create_committed_revision_in_transaction(
                    connection,
                    campaign_id,
                    branch_id,
                    turn["action_text"],
                    turn["narrative_text"],
                    expected_state_version=version,
                )
                version += 1

            complete = stop == len(parsed["turns"])
            status = "complete" if complete else "importing"
            connection.execute(
                "UPDATE chatgpt_import_sources SET imported_turns=?, import_status=?, "
                "import_updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE owner_id=? AND campaign_id=?",
                (stop, status, owner_id, campaign_id),
            )
            if complete:
                checkpoint = connection.execute(
                    "SELECT head_checkpoint_id FROM branches WHERE id=?",
                    (branch_id,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT OR IGNORE INTO import_review_checkpoints("
                    "campaign_id,owner_id,source_checkpoint_id,review_json,created_at"
                    ") VALUES(?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                    (campaign_id, owner_id, checkpoint, "{}"),
                )
            row = connection.execute(
                "SELECT campaign_id, branch_id, payload_hash, paired_turns, imported_turns, import_status "
                "FROM chatgpt_import_sources WHERE owner_id=? AND campaign_id=?",
                (owner_id, campaign_id),
            ).fetchone()

    if row is None:
        raise RuntimeError("ChatGPT import progress disappeared")
    result = _import_progress(row, already_imported=False, resumed=resumed)
    result["skipped_messages"] = parsed["skipped_messages"]
    result["warnings"] = parsed["warnings"]
    return result
