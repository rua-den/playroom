from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from . import memory as memory_service
from .domain import NotFound, StateConflict, ValidationError
from .timeline import get_branch_head, load_state_checkpoint
from .token_budget import evaluate_budget

DEFAULT_OPTIONAL_POOL_LIMIT = 64
MAX_SELECTED_OPTIONAL = 20


def _canonical_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _terms(value: str) -> set[str]:
    stop_words = {"about", "after", "before", "from", "into", "that", "them", "then", "there", "this", "what", "when", "where", "will", "with", "your", "their", "the", "and", "for", "but", "not", "you", "she", "her", "him", "his", "are", "was", "were", "has", "have", "had", "make", "good", "said", "place"}
    return {term for term in re.findall(r"[\w]+", _normalize(value), flags=re.UNICODE) if len(term) > 1 and term not in stop_words}


def _contains_name(value: str, name: str) -> bool:
    normalized_name = _normalize(name).strip()
    if not normalized_name:
        return False
    return re.search(r"(?<!\w)" + re.escape(normalized_name) + r"(?!\w)", _normalize(value)) is not None


def _profiles(connection: sqlite3.Connection, campaign_id: str, snapshot: dict) -> list[dict]:
    result = []
    for key, version_id in snapshot["profile_versions"].items():
        row = connection.execute("SELECT kind, data_json FROM profile_versions WHERE id = ? AND campaign_id = ?", (version_id, campaign_id)).fetchone()
        if row is None:
            raise NotFound("Profile version is missing from the selected checkpoint")
        data = json.loads(row["data_json"])
        result.append({"id": version_id, "key": key, "kind": row["kind"], "text": json.dumps(data, ensure_ascii=False, sort_keys=True), "data": data, "source_ids": [version_id], "mandatory": True})
    return result


def _scene(connection: sqlite3.Connection, campaign_id: str, checkpoint) -> dict:
    row = connection.execute("SELECT data_json, effective_state_version, effective_checkpoint_id FROM scene_versions WHERE id = ? AND campaign_id = ?", (checkpoint.snapshot["scene_version_id"], campaign_id)).fetchone()
    if row is None:
        raise NotFound("Scene version is missing from the selected checkpoint")
    return {**json.loads(row["data_json"]), "effective_cursor": {"state_version": row["effective_state_version"], "checkpoint_id": row["effective_checkpoint_id"]}, "read_cursor": {"state_version": checkpoint.state_version, "checkpoint_id": checkpoint.id}}


def _memory_record(item, branch_id: str) -> dict:
    return {"id": item.memory_id, "version_id": item.version_id, "branch_id": branch_id, "kind": item.kind, "text": item.text, "entity_ids": list(item.entity_ids), "source_revision_ids": list(item.source_revision_ids), "pinned": item.pinned, "mandatory": item.mandatory, "status": item.status, "knowledge_scope": item.knowledge_scope, "known_by": list(item.known_by), "effective_cursor": {"state_version": item.state_version, "checkpoint_id": item.checkpoint_id}, "read_cursor": {"state_version": item.read_state_version, "checkpoint_id": item.read_checkpoint_id}}


def _selected_turns(connection: sqlite3.Connection, campaign_id: str, checkpoint) -> list[dict]:
    selected = checkpoint.snapshot.get("selected_revision_ids", [])
    if not selected:
        return []
    rows = connection.execute("SELECT t.id AS turn_id, t.sequence, t.action_text, tr.id AS revision_id, tr.narrative_text FROM turn_revisions tr JOIN turns t ON t.id = tr.turn_id WHERE t.campaign_id = ? AND tr.id IN (" + ",".join("?" for _ in selected) + ")", (campaign_id, *selected)).fetchall()
    by_revision = {row["revision_id"]: row for row in rows}
    if len(by_revision) != len(selected):
        raise ValidationError("Checkpoint transcript contains a missing or foreign revision")
    return sorted((dict(by_revision[item]) for item in selected), key=lambda row: row["sequence"])


def _rank(record: dict, terms: set[str], relevant_actor_ids: set[str]) -> tuple:
    overlap = len(terms & _terms(record["text"]))
    actors = len(relevant_actor_ids & set(record["entity_ids"]))
    obligation = 10 if record["kind"] == "promise" else 6 if record["kind"] == "event" else 0
    recency = max(record.get("source_turn_sequences", []), default=0)
    return (-(overlap * 4 + actors * 2 + obligation), -recency, record["id"])


def build_candidate_pool(connection: sqlite3.Connection, campaign_id: str, branch_id: str, action: str, *, checkpoint_id: str | None = None, owner_id: str | None = None, limit: int = DEFAULT_OPTIONAL_POOL_LIMIT) -> dict:
    if not isinstance(action, str) or not action.strip():
        raise ValidationError("Action is required to build a candidate pool")
    if not 1 <= limit <= DEFAULT_OPTIONAL_POOL_LIMIT:
        raise ValidationError("Candidate pool limit must be between 1 and 64")
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, checkpoint_id, owner_id)
    scene = _scene(connection, campaign_id, checkpoint)
    scene_values = scene.get("scenes", {})
    scene_ids = {char_id for item in scene_values.values() for char_id in item.get("present_ids", [])}
    profile_blocks = _profiles(connection, campaign_id, checkpoint.snapshot)
    profile_names = []
    for profile in profile_blocks:
        if profile["kind"] == "character":
            profile_names.extend([profile["data"].get("name", ""), *profile["data"].get("aliases", [])])
    terms = _terms(action)
    matched_actor_ids = set()
    for name in profile_names:
        if name and _contains_name(action, name):
            terms.update(_terms(name))
            matched_actor_ids.update(profile["key"].partition(":")[2] for profile in profile_blocks if profile["kind"] == "character" and name in [profile["data"].get("name", ""), *profile["data"].get("aliases", [])])
    relevant_profile_ids = scene_ids | matched_actor_ids
    selected_profiles = [profile for profile in profile_blocks if profile["kind"] in {"world", "persona", "style"} or (profile["kind"] == "character" and profile["key"].partition(":")[2] in relevant_profile_ids)]
    records = [_memory_record(item, branch_id) for item in memory_service.list_effective_memory(connection, campaign_id, branch_id, checkpoint.id, owner_id=owner_id)]
    turn_rows = _selected_turns(connection, campaign_id, checkpoint)
    sequence_by_revision = {turn["revision_id"]: turn["sequence"] for turn in turn_rows}
    for record in records:
        record["source_turn_sequences"] = [sequence_by_revision[source] for source in record["source_revision_ids"] if source in sequence_by_revision]
    mandatory = [*selected_profiles, {"id": checkpoint.snapshot["scene_version_id"], "type": "scene", "text": json.dumps(scene, ensure_ascii=False, sort_keys=True), "source_ids": [checkpoint.snapshot["scene_version_id"]], "mandatory": True}, *[item for item in records if item["mandatory"] or item["pinned"]]]
    optional = [item for item in records if item not in mandatory]
    optional.sort(key=lambda item: _rank(item, terms, scene_ids | matched_actor_ids))
    dropped = [{"id": item["id"], "reason": "optional candidate pool limit"} for item in optional[limit:]]
    dropped.extend({"id": memory_id, "reason": "pending memory approval; not eligible for context"} for memory_id in checkpoint.snapshot.get("pending_memory_versions", {}))
    recent_context = [{"turn_id": turn["turn_id"], "revision_id": turn["revision_id"], "sequence": turn["sequence"], "action": turn["action_text"], "narration": turn["narrative_text"], "source_ids": [turn["turn_id"], turn["revision_id"]]} for turn in turn_rows[-8:]]
    return {"checkpoint_id": checkpoint.id, "branch_id": branch_id, "action_hash": _canonical_hash(action), "mandatory": mandatory, "optional": optional[:limit], "scene_ids": sorted(scene_values), "scene_cast_ids": sorted(scene_ids), "excluded": dropped, "pool_limit": limit, "omission_reasons": dropped, "recent_context": recent_context}


def validate_selection_plan(checkpoint_id: str, action_hash: str, pool: dict, plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("checkpoint_id") != checkpoint_id or pool.get("checkpoint_id") != checkpoint_id:
        raise ValidationError("Selection plan checkpoint does not match")
    if plan.get("action_hash") != action_hash or pool.get("action_hash") != action_hash:
        raise ValidationError("Selection plan action does not match")
    ids = plan.get("selected_memory_ids")
    if not isinstance(ids, list) or any(not isinstance(memory_id, str) for memory_id in ids) or len(ids) > MAX_SELECTED_OPTIONAL or len(ids) != len(set(ids)):
        raise ValidationError("Selection plan memory IDs must be unique and at most 20")
    by_id = {item["id"]: item for item in pool.get("optional", [])}
    if any(memory_id not in by_id for memory_id in ids):
        raise ValidationError("Selection plan contains an ID outside the candidate pool")
    for memory_id in ids:
        item = by_id[memory_id]
        if item.get("status") != "approved":
            raise ValidationError("Selection plan cannot select pending or unapproved memory")
        if item.get("branch_id") != pool.get("branch_id"):
            raise ValidationError("Selection plan memory belongs to another branch")
    reasons = plan.get("reasons", {})
    if not isinstance(reasons, dict) or set(reasons) - set(ids) or any(not isinstance(reasons.get(memory_id), str) or not reasons[memory_id].strip() or len(reasons[memory_id]) > 180 for memory_id in ids):
        raise ValidationError("Each selected memory needs a short sourced explanation")
    reason_sources = plan.get("reason_sources", {})
    if not isinstance(reason_sources, dict) or set(reason_sources) - set(ids):
        raise ValidationError("Selection explanation has unexpected source citations")
    for memory_id in ids:
        item = by_id[memory_id]
        cited = reason_sources.get(memory_id) if isinstance(reason_sources, dict) else None
        allowed_sources = {item.get("version_id"), *item.get("source_revision_ids", [])}
        if not isinstance(cited, list) or not cited or not set(cited).issubset(allowed_sources):
            raise ValidationError("Selection explanation must cite the chosen memory's source")
    scene_ids = plan.get("scene_ids", [])
    if not isinstance(scene_ids, list) or any(not isinstance(scene_id, str) for scene_id in scene_ids) or len(scene_ids) != len(set(scene_ids)) or not set(scene_ids).issubset(set(pool.get("scene_ids", []))):
        raise ValidationError("Selection plan references a nonexistent scene")
    conflict_flags = plan.get("conflict_flags", [])
    if not isinstance(conflict_flags, list) or any(not isinstance(flag, str) or not flag.strip() or len(flag) > 160 for flag in conflict_flags):
        raise ValidationError("Selection plan conflict flags are malformed")
    return {"checkpoint_id": checkpoint_id, "action_hash": action_hash, "selected_memory_ids": ids, "reasons": reasons, "reason_sources": reason_sources, "scene_ids": scene_ids, "mandatory": pool.get("mandatory", []), "optional": [by_id[memory_id] for memory_id in ids], "new_facts": [], "conflict_flags": conflict_flags}


def build_context_preview(connection: sqlite3.Connection, campaign_id: str, branch_id: str, action: str, model_config: dict, *, owner_id: str | None = None, settings_hash: str | None = None, context_counter=None, counter_id: str = "synthetic-test-counter") -> dict:
    model_config = model_config if isinstance(model_config, dict) else {}
    counter_id = model_config.get("counter_id", counter_id)
    trusted_config = bool(model_config.get("is_test_profile") or model_config.get("capabilities_verified"))
    head = get_branch_head(connection, campaign_id, branch_id, owner_id)
    checkpoint = load_state_checkpoint(connection, campaign_id, branch_id, head.checkpoint_id, owner_id)
    omitted = []
    profiles = _profiles(connection, campaign_id, checkpoint.snapshot)
    scene = _scene(connection, campaign_id, checkpoint)
    scene_character_ids = {char_id for scene_item in scene.get("scenes", {}).values() for char_id in scene_item.get("present_ids", [])}
    matched_actor_ids = {profile["key"].partition(":")[2] for profile in profiles if profile["kind"] == "character" and any(_contains_name(action, name) for name in [profile["data"].get("name", ""), *profile["data"].get("aliases", [])])}
    relevant_profile_ids = scene_character_ids | matched_actor_ids
    selected_profiles = [profile for profile in profiles if profile["kind"] in {"world", "persona", "style"} or (profile["kind"] == "character" and profile["key"].partition(":")[2] in relevant_profile_ids)]
    memories = [_memory_record(item, branch_id) for item in memory_service.list_effective_memory(connection, campaign_id, branch_id, checkpoint.id, owner_id=owner_id)]
    turns = _selected_turns(connection, campaign_id, checkpoint)
    turn_order = {turn["revision_id"]: index for index, turn in enumerate(turns)}
    latest = {turns[-1]["revision_id"]} if turns else set()
    covered = {}
    summary_by_id = {item["id"]: item for item in memories if item["kind"] == "summary"}
    for memory in summary_by_id.values():
        sources = memory["source_revision_ids"]
        positions = [turn_order.get(source) for source in sources]
        if not sources or any(position is None for position in positions) or positions != list(range(min(positions), max(positions) + 1)):
            continue
        for source in sources:
            if source not in latest:
                covered[source] = memory["id"]
    sequence_by_revision = {turn["revision_id"]: turn["sequence"] for turn in turns}
    for memory in memories:
        memory["source_turn_sequences"] = [sequence_by_revision[source] for source in memory["source_revision_ids"] if source in sequence_by_revision]
    profile_by_actor = {profile["key"].partition(":")[2]: profile for profile in profiles if profile["kind"] == "character"}
    required_memory_ids = {memory["id"] for memory in memories if memory["mandatory"] or memory["pinned"]}
    required_memory_ids.update(covered.values())
    required_actor_ids = set(scene_character_ids) | set(matched_actor_ids)
    required_actor_ids.update(actor_id for memory in memories if memory["id"] in required_memory_ids for actor_id in {*memory["entity_ids"], *memory["known_by"]})
    selected_profile_ids = {profile["id"] for profile in profiles if profile["kind"] in {"world", "persona", "style"} or (profile["kind"] == "character" and profile["key"].partition(":")[2] in required_actor_ids)}
    selected_profiles = [profile for profile in profiles if profile["id"] in selected_profile_ids]
    blocks = []
    blocks.append({"id": f"action:{_canonical_hash(action)}", "type": "action", "text": action, "source_ids": [], "mandatory": True, "why": "Current player action must be preserved verbatim."})
    for profile in selected_profiles:
        blocks.append({"id": profile["id"], "type": profile["kind"], "text": profile["text"], "source_ids": profile["source_ids"], "mandatory": True, "why": "Checkpoint profile is required context."})
    omitted.extend({"id": profile["id"], "actor_id": profile["key"].partition(":")[2], "reason": "Actor profile is outside current scene and action relevance."} for profile in profiles if profile not in selected_profiles)
    blocks.append({"id": scene["effective_cursor"]["checkpoint_id"], "type": "scene", "text": json.dumps(scene, ensure_ascii=False, sort_keys=True), "source_ids": [checkpoint.snapshot["scene_version_id"]], "mandatory": True, "why": "Approved current scene and actor presence."})
    emitted = set()
    for memory in memories:
        if memory["mandatory"] or memory["pinned"]:
            blocks.append({"id": memory["id"], "type": "memory", "text": memory["text"], "source_ids": [memory["version_id"], *memory["source_revision_ids"]], "mandatory": True, "why": "Pinned or mandatory approved memory.", "knowledge_scope": memory["knowledge_scope"], "known_by": memory["known_by"], "as_of_cursor": memory["effective_cursor"], "source_turn_sequences": memory["source_turn_sequences"]})
    for turn in turns:
        summary_id = covered.get(turn["revision_id"])
        if summary_id:
            if summary_id not in emitted:
                memory = summary_by_id[summary_id]
                blocks.append({"id": memory["id"], "type": "memory", "text": memory["text"], "source_ids": [memory["version_id"], *memory["source_revision_ids"]], "mandatory": True, "why": "Approved summary replaces its contiguous committed interval and is required to preserve it.", "knowledge_scope": memory["knowledge_scope"], "known_by": memory["known_by"], "as_of_cursor": memory["effective_cursor"], "source_turn_sequences": memory["source_turn_sequences"]})
                emitted.add(summary_id)
            continue
        blocks.append({"id": turn["revision_id"], "type": "transcript", "text": f"Player: {turn['action_text']}\nNarration: {turn['narrative_text']}", "source_ids": [turn["turn_id"], turn["revision_id"]], "mandatory": True, "turn_sequence": turn["sequence"], "why": "Recent committed turn remains verbatim."})
    included = {block["id"] for block in blocks}
    verbatim_revision_ids = {block["id"] for block in blocks if block["type"] == "transcript"}
    covered_revision_ids = set(covered) | verbatim_revision_ids
    for memory in memories:
        if memory["id"] not in included:
            source_ids = set(memory["source_revision_ids"])
            if source_ids and source_ids.issubset(verbatim_revision_ids) and memory["kind"] not in {"promise", "event", "canon", "invariant"}:
                omitted.append({"id": memory["id"], "reason": "The complete source span is already present verbatim."})
                continue
            is_related = bool(_terms(action) & _terms(memory["text"])) or bool(set(memory["entity_ids"]) & (scene_character_ids | matched_actor_ids))
            if is_related:
                blocks.append({"id": memory["id"], "type": "memory", "text": memory["text"], "source_ids": [memory["version_id"], *memory["source_revision_ids"]], "mandatory": False, "why": "Action terms, aliases, or current scene cast match this approved memory.", "knowledge_scope": memory["knowledge_scope"], "known_by": memory["known_by"], "as_of_cursor": memory["effective_cursor"], "source_turn_sequences": memory["source_turn_sequences"]})
            else:
                omitted.append({"id": memory["id"], "reason": "No action, alias, or current-scene match."})
    omitted.extend({"id": memory_id, "reason": "Pending memory approval; pending facts cannot enter context."} for memory_id in checkpoint.snapshot.get("pending_memory_versions", {}))
    settings_hash = settings_hash or _canonical_hash({"config": model_config, "counter_id": counter_id, "counter_mode": "exact" if context_counter is not None else "estimated"})
    action_hash = _canonical_hash(action)
    budget_config = {key: model_config.get(key) for key in ("context_window", "input_limit", "output_limit", "wrapper_buffer", "requested_output")} if trusted_config else {}
    if trusted_config:
        budget_config["is_test_profile"] = bool(model_config.get("is_test_profile"))
        budget_config["capabilities_verified"] = bool(model_config.get("capabilities_verified"))
    candidate_blocks = list(blocks)
    required_blocks = [block for block in candidate_blocks if block["mandatory"]]
    optional_blocks = [block for block in candidate_blocks if not block["mandatory"]]
    record_by_id = {item["id"]: item for item in memories}
    optional_blocks.sort(key=lambda block: _rank(record_by_id[block["id"]], _terms(action), scene_character_ids | matched_actor_ids) if block["id"] in record_by_id else (0, block["id"]))
    if len(optional_blocks) > MAX_SELECTED_OPTIONAL:
        for block in optional_blocks[MAX_SELECTED_OPTIONAL:]:
            omitted.append({"id": block["id"], "reason": "Optional selection limit is 20 records."})
        optional_blocks = optional_blocks[:MAX_SELECTED_OPTIONAL]
        candidate_blocks = [*required_blocks, *optional_blocks]
    optional_memory_blocks = optional_blocks
    dependency_blocks = {}
    for block in optional_memory_blocks:
        memory = record_by_id[block["id"]]
        dependency_blocks[block["id"]] = [{"id": profile["id"], "type": "character", "text": profile["text"], "source_ids": profile["source_ids"], "mandatory": False, "why": "Profile required by selected memory actor.", "dependent_memory_id": block["id"], "actor_id": actor_id} for actor_id in sorted({*memory["entity_ids"], *memory["known_by"]}) if (profile := profile_by_actor.get(actor_id)) is not None and profile["id"] not in selected_profile_ids]
    budget = evaluate_budget(required_blocks, budget_config, counter=context_counter, counter_id=counter_id)
    selected_block_ids = {block["id"] for block in required_blocks}
    if budget["fits"]:
        selected_blocks = list(required_blocks)
        for block in optional_memory_blocks:
            dependencies = [dependency for dependency in dependency_blocks[block["id"]] if dependency["id"] not in selected_block_ids]
            trial = evaluate_budget([*selected_blocks, *dependencies, block], budget_config, counter=context_counter, counter_id=counter_id)
            if trial["fits"]:
                selected_blocks.extend([*dependencies, block])
                selected_block_ids.update(item["id"] for item in [*dependencies, block])
            else:
                omitted.append({"id": block["id"], "reason": "Optional block and its dependent actor profile omitted to fit the verified input budget."})
                omitted.extend({"id": dependency["id"], "actor_id": dependency["actor_id"], "reason": "Dependent actor profile omitted with its optional memory."} for dependency in dependencies)
        blocks = [block for block in [*required_blocks, *selected_blocks[len(required_blocks):]] if block["id"] in selected_block_ids]
        budget = evaluate_budget(blocks, budget_config, counter=context_counter, counter_id=counter_id)
    else:
        blocks = required_blocks
        omitted.extend({"id": block["id"], "reason": "Optional block and its dependent actor profile omitted because required context already exceeds the verified input budget."} for block in optional_memory_blocks)
    selected_summary_ids = emitted & {block["id"] for block in blocks}
    included_ids = {block["id"] for block in blocks}
    omitted = [entry for entry in omitted if entry["id"] not in included_ids]
    selected_replacements = {revision_id: summary_id for revision_id, summary_id in covered.items() if summary_id in selected_summary_ids}
    payload_hash = _canonical_hash({"blocks": blocks, "action": action, "config": model_config, "counter_id": counter_id, "counter_mode": budget["counter_mode"]})
    current = get_branch_head(connection, campaign_id, branch_id, owner_id)
    scene_ended = any(bool(item.get("scene_ended") or item.get("is_scene_end")) for item in scene.get("scenes", {}).values())
    review_hint = budget.get("input_tokens", 0) >= budget.get("input_cap", budget.get("input_limit", 1)) * 0.75 or scene_ended
    record = {"id": str(uuid4()), "status": "stale" if current.checkpoint_id != checkpoint.id else ("ready" if budget["fits"] else "blocked"), "failure": budget["failure"], "campaign_id": campaign_id, "branch_id": branch_id, "checkpoint_id": checkpoint.id, "state_version": checkpoint.state_version, "action": action, "action_hash": action_hash, "profile_id": model_config.get("profile_id"), "profile_version": model_config.get("profile_version"), "profile_hash": model_config.get("profile_hash"), "settings_revision": model_config.get("settings_revision"), "owner_settings_hash": model_config.get("owner_settings_hash"), "settings_hash": settings_hash, "payload_hash": payload_hash, "blocks": blocks, "replacement_map": selected_replacements, "summary_ids": sorted(selected_summary_ids), "scene": scene, "budget": budget, "omission_reasons": omitted, "review_memory_hint": review_hint, "provider_calls": 0, "mode": "deterministic_preflight", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    saved_owner = owner_id or connection.execute("SELECT owner_id FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()[0]
    connection.execute("INSERT INTO context_previews(id, campaign_id, branch_id, owner_id, checkpoint_id, state_version, action_hash, settings_hash, payload_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (record["id"], campaign_id, branch_id, saved_owner, checkpoint.id, checkpoint.state_version, action_hash, settings_hash, payload_hash, json.dumps(record, ensure_ascii=False, sort_keys=True), record["created_at"]))
    return record


def load_context_preview(connection: sqlite3.Connection, preview_id: str, owner_id: str, *, settings_hash: str | None = None) -> dict:
    row = connection.execute("SELECT payload_json, campaign_id, branch_id, checkpoint_id FROM context_previews WHERE id = ? AND owner_id = ?", (preview_id, owner_id)).fetchone()
    if row is None:
        raise NotFound("Context preview not found")
    result = json.loads(row["payload_json"])
    if settings_hash is not None and result["settings_hash"] != settings_hash:
        raise StateConflict("Context preview is stale because settings changed")
    head = get_branch_head(connection, row["campaign_id"], row["branch_id"], owner_id)
    if head.checkpoint_id != row["checkpoint_id"]:
        raise StateConflict("Context preview is stale because campaign state changed")
    return result
