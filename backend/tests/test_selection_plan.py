from __future__ import annotations

import pytest

from playroom.context import validate_selection_plan
from playroom.domain import ValidationError


def test_selection_plan_rejects_ids_outside_the_effective_pool():
    pool = {"checkpoint_id": "cp-a", "action_hash": "hash-a", "mandatory": [], "optional": [{"id": "memory-a", "status": "approved", "branch_id": "branch-a"}], "scene_ids": ["scene-a"]}
    with pytest.raises(ValidationError, match="outside the candidate pool"):
        validate_selection_plan("cp-a", "hash-a", pool, {"checkpoint_id": "cp-a", "action_hash": "hash-a", "selected_memory_ids": ["invented"], "reasons": {"invented": "Relevant"}, "scene_ids": ["scene-a"]})


@pytest.mark.parametrize("plan", [
    {"checkpoint_id": "wrong", "action_hash": "hash-a", "selected_memory_ids": [], "reasons": {}, "scene_ids": ["scene-a"]},
    {"checkpoint_id": "cp-a", "action_hash": "wrong", "selected_memory_ids": [], "reasons": {}, "scene_ids": ["scene-a"]},
    {"checkpoint_id": "cp-a", "action_hash": "hash-a", "selected_memory_ids": ["memory-a", "memory-a"], "reasons": {"memory-a": "Relevant"}, "scene_ids": ["scene-a"]},
    {"checkpoint_id": "cp-a", "action_hash": "hash-a", "selected_memory_ids": [], "reasons": {}, "scene_ids": ["missing"]},
])
def test_selection_plan_rejects_wrong_checkpoint_hash_duplicate_and_missing_scene(plan):
    pool = {"checkpoint_id": "cp-a", "action_hash": "hash-a", "mandatory": [], "optional": [{"id": "memory-a", "status": "approved", "branch_id": "branch-a"}], "scene_ids": ["scene-a"]}
    with pytest.raises(ValidationError):
        validate_selection_plan("cp-a", "hash-a", pool, plan)


def test_director_cannot_select_pending_or_remove_mandatory_blocks():
    pool = {"checkpoint_id": "cp-a", "action_hash": "hash-a", "mandatory": [{"id": "pinned", "text": "Player rule"}], "optional": [{"id": "pending", "status": "pending", "branch_id": "branch-a"}], "scene_ids": []}
    with pytest.raises(ValidationError, match="pending"):
        validate_selection_plan("cp-a", "hash-a", pool, {"checkpoint_id": "cp-a", "action_hash": "hash-a", "selected_memory_ids": ["pending"], "reasons": {"pending": "Mentioned"}, "scene_ids": [], "new_facts": ["The character is now a king"]})
    validated = validate_selection_plan("cp-a", "hash-a", pool, {"checkpoint_id": "cp-a", "action_hash": "hash-a", "selected_memory_ids": [], "reasons": {}, "scene_ids": [], "new_facts": ["The character is now a king"]})
    assert validated["mandatory"] == [{"id": "pinned", "text": "Player rule"}]
    assert validated["new_facts"] == []


def test_selection_explanation_must_cite_source_and_wrong_branch_candidate_is_rejected():
    memory = {"id": "memory-a", "version_id": "version-a", "source_revision_ids": ["revision-a"], "status": "approved", "branch_id": "branch-a"}
    pool = {"checkpoint_id": "cp-a", "action_hash": "hash-a", "branch_id": "branch-a", "mandatory": [{"id": "pinned"}], "optional": [memory], "scene_ids": []}
    base = {"checkpoint_id": "cp-a", "action_hash": "hash-a", "selected_memory_ids": ["memory-a"], "reasons": {"memory-a": "Henn mentioned this promise."}, "scene_ids": []}
    with pytest.raises(ValidationError, match="cite"):
        validate_selection_plan("cp-a", "hash-a", pool, base)
    valid = validate_selection_plan("cp-a", "hash-a", pool, {**base, "reason_sources": {"memory-a": ["revision-a"]}})
    assert valid["reason_sources"]["memory-a"] == ["revision-a"]
    wrong_branch_pool = {**pool, "optional": [{**memory, "branch_id": "branch-b"}]}
    with pytest.raises(ValidationError, match="another branch"):
        validate_selection_plan("cp-a", "hash-a", wrong_branch_pool, {**base, "reason_sources": {"memory-a": ["revision-a"]}})
