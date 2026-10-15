"""Import exactly one owner-selected ChatGPT conversation, without model calls.

The source archive remains private and is not merged into approved canon.
Current-node traversal is mandatory: mapping iteration includes alternate AI
regenerations and unrelated tool branches and MUST NOT be used as chronology.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from uuid import uuid4

from .campaigns import create_campaign
from .db import transaction
from .domain import ValidationError
from .timeline import _create_committed_revision_in_transaction

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_NODES = 6000
MAX_TURNS = 1500


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


def _validated_config(config: dict) -> tuple[str, dict, dict, list[dict]]:
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
    for item in characters:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValidationError("Imported character name is invalid")
    return title.strip(), world, persona, characters


def import_conversation(connection: sqlite3.Connection, owner_id: str, source: dict, config: dict, import_key: str) -> dict:
    from .domain import require_uuid
    key = require_uuid(import_key, "import key")
    parsed = preview_conversation(source)
    title, world, persona, characters = _validated_config(config)
    original = _serialized_source(source)
    config_json = json.dumps({"title": title, "world": world, "persona": persona, "characters": characters},
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256((original + "\n" + config_json).encode("utf-8")).hexdigest()
    with transaction(connection):
        existing = connection.execute(
            "SELECT campaign_id, branch_id, payload_hash, paired_turns FROM chatgpt_import_sources WHERE owner_id=? AND import_key=?",
            (owner_id, key),
        ).fetchone()
        if existing:
            if existing["payload_hash"] != digest:
                raise ValidationError("Import key was already used for a different payload")
            return {"campaign_id": existing["campaign_id"], "branch_id": existing["branch_id"],
                    "turn_count": existing["paired_turns"], "already_imported": True}
        duplicate = connection.execute(
            "SELECT campaign_id, branch_id, paired_turns FROM chatgpt_import_sources WHERE owner_id=? AND payload_hash=?",
            (owner_id, digest),
        ).fetchone()
        if duplicate:
            return {"campaign_id": duplicate["campaign_id"], "branch_id": duplicate["branch_id"],
                    "turn_count": duplicate["paired_turns"], "already_imported": True}
        created = create_campaign(connection, owner_id, title, world, [dict(c) for c in characters],
                                  persona, _within_transaction=True)
        version = 1
        for turn in parsed["turns"]:
            _create_committed_revision_in_transaction(
                connection, created.id, created.initial_branch_id,
                turn["action_text"], turn["narrative_text"],
                expected_state_version=version,
            )
            version += 1
        connection.execute(
            "INSERT INTO chatgpt_import_sources(id,owner_id,campaign_id,branch_id,import_key,payload_hash,source_conversation_id,selected_source_json,paired_turns,warnings_json,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (str(uuid4()), owner_id, created.id, created.initial_branch_id, key, digest,
             parsed["conversation_id"], original, len(parsed["turns"]),
             json.dumps(parsed["warnings"], ensure_ascii=False)),
        )
    return {"campaign_id": created.id, "branch_id": created.initial_branch_id,
            "turn_count": len(parsed["turns"]), "already_imported": False,
            "skipped_messages": parsed["skipped_messages"], "warnings": parsed["warnings"]}
