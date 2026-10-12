from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.context import build_context_preview, build_candidate_pool, load_context_preview
from playroom.db import connect, migrate
from playroom.domain import StateConflict, ValidationError
from playroom.memory import append_memory_version, update_scene
from playroom.timeline import create_committed_revision, get_branch_head


@pytest.fixture
def story(tmp_path):
    fixture_spec = json.loads((Path(__file__).parent / "fixtures" / "context-120-pairs.json").read_text(encoding="utf-8"))
    assert fixture_spec["fixture_kind"] == "synthetic_only"
    connection = connect(tmp_path / "context.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "context@example.test", "strong context password")
    henn, mila, doctor, mentioned = (str(uuid4()) for _ in range(4))
    campaign = create_campaign(connection, owner.id, "Synthetic context fixture", {"name": "Rain City", "lore": "The old dairy has a blue gate."}, [
        {"id": henn, "name": "Henn", "aliases": ["Hen"], "height_cm": 168},
        {"id": mila, "name": "Mila", "aliases": ["Mimi"]},
        {"id": doctor, "name": "Dr. Vinh", "aliases": ["Vinh"]},
        {"id": mentioned, "name": "Bao", "aliases": ["B"]},
    ], {"name": "Henn", "agency_rule": "The player alone controls Henn's choices."})
    branch = campaign.initial_branch_id
    checkpoint = get_branch_head(connection, campaign.id, branch).checkpoint_id
    scene = {"focus_scene_id": None, "scenes": [{"id": str(uuid4()), "name": "Clinic", "location": "Old clinic", "present_ids": [henn, mila]}]}
    saved = update_scene(connection, campaign.id, branch, scene, expected_state_version=1)
    checkpoint = saved.id

    revisions = []
    head = get_branch_head(connection, campaign.id, branch)
    first_turn, first_revision = create_committed_revision(connection, campaign.id, branch, "Synthetic test action 1: Henn checks the clinic.", "Synthetic test narration 1: Henn and Mila wait at the clinic.", expected_state_version=head.state_version)
    revisions.append(first_revision)
    head = get_branch_head(connection, campaign.id, branch)
    promise = append_memory_version(connection, campaign.id, branch, "promise", "Henn promised Mila a bottle of milk at the old dairy; unresolved.", origin="user", expected_state_version=head.state_version, source_revision_ids=[first_revision], entity_ids=[henn, mila], pinned=True, mandatory=True, subject_id=henn, predicate="promise", value="deliver milk", object_id=mila)
    for turn in range(1, fixture_spec["pair_count"]):
        head = get_branch_head(connection, campaign.id, branch)
        if turn == 59:
            scene_id = str(uuid4())
            changed_scene = {"focus_scene_id": scene_id, "scenes": [{"id": scene_id, "name": "Dairy", "location": "Old dairy beside clinic", "present_ids": [henn, mila]}]}
            changed = update_scene(connection, campaign.id, branch, changed_scene, expected_state_version=head.state_version)
            head = get_branch_head(connection, campaign.id, branch)
        action = fixture_spec["action_template"].format(sequence=turn + 1)
        if str(turn + 1) in fixture_spec["special_narrations"]:
            narrative = fixture_spec["special_narrations"][str(turn + 1)]
        else:
            narrative = fixture_spec["narration_template"].format(sequence=turn + 1)
        _, revision_id = create_committed_revision(connection, campaign.id, branch, action, narrative, expected_state_version=head.state_version)
        revisions.append(revision_id)
    head = get_branch_head(connection, campaign.id, branch)
    summary = append_memory_version(connection, campaign.id, branch, "summary", "Synthetic approved chapter summary: Henn promised milk to Mila; Dr. Vinh is at the clinic; the blue gate leads to the old dairy.", origin="user", expected_state_version=head.state_version, source_revision_ids=revisions[:fixture_spec["summary_source_end_exclusive"]], entity_ids=[henn, mila, doctor], pinned=False)
    head = get_branch_head(connection, campaign.id, branch)
    relevant = append_memory_version(connection, campaign.id, branch, "lore", "The old dairy has a blue gate and is beside the clinic.", origin="user", expected_state_version=head.state_version, source_revision_ids=[revisions[1]], entity_ids=[mila, doctor])
    head = get_branch_head(connection, campaign.id, branch)
    old_event = append_memory_version(connection, campaign.id, branch, "event", "Unresolved old event: Mila left Henn the dairy ledger and expects it returned.", origin="user", expected_state_version=head.state_version, source_revision_ids=[revisions[0]], entity_ids=[henn, mila])
    for index in range(70):
        head = get_branch_head(connection, campaign.id, branch)
        append_memory_version(connection, campaign.id, branch, "lore", f"Synthetic unrelated side note {index}: a remote observatory catalog entry.", origin="user", expected_state_version=head.state_version, source_revision_ids=[revisions[3]])
    head = get_branch_head(connection, campaign.id, branch)
    pending = append_memory_version(connection, campaign.id, branch, "event", "Synthetic pending fact that must never enter context.", origin="ai", expected_state_version=head.state_version, source_revision_ids=[revisions[2]])
    head = get_branch_head(connection, campaign.id, branch)
    excluded = append_memory_version(connection, campaign.id, branch, "lore", "Synthetic irrelevant side lore about the northern observatory.", origin="user", expected_state_version=head.state_version, source_revision_ids=[revisions[3]])
    head = get_branch_head(connection, campaign.id, branch)
    other = create_campaign(connection, owner.id, "Other synthetic world", {"name": "Other"}, [], {"name": "Other player"})
    foreign_memory = append_memory_version(connection, other.id, other.initial_branch_id, "event", "Foreign campaign memory must not enter this preview.", origin="user", expected_state_version=1, source_revision_ids=[])
    assert summary.status == promise.status == relevant.status == excluded.status == "approved"
    yield {"connection": connection, "owner": owner, "campaign": campaign, "branch": branch, "henn": henn, "mila": mila, "doctor": doctor, "mentioned": mentioned, "revisions": revisions, "summary": summary, "promise": promise, "relevant": relevant, "old_event": old_event, "pending": pending, "excluded": excluded, "other": other, "foreign_memory": foreign_memory, "head": head, "fixture_spec": fixture_spec}
    connection.close()


def _model_config():
    return {"profile_id": "fake-context-test", "label": "Synthetic fixture only", "context_window": 16512, "input_limit": 12000, "output_limit": 4000, "wrapper_buffer": 512, "requested_output": 1000, "token_count_mode": "estimated", "is_test_profile": True}


def test_context_preview_replaces_approved_intervals_but_keeps_latest_turn_verbatim(story):
    connection, campaign, branch = story["connection"], story["campaign"], story["branch"]
    preview = build_context_preview(connection, campaign.id, branch, "What about the milk promise at that place?", _model_config(), owner_id=story["owner"].id)
    blocks = preview["blocks"]
    raw_ids = {block["id"] for block in blocks if block["type"] == "transcript"}
    assert story["revisions"][119] in raw_ids
    assert story["revisions"][0] not in raw_ids
    assert preview["replacement_map"][story["revisions"][0]] == preview["summary_ids"][0]
    assert any("Synthetic test narration 120" in block["text"] for block in blocks)
    assert any("controls Henn's choices" in block["text"] for block in blocks)
    assert any(block["id"] == story["pending"].memory_id for block in preview["blocks"] if block["type"] == "memory") is False
    assert all(block["id"] != story["excluded"].memory_id for block in blocks)
    assert all(block["id"] != story["foreign_memory"].memory_id for block in blocks)
    assert any(entry["id"] == story["pending"].memory_id and "Pending" in entry["reason"] for entry in preview["omission_reasons"])
    assert preview["provider_calls"] == 0 and preview["mode"] == "deterministic_preflight"
    repeated = build_context_preview(connection, campaign.id, branch, "What about the milk promise at that place?", _model_config(), owner_id=story["owner"].id)
    assert repeated["payload_hash"] == preview["payload_hash"]
    assert [block["id"] for block in repeated["blocks"]] == [block["id"] for block in blocks]
    for block in blocks:
        for source_id in block["source_ids"]:
            found = connection.execute("SELECT 1 FROM profile_versions WHERE id = ? UNION ALL SELECT 1 FROM scene_versions WHERE id = ? UNION ALL SELECT 1 FROM memory_versions WHERE id = ? UNION ALL SELECT 1 FROM turn_revisions WHERE id = ? UNION ALL SELECT 1 FROM turns WHERE id = ? LIMIT 1", (source_id, source_id, source_id, source_id, source_id)).fetchone()
            assert found is not None, (block["id"], source_id)
    assert story["doctor"] not in next(iter(preview["scene"]["scenes"].values()))["present_ids"]
    assert next(iter(preview["scene"]["scenes"].values()))["location"] == "Old dairy beside clinic"
    promise_block = next(block for block in blocks if block["id"] == story["promise"].memory_id)
    latest_block = next(block for block in blocks if block.get("turn_sequence") == 120)
    assert promise_block["as_of_cursor"]["state_version"] < preview["state_version"]
    assert promise_block["source_turn_sequences"] == [1]
    assert "closing the promise" in latest_block["text"]
    assert "181 cm" in latest_block["text"]
    henn_profile = next(block for block in blocks if block["type"] == "character" and story["henn"] in block["text"])
    assert '"height_cm": 168' in henn_profile["text"]
    assert blocks.index(promise_block) < blocks.index(latest_block)
    mentioned = connection.execute("SELECT narrative_text FROM turn_revisions WHERE id = ?", (story["revisions"][39],)).fetchone()["narrative_text"]
    assert "Bao never enters" in mentioned


def test_candidate_pool_finds_old_promise_and_indirect_reference_from_scene(story):
    pool = build_candidate_pool(story["connection"], story["campaign"].id, story["branch"], "I will make good on what I said and go there.", owner_id=story["owner"].id)
    ids = {item["id"] for item in pool["mandatory"] + pool["optional"]}
    assert story["pending"].memory_id not in ids
    assert story["foreign_memory"].memory_id not in ids
    assert set(pool["scene_cast_ids"]) == {story["henn"], story["mila"]}
    assert story["doctor"] not in pool["scene_cast_ids"] and story["mentioned"] not in pool["scene_cast_ids"]
    assert any(entry["id"] == story["pending"].memory_id for entry in pool["excluded"])
    assert any(item["id"] == story["promise"].memory_id for item in pool["mandatory"] + pool["optional"])
    assert len(pool["optional"]) <= 64
    assert all("other" not in item["text"].casefold() for item in pool["optional"])
    assert any(item["id"] == story["old_event"].memory_id for item in pool["optional"])
    alias_pool = build_candidate_pool(story["connection"], story["campaign"].id, story["branch"], "Hen checks the blue gate", owner_id=story["owner"].id)
    assert any(item["id"] == story["relevant"].memory_id for item in alias_pool["mandatory"] + alias_pool["optional"])


def test_preview_is_immutable_owned_and_stale_after_state_or_settings_change(story):
    connection, campaign, branch = story["connection"], story["campaign"], story["branch"]
    preview = build_context_preview(connection, campaign.id, branch, "Keep the promise", _model_config(), owner_id=story["owner"].id)
    saved = load_context_preview(connection, preview["id"], story["owner"].id)
    assert saved["payload_hash"] == preview["payload_hash"]
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute("UPDATE context_previews SET payload_json = '{}' WHERE id = ?", (preview["id"],))
    from playroom.campaigns import update_profile
    head = get_branch_head(connection, campaign.id, branch)
    update_profile(connection, campaign.id, branch, "world", {"name": "Changed synthetic world"}, expected_state_version=head.state_version)
    with pytest.raises(StateConflict, match="stale"):
        load_context_preview(connection, preview["id"], story["owner"].id)


def test_uncompressed_long_chapter_triggers_review_hint_without_dropping_turns(story):
    from playroom.campaigns import create_campaign
    from playroom.timeline import create_committed_revision, get_branch_head
    campaign = create_campaign(story["connection"], story["owner"].id, "Long synthetic chapter", {"name": "Long"}, [], {"name": "Player"})
    branch = campaign.initial_branch_id
    for turn in range(8):
        head = get_branch_head(story["connection"], campaign.id, branch)
        create_committed_revision(story["connection"], campaign.id, branch, f"Action {turn}", "Long synthetic narration " + ("rain and memory " * 400), expected_state_version=head.state_version)
    preview = build_context_preview(story["connection"], campaign.id, branch, "Continue", _model_config(), owner_id=story["owner"].id)
    raw_turns = [block for block in preview["blocks"] if block["type"] == "transcript"]
    assert len(raw_turns) == 8
    assert preview["review_memory_hint"] is True
    assert preview["status"] == "blocked"
    assert preview["failure"]["code"] == "REQUIRED_CONTEXT_OVERFLOW"
    assert preview["provider_calls"] == 0


def test_context_preview_routes_require_owner_and_select_only_server_configured_profile(story, tmp_path):
    from fastapi.testclient import TestClient
    from playroom.app import create_app
    from playroom.auth import create_session
    path = story["connection"].execute("PRAGMA database_list").fetchone()[2]
    app = create_app(database_url=path, allowed_hosts={"testserver"}, secure_cookies=False)
    client = TestClient(app, base_url="https://testserver")
    route = f"/api/campaigns/{story['campaign'].id}/context/previews"
    payload = {"branch_id": story["branch"], "action": "Remember the milk promise", "profile_id": "fake-context-test", "input_limit": 1}
    headers = {"origin": "https://testserver"}
    assert client.post(route, json=payload, headers=headers).status_code == 401
    client.cookies.set("playroom_session", create_session(story["connection"], story["owner"].id))
    head = get_branch_head(story["connection"], story["campaign"].id, story["branch"])
    summary_response = client.post(f"/api/campaigns/{story['campaign'].id}/memory", json={"branch_id": story["branch"], "expected_state_version": head.state_version, "kind": "summary", "text": "Manual synthetic summary, reviewed and approved by the player.", "source_revision_ids": story["revisions"][:119]}, headers=headers)
    assert summary_response.status_code == 201 and summary_response.json()["status"] == "approved"
    rejected = client.post(route, json={**payload, "profile_id": "unconfigured"}, headers=headers)
    assert rejected.status_code == 422
    response = client.post(route, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["budget"]["input_limit"] == 12000
    assert preview["provider_calls"] == 0
    assert client.get(f"/api/context/previews/{preview['id']}").json()["payload_hash"] == preview["payload_hash"]
    story_state_version = preview["state_version"]
    app.state.context_model_profiles["fake-context-test"]["wrapper_buffer"] = 511
    rebuilt = client.post(route, json=payload, headers=headers).json()
    assert rebuilt["settings_hash"] != preview["settings_hash"]
    assert rebuilt["payload_hash"] != preview["payload_hash"]
    assert rebuilt["state_version"] == story_state_version
    assert client.get(f"/api/context/previews/{preview['id']}").status_code == 409


def test_noncontiguous_summary_never_replaces_raw_turns_and_missing_limits_block(story):
    from playroom.context import build_context_preview
    from playroom.memory import append_memory_version
    from playroom.timeline import create_committed_revision, get_branch_head
    campaign = create_campaign(story["connection"], story["owner"].id, "Gap test", {"name": "Gap"}, [], {"name": "Player"})
    branch = campaign.initial_branch_id
    revisions = []
    for index in range(4):
        head = get_branch_head(story["connection"], campaign.id, branch)
        _, revision = create_committed_revision(story["connection"], campaign.id, branch, f"Action {index}", f"Narration {index}", expected_state_version=head.state_version)
        revisions.append(revision)
    head = get_branch_head(story["connection"], campaign.id, branch)
    append_memory_version(story["connection"], campaign.id, branch, "summary", "This summary skips a turn.", origin="user", expected_state_version=head.state_version, source_revision_ids=[revisions[0], revisions[2]])
    preview = build_context_preview(story["connection"], campaign.id, branch, "Continue", _model_config(), owner_id=story["owner"].id)
    assert {block["id"] for block in preview["blocks"] if block["type"] == "transcript"} == set(revisions)
    assert preview["replacement_map"] == {}
    unsupported = build_context_preview(story["connection"], campaign.id, branch, "Continue", {"profile_id": "unknown"}, owner_id=story["owner"].id)
    assert unsupported["status"] == "blocked"
    assert unsupported["failure"]["code"] == "UNSUPPORTED_MODEL_LIMITS"
    assert unsupported["provider_calls"] == 0


def test_budget_drops_optional_memory_before_blocking_required_context(story):
    head = get_branch_head(story["connection"], story["campaign"].id, story["branch"])
    append_memory_version(story["connection"], story["campaign"].id, story["branch"], "lore", "Milk " * 9000, origin="user", expected_state_version=head.state_version, source_revision_ids=[], entity_ids=[story["mila"]])
    config = {**_model_config(), "input_limit": 3000}
    preview = build_context_preview(story["connection"], story["campaign"].id, story["branch"], "milk at clinic", config, owner_id=story["owner"].id)
    assert preview["status"] == "ready"
    assert preview["budget"]["fits"] is True
    assert not any("Milk Milk" in block["text"] for block in preview["blocks"])
    assert any("budget" in item["reason"].casefold() for item in preview["omission_reasons"])


def test_latest_inclusive_summary_is_selected_or_raw_interval_is_restored(story):
    head = get_branch_head(story['connection'], story['campaign'].id, story['branch'])
    latest_summary = append_memory_version(story['connection'], story['campaign'].id, story['branch'], 'summary', 'Synthetic full chapter summary with older milk promise.', origin='user', expected_state_version=head.state_version, source_revision_ids=story['revisions'], entity_ids=[story['henn'], story['mila']])
    preview = build_context_preview(story['connection'], story['campaign'].id, story['branch'], 'What about the promise?', _model_config(), owner_id=story['owner'].id)
    raw_ids = {block['id'] for block in preview['blocks'] if block['type'] == 'transcript'}
    summarized = latest_summary.version_id in {source for block in preview['blocks'] for source in block['source_ids']}
    assert story['revisions'][-1] in raw_ids
    assert summarized or set(story['revisions'][:-1]).issubset(raw_ids)

def test_summary_coverage_does_not_discard_distinct_unresolved_memory(story):
    preview = build_context_preview(story['connection'], story['campaign'].id, story['branch'], 'Return that ledger to Mila', _model_config(), owner_id=story['owner'].id)
    assert any(block['id'] == story['old_event'].memory_id for block in preview['blocks'])

def test_alias_resolves_actor_profile_and_rank_uses_recent_effective_memory(story):
    pool = build_candidate_pool(story['connection'], story['campaign'].id, story['branch'], 'Hen, give her the ledger', owner_id=story['owner'].id)
    assert any(item['kind'] == 'character' and story['henn'] in item['text'] for item in pool['mandatory'] + pool['optional'])
    alias_candidates = [item for item in pool['optional'] if item.get('entity_ids') and story['henn'] in item['entity_ids']]
    assert alias_candidates
    assert max(max(item['source_turn_sequences'], default=0) for item in alias_candidates) == 119
    assert story['mentioned'] not in {item['key'].partition(':')[2] for item in pool['mandatory'] if item.get('kind') == 'character'}
    preview = build_context_preview(story['connection'], story['campaign'].id, story['branch'], 'Hen, what about her?', _model_config(), owner_id=story['owner'].id)
    assert any(item.get('actor_id') == story['mentioned'] and 'outside current scene' in item['reason'] for item in preview['omission_reasons'])

def test_same_relevance_actor_memory_prefers_newer_effective_turn(story):
    head = get_branch_head(story['connection'], story['campaign'].id, story['branch'])
    old = append_memory_version(story['connection'], story['campaign'].id, story['branch'], 'lore', 'Silver compass points to the north room.', origin='user', expected_state_version=head.state_version, source_revision_ids=[story['revisions'][0]], entity_ids=[story['henn']])
    head = get_branch_head(story['connection'], story['campaign'].id, story['branch'])
    newer = append_memory_version(story['connection'], story['campaign'].id, story['branch'], 'lore', 'Silver compass points to the north room.', origin='user', expected_state_version=head.state_version, source_revision_ids=[story['revisions'][-1]], entity_ids=[story['henn']])
    pool = build_candidate_pool(story['connection'], story['campaign'].id, story['branch'], 'Henn checks the silver compass', owner_id=story['owner'].id)
    ordered = [item['id'] for item in pool['optional']]
    assert ordered.index(newer.memory_id) < ordered.index(old.memory_id)

def test_preview_injected_counter_is_internal_and_owned_read_is_saved(story):
    calls = []
    counter = lambda text: calls.append(text) or len(text.split())
    preview = build_context_preview(story['connection'], story['campaign'].id, story['branch'], 'A synthetic exact count', _model_config(), owner_id=story['owner'].id, context_counter=counter, counter_id='fixture-word-counter-v1')
    assert preview['budget']['counter_mode'] == 'exact'
    assert preview['budget']['counter_id'] == 'fixture-word-counter-v1'
    assert calls
    saved = load_context_preview(story['connection'], preview['id'], story['owner'].id)
    assert saved['budget']['counter_id'] == 'fixture-word-counter-v1'
    assert '_context_counter' not in json.dumps(saved)

def test_synthetic_style_cases_keep_agency_and_style_profiles_required(story):
    style_data = json.loads((Path(__file__).parent / "fixtures" / "style-cases.json").read_text(encoding="utf-8"))
    assert style_data["fixture_kind"] == "synthetic_only"
    preview = build_context_preview(story['connection'], story['campaign'].id, story['branch'], 'Continue at the clinic', _model_config(), owner_id=story['owner'].id)
    profile_blocks = [block for block in preview['blocks'] if block['type'] in {'persona', 'style'}]
    assert any("player alone controls Henn's choices" in block['text'] for block in profile_blocks)
    assert any(block['type'] == 'style' for block in profile_blocks)

