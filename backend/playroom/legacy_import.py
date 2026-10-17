"""Strict, metadata-only validation of a selected legacy story bundle.

This is NOT ChatGPT conversations.json and has no replayable turn history.
No private source is logged, sent to a model, or included in public fixtures.
The import/persistence stage is a separate checkpoint.
"""
from __future__ import annotations

import json
from uuid import UUID

from .domain import ValidationError

MAX_LEGACY_BYTES = 20 * 1024 * 1024
FORMAT = "playroom_legacy_story_bundle"
SCHEMA = "1.0.0"


def _record(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def _items(value: object, label: str, limit: int) -> list:
    if not isinstance(value, list) or len(value) > limit:
        raise ValidationError(f"{label} must be an array of at most {limit} items")
    return value


def _uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a UUID")
    try:
        normalized = str(UUID(value))
    except ValueError as exc:
        raise ValidationError(f"{label} must be a UUID") from exc
    if normalized != value:
        raise ValidationError(f"{label} must use the canonical UUID format")
    return normalized


def _text(value: object, label: str, *, max_len: int = 20000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise ValidationError(f"{label} must be nonempty bounded text")
    return value


def _refs(value: object, label: str, valid: set[str], *, limit: int = 128) -> list[str]:
    values = _items(value, label, limit)
    normalized = [_uuid(item, label) for item in values]
    if len(set(normalized)) != len(normalized) or not set(normalized).issubset(valid):
        raise ValidationError(f"{label} contains duplicates or unknown character references")
    return normalized


def preview_legacy_bundle(source: dict) -> dict:
    """Return safe structural metadata only. Never return raw prose or excerpts."""
    root = _record(source, "Legacy bundle")
    try:
        encoded = json.dumps(root, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValidationError("Legacy bundle JSON is invalid") from exc
    if len(encoded) > MAX_LEGACY_BYTES:
        raise ValidationError("Legacy bundle exceeds the 20 MiB limit")
    if root.get("format") != FORMAT or root.get("schema_version") != SCHEMA:
        raise ValidationError("Unsupported legacy bundle format or schema version")
    if root.get("is_app_export") is not False or root.get("can_roundtrip_app_export") is not False:
        raise ValidationError("Legacy bundle must not claim to be a complete application export")

    _text(root.get("title"), "Bundle title", max_len=160)
    create = _record(root.get("campaign_create_payload"), "Campaign source")
    _text(create.get("title"), "Campaign title", max_len=160)
    _text(_record(create.get("world"), "World").get("name"), "World name", max_len=160)
    persona = _record(create.get("persona"), "Persona")
    player_id = _uuid(persona.get("id"), "Persona id")
    _text(persona.get("name"), "Persona name", max_len=160)
    if persona.get("player_controlled") is not True:
        raise ValidationError("Player persona must remain player-controlled")
    _record(create.get("style"), "Style")

    profiles = _items(create.get("characters"), "NPC profiles", 128)
    npc_ids: set[str] = set()
    for item in profiles:
        npc = _record(item, "NPC profile")
        ident = _uuid(npc.get("id"), "NPC id")
        _text(npc.get("name"), "NPC name", max_len=160)
        if ident == player_id or ident in npc_ids or npc.get("player_controlled") is True:
            raise ValidationError("NPC profiles must be unique and must exclude the player")
        aliases = npc.get("aliases", [])
        if not isinstance(aliases, list) or len(aliases) > 64 or any(not isinstance(a, str) or len(a) > 160 for a in aliases):
            raise ValidationError("NPC aliases are invalid")
        npc_ids.add(ident)

    roster = _items(root.get("characters"), "Character roster", 129)
    roster_ids = [_uuid(_record(c, "Character").get("id"), "Character id") for c in roster]
    if len(roster_ids) != len(set(roster_ids)) or set(roster_ids) != npc_ids | {player_id}:
        raise ValidationError("Roster and campaign NPC/persona identities do not match")
    valid_ids = set(roster_ids)

    events = _items(root.get("timeline_events"), "Timeline events", 500)
    event_keys: set[str] = set()
    event_ids: set[str] = set()
    previous_order = -1
    for item in events:
        event = _record(item, "Timeline event")
        event_id = _uuid(event.get("id"), "Timeline event id")
        key = _text(event.get("key"), "Timeline event key", max_len=160)
        _text(event.get("summary"), "Timeline summary")
        _text(event.get("title"), "Timeline event title", max_len=500)
        if "chapter_range" in event:
            _text(event["chapter_range"], "Timeline chapter range", max_len=160)
        if "publicity" in event and event["publicity"] not in {"public", "restricted", "narrator_only", "unknown", "generally_known_within_relevant_group"}:
            raise ValidationError("Timeline event publicity is invalid")
        order = event.get("order")
        if type(order) is not int or order <= previous_order or key in event_keys or event_id in event_ids:
            raise ValidationError("Timeline event keys, IDs and strictly increasing orders must be unique")
        previous_order = order
        event_keys.add(key)
        event_ids.add(event_id)
        _refs(event.get("participant_ids"), "Event participants", valid_ids)

    facts = _items(root.get("canon_facts"), "Canon facts", 500)
    fact_ids: set[str] = set()
    fact_keys: set[str] = set()
    for item in facts:
        fact = _record(item, "Canon fact")
        fact_id = _uuid(fact.get("id"), "Canon fact id")
        key = _text(fact.get("key"), "Canon fact key", max_len=160)
        _text(fact.get("text"), "Canon fact text")
        if fact_id in fact_ids or key in fact_keys:
            raise ValidationError("Canon fact IDs and keys must be unique")
        fact_ids.add(fact_id)
        fact_keys.add(key)
        if fact.get("knowledge_scope") not in {"public", "known_by", "narrator_only"}:
            raise ValidationError("Invalid canon knowledge_scope")
        known_by = _refs(fact.get("known_by_entity_ids"), "Canon knowledge reference", valid_ids)
        if fact["knowledge_scope"] == "known_by" and not known_by:
            raise ValidationError("Known-by canon must name its readers")
        related = _items(fact.get("related_event_keys", []), "Related event keys", 500)
        if any(not isinstance(k, str) or k not in event_keys for k in related) or len(set(related)) != len(related):
            raise ValidationError("Canon fact references an unknown event")

    relations = _items(root.get("relationship_states"), "Relationships", 500)
    for item in relations:
        relation = _record(item, "Relationship")
        _refs([relation.get("from_id"), relation.get("to_id")], "Relationship characters", valid_ids)
        if "type" in relation:
            _text(relation["type"], "Relationship type", max_len=160)
        if "state" in relation:
            _text(relation["state"], "Relationship state", max_len=1000)

    excerpts = _items(root.get("player_source_excerpts_ch137_156"), "Player excerpts", 1000)
    for item in excerpts:
        excerpt = _record(item, "Player excerpt")
        _text(excerpt.get("source_id"), "Excerpt source id", max_len=256)
        _text(excerpt.get("text"), "Excerpt text")
        if (excerpt.get("source_type") != "verbatim_user_message_excerpt"
                or excerpt.get("actor_role") != "player"
                or excerpt.get("completeness") != "user_excerpt_only"):
            raise ValidationError("Only explicitly incomplete player-authored excerpts are supported")

    integrity = _record(root.get("data_integrity"), "Data integrity")
    checkpoint = _record(root.get("resume_checkpoint"), "Resume checkpoint")
    last = integrity.get("last_completed_chapter")
    following = integrity.get("next_chapter")
    if (type(last) is not int or type(following) is not int or last < 0 or following != last + 1
            or integrity.get("next_chapter_has_been_written") is not False
            or checkpoint.get("chapter_last_completed") != last
            or checkpoint.get("next_chapter_number") != following
            or checkpoint.get("next_chapter_written") is not False):
        raise ValidationError("Completed/next chapter metadata is contradictory")
    focus = _record(checkpoint.get("focus_scene"), "Resume scene")
    _uuid(focus.get("scene_id"), "Resume scene id")
    _text(focus.get("location"), "Resume location", max_len=500)
    present = _refs(focus.get("present_character_ids"), "Present characters", valid_ids)
    for field in ("narrator_must_not_assume", "narrator_may_assume"):
        if field in focus:
            notes = _items(focus[field], field, 64)
            if any(not isinstance(note, str) or len(note) > 2000 for note in notes):
                raise ValidationError(f"{field} must contain bounded text only")
    if "relative_time" in focus and focus["relative_time"] is not None:
        _text(focus["relative_time"], "Resume relative time", max_len=300)
    if "player_latest_exact" in focus and focus["player_latest_exact"] is not None:
        _text(focus["player_latest_exact"], "Latest exact player excerpt", max_len=20000)

    gaps = _items(root.get("gaps_and_review_queue"), "Missing-history review queue", 500)
    for item in gaps:
        _record(item, "Missing-history review item")

    return {
        "format": FORMAT,
        "schema_version": SCHEMA,
        "title": root["title"],
        "counts": {
            "characters": len(roster),
            "canon_facts": len(facts),
            "relationships": len(relations),
            "timeline_events": len(events),
            "player_excerpts": len(excerpts),
        },
        "turn_count": 0,
        "missing_history": True,
        "checkpoint": {
            "last_completed_chapter": last,
            "next_chapter": following,
            "next_chapter_written": False,
            "present_character_count": len(present),
        },
        "warnings": [
            "Legacy bundle is structured source material, not a complete conversation transcript.",
            "Chapter numbers are not Playroom turn/revision IDs; missing chapters must not be invented.",
            "Canon, knowledge scopes, character presence and resume checkpoint require explicit owner review.",
        ],
        "requires_owner_review": True,
    }


def import_legacy_bundle(connection, owner_id: str, source: dict, import_key: str) -> dict:
    """Atomically stage profiles/scene/memories as REVIEW REQUIRED, with no turns.

    This is local durable import only; no remote model is invoked.
    """
    import hashlib
    from uuid import uuid4

    from .campaigns import create_campaign
    from .db import transaction
    from .domain import require_uuid
    from .memory import _append_memory_in_transaction
    from .timeline import _advance_checkpoint, get_branch_head, load_state_checkpoint, utc_now

    report = preview_legacy_bundle(source)
    key = require_uuid(import_key, "import key")
    owner_id = require_uuid(owner_id, "owner id")
    serialized = json.dumps(source, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    payload = source["campaign_create_payload"]

    with transaction(connection):
        existing = connection.execute(
            "SELECT campaign_id, branch_id, payload_hash FROM legacy_import_sources WHERE owner_id=? AND import_key=?",
            (owner_id, key),
        ).fetchone()
        if existing:
            if existing["payload_hash"] != digest:
                raise ValidationError("Import key already used for another legacy source")
            return {"campaign_id": existing["campaign_id"], "branch_id": existing["branch_id"], "already_imported": True, "turn_count": 0}
        duplicate = connection.execute(
            "SELECT campaign_id, branch_id FROM legacy_import_sources WHERE owner_id=? AND payload_hash=?",
            (owner_id, digest),
        ).fetchone()
        if duplicate:
            return {"campaign_id": duplicate["campaign_id"], "branch_id": duplicate["branch_id"], "already_imported": True, "turn_count": 0}

        created = create_campaign(
            connection, owner_id, payload["title"], dict(payload["world"]),
            [dict(character) for character in payload["characters"]], dict(payload["persona"]),
            style=dict(payload["style"]), _within_transaction=True,
        )
        campaign_id, branch_id = created.id, created.initial_branch_id
        version = 1
        for fact in source["canon_facts"]:
            _append_memory_in_transaction(
                connection, campaign_id, branch_id, "lore", f"[legacy canon {fact['key']}] {fact['text']}",
                origin="import", status="pending", expected_state_version=version,
                source_revision_ids=[], knowledge_scope=fact["knowledge_scope"],
                known_by=list(fact["known_by_entity_ids"]),
            )
            version += 1
        for event in source["timeline_events"]:
            # Never manufacture a full turn/revision from a chapter summary.
            text = f"[legacy event {event['key']}] {event.get('chapter_range', 'Historical summary')}: {event['title']} — {event['summary']}"
            _append_memory_in_transaction(
                connection, campaign_id, branch_id, "event", text,
                origin="import", status="pending", expected_state_version=version,
                source_revision_ids=[], entity_ids=list(event["participant_ids"]),
                knowledge_scope="narrator_only" if event.get("publicity") == "restricted" else "public",
            )
            version += 1
        for relation in source["relationship_states"]:
            text = f"{relation.get('type', 'relationship')}: {relation.get('state', 'unspecified')}"
            _append_memory_in_transaction(
                connection, campaign_id, branch_id, "relationship", text,
                origin="import", status="pending", expected_state_version=version,
                source_revision_ids=[], entity_ids=[relation["from_id"], relation["to_id"]],
                knowledge_scope="narrator_only",  # Conservative until reviewed.
            )
            version += 1

        focus = source["resume_checkpoint"]["focus_scene"]
        checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, None)
        scene_version = str(uuid4())
        scene_checkpoint = str(uuid4())
        scene_record = {
            "id": focus["scene_id"], "name": focus["location"],
            "relative_time": focus.get("relative_time"),
            "present_ids": list(focus["present_character_ids"]),
            "unverified_legacy_resume": True,
            "last_player_excerpt_unverified": focus.get("player_latest_exact"),
            "narrator_must_not_assume": focus.get("narrator_must_not_assume", []),
        }
        connection.execute(
            "INSERT INTO scene_versions(id,campaign_id,branch_id,version,data_json,effective_state_version,effective_checkpoint_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (scene_version, campaign_id, branch_id, 2,
             json.dumps({"focus_scene_id": focus["scene_id"], "scenes": {focus["scene_id"]: scene_record}}, ensure_ascii=False),
             version + 1, scene_checkpoint, utc_now()),
        )
        snapshot = dict(checkpoint.snapshot)
        snapshot["scene_version_id"] = scene_version
        _advance_checkpoint(connection, campaign_id, branch_id, version, snapshot, checkpoint_id=scene_checkpoint)

        connection.execute(
            "INSERT INTO legacy_import_sources(id,owner_id,campaign_id,branch_id,import_key,payload_hash,selected_source_json,warnings_json,canon_count,event_count,excerpt_count,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), owner_id, campaign_id, branch_id, key, digest, serialized,
             json.dumps(report["warnings"], ensure_ascii=False), report["counts"]["canon_facts"],
             report["counts"]["timeline_events"], report["counts"]["player_excerpts"], utc_now()),
        )
        connection.execute(
            "INSERT INTO import_review_checkpoints(campaign_id,owner_id,source_checkpoint_id,review_json,created_at) VALUES(?,?,?,?,?)",
            (campaign_id, owner_id, scene_checkpoint, "{}", utc_now()),
        )
    return {
        "campaign_id": campaign_id, "branch_id": branch_id, "checkpoint_id": scene_checkpoint,
        "turn_count": 0, "already_imported": False, "review_required": True,
        "pending_memories": len(source["canon_facts"]) + len(source["timeline_events"]) + len(source["relationship_states"]),
        "warnings": report["warnings"],
    }
