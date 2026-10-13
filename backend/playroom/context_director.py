from __future__ import annotations

from .context import validate_selection_plan
from .domain import ValidationError


def deterministic_selection(pool: dict, checkpoint_id: str, action_hash: str) -> dict:
    optional = [item for item in pool.get("optional", []) if item.get("status") == "approved"][:20]
    return validate_selection_plan(checkpoint_id, action_hash, pool, {"checkpoint_id": checkpoint_id, "action_hash": action_hash, "selected_memory_ids": [item["id"] for item in optional], "selected_characters": pool.get("selected_characters", []), "reasons": {item["id"]: "Selected by deterministic relevance ranking." for item in optional}, "reason_sources": {item["id"]: [item.get("version_id") or item["id"]] for item in optional}, "scene_ids": pool.get("scene_ids", []), "conflict_flags": []})


def validate_director_plan(pool: dict, checkpoint_id: str, action_hash: str, plan: dict) -> dict:
    if plan.get("new_facts"):
        plan = dict(plan)
        plan["new_facts"] = []
    return validate_selection_plan(checkpoint_id, action_hash, pool, plan)
