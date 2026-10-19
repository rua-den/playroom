"""B2: contract tests for a paid Ollama Cloud narrator (no live API calls)."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx2 as httpx
import pytest

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
from playroom.domain import ValidationError
from playroom.memory import update_scene
from playroom.generation import GenerationService
from playroom.model_profiles import OLLAMA_CLOUD_API_MODEL, OLLAMA_CLOUD_ENDPOINT
from playroom.provider import OllamaCloudAdapter
from playroom.timeline import get_branch_head


def _story(tmp_path):
    db = connect(tmp_path / "ollama-contract.sqlite3")
    migrate(db)
    owner = create_owner(db, "ollama-contract@example.test", "private fixture password")
    yuna_id = str(uuid4())
    campaign = create_campaign(
        db, owner.id, "Demo trận đấu", {"name": "Nhà thi đấu"},
        [{"id": yuna_id, "name": "Yuna"}],
        {"name": "Henn", "agency_rule": "Only the player writes Henn dialogue and actions"},
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id)
    scene_id = str(uuid4())
    update_scene(
        db, campaign.id, campaign.initial_branch_id,
        {"focus_scene_id": scene_id, "scenes": [{"id": scene_id, "present_ids": [yuna_id]}]},
        expected_state_version=head.state_version,
    )
    head = get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id)
    return db, owner, campaign, head, yuna_id


def _profile():
    return {
        "id": "ollama-contract", "version": 1, "profile_hash": "pinned-profile",
        "provider": "ollama", "endpoint": OLLAMA_CLOUD_ENDPOINT,
        "model": OLLAMA_CLOUD_API_MODEL, "provider_tag": None,
        "context_limit": 131072, "output_limit": 4096,
        "supported_parameters": ["max_tokens"], "output_parameter": "max_tokens",
        "structured_output": False, "native_structured_output": False,
        "pricing_verified": True, "credential_tier": "paid",
        "secret_version": "credential-pinned",
        "pricing": {"prompt": "0.00000015", "completion": "0.00000060"},
    }


def test_ollama_narrator_prompt_always_demands_attributed_json_without_native_schema(tmp_path):
    db, _, _, _, yuna_id = _story(tmp_path)
    profile = _profile()
    service = GenerationService(db, None, profile={"roles": {"narrator": profile}})
    preview = {
        "action": "Yuna, tới lượt cậu.",
        "blocks": [],
        "selected_characters": [{"character_id": yuna_id, "profile_version_id": "pinned-npc-v1"}],
    }
    settings = {"budgets": {"narrator": {"input_limit": 12000, "requested_output": 400, "wrapper_buffer": 0}}}
    _, request, _ = service._narrator_request({}, profile, preview, settings)
    prompt = request["messages"][0]["content"]
    assert 'Return exactly one JSON object with a "segments" array' in prompt
    assert '"kind": "narration"' in prompt
    assert '"kind": "dialogue"' in prompt
    assert "when structured roleplay output is enabled" not in prompt
    assert "schema" not in request
    assert request["messages"][1]["content"].find(yuna_id) >= 0


def _stream_response(
    contents: str,
    *,
    finish_reason: str | None = "stop",
    terminal: bool = True,
    refusal: bool = False,
):
    frames = []
    if refusal:
        frames.append({"choices": [{"delta": {"refusal": "Cannot comply"}}]})
    else:
        # Deliberately split a JSON string mid-object as an SSE stream.
        halfway = max(1, len(contents) // 2)
        for piece in (contents[:halfway], contents[halfway:]):
            if piece:
                frames.append({"choices": [{"delta": {"content": piece}}]})
        if finish_reason is not None:
            frames.append({"choices": [{"finish_reason": finish_reason}], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}})
    data = "".join(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n" for frame in frames)
    if terminal:
        data += "data: [DONE]\n\n"
    return httpx.Response(200, content=data.encode("utf-8"), headers={"content-type": "text/event-stream"})


def _run_mocked_narrator(tmp_path, response_factory, *, key: str):
    db, owner, campaign, head, yuna_id = _story(tmp_path)
    calls: list[dict] = []
    profile = _profile()

    def transport(request):
        assert request.headers["authorization"] == "Bearer fixture-only-secret"
        assert str(request.url) == f"{OLLAMA_CLOUD_ENDPOINT}/chat/completions"
        wire = json.loads(request.content)
        calls.append(wire)
        assert wire["model"] == OLLAMA_CLOUD_API_MODEL
        assert wire["stream"] is True
        assert wire["stream_options"] == {"include_usage": True}
        # Ollama Cloud is not advertised as a strict schema provider.
        assert "response_format" not in wire
        assert "provider" not in wire
        assert 'Return exactly one JSON object with a "segments" array' in wire["messages"][0]["content"]
        assert yuna_id in wire["messages"][1]["content"]
        return response_factory(yuna_id, campaign.profile_ids[f"character:{yuna_id}"])

    adapter = OllamaCloudAdapter(
        "fixture-only-secret", OLLAMA_CLOUD_ENDPOINT, profile=profile,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    service = GenerationService(
        db, adapter, profile={"roles": {"narrator": profile}},
        settings={"budgets": {"narrator": {"input_limit": 12000, "requested_output": 400, "wrapper_buffer": 64}}},
    )
    job = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Yuna, tới lượt cậu.",
        idempotency_key=key, expected_checkpoint_id=head.checkpoint_id,
        mode="economy", policy="capped_paid", cap="1.00",
    )
    return db, owner, campaign, head, yuna_id, service, job, calls


def _valid_segments(yuna_id, version_id):
    return json.dumps({"segments": [
        {"kind": "narration", "text": "Yuna đứng bên lưới, đợi câu trả lời."},
        {"kind": "dialogue", "text": "Tớ sẵn sàng.", "character_id": yuna_id, "profile_version_id": version_id},
    ]}, ensure_ascii=False)


def test_mocked_ollama_sse_creates_one_attributed_candidate_commit_and_no_replay(tmp_path):
    db, owner, campaign, head, yuna, service, job, calls = _run_mocked_narrator(
        tmp_path, lambda cid, vid: _stream_response(_valid_segments(cid, vid)), key="ollama-valid",
    )
    assert job["status"] == "candidate"
    assert job["draft"] == "Yuna đứng bên lưới, đợi câu trả lời.\nTớ sẵn sàng."
    assert job["output_segments"][1] == {
        "kind": "dialogue", "text": "Tớ sẵn sàng.",
        "character_id": yuna, "profile_version_id": campaign.profile_ids[f"character:{yuna}"],
    }
    assert job["attempts"] == ["narration"]
    assert job["cost_ledger"]["stages"]["narration"]["usage"]["total_tokens"] == 20
    assert job["cost_ledger"]["stages"]["narration"]["calculated_status"] == "calculated"
    assert len(calls) == 1
    assert service.commit_candidate(owner.id, job["id"])["status"] == "committed"
    updated = get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id)
    assert updated.state_version == head.state_version + 1
    assert service.commit_candidate(owner.id, job["id"])["status"] == "committed"
    # A lost original POST response can resolve by idempotency without
    # dispatching or committing another paid narration.
    recovered = service.generate(
        owner.id, campaign.id, campaign.initial_branch_id, "Yuna, tới lượt cậu.",
        idempotency_key="ollama-valid", expected_checkpoint_id=head.checkpoint_id,
        mode="economy", policy="capped_paid", cap="1.00",
    )
    assert recovered["id"] == job["id"]
    assert recovered["status"] == "committed"
    assert len(calls) == 1
    assert db.execute("SELECT COUNT(*) FROM provider_attempts WHERE generation_job_id=?", (job["id"],)).fetchone()[0] == 1


def test_mocked_ollama_accepts_complete_gemma_fenced_segments_and_commits(tmp_path):
    db, owner, campaign, head, yuna, service, job, calls = _run_mocked_narrator(
        tmp_path,
        lambda cid, vid: _stream_response("```json\\n" + _valid_segments(cid, vid) + "\\n```"),
        key="ollama-gemma-fenced",
    )
    assert job["status"] == "candidate", job.get("failure")
    assert job["draft"] == "Yuna đứng bên lưới, đợi câu trả lời.\\nTớ sẵn sàng."
    assert job["output_segments"][1]["character_id"] == yuna
    assert len(calls) == 1
    assert service.commit_candidate(owner.id, job["id"])["status"] == "committed"
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id).state_version == head.state_version + 1


@pytest.mark.parametrize(
    ("invalid", "expected"),
    [
        ('Yuna cười và nói.', "SCHEMA_INVALID"),
        ('```json\n{"segments": [{"kind": "narration", "text": "ok"}]}\n``` trailing', "SCHEMA_INVALID"),
        ('```json\n{"segments": [{"kind": "narration", "text": "ok"}]}', "SCHEMA_INVALID"),
        ('{"segments":', "SCHEMA_INVALID"),
        ('{"segments": []}', "SCHEMA_INVALID"),
        ('{"segments": [{"kind": "dialogue", "text": "Sai", "character_id": "unknown", "profile_version_id": "v1"}]}', "SCHEMA_INVALID"),
    ],
)
def test_mocked_ollama_invalid_outputs_cannot_create_candidate_or_turn(tmp_path, invalid, expected):
    db, owner, campaign, head, _, service, job, calls = _run_mocked_narrator(
        tmp_path, lambda *_: _stream_response(invalid), key="ollama-invalid",
    )
    assert job["status"] == "failed"
    assert job["failure"]["code"] == expected
    assert len(calls) == 1
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id).checkpoint_id == head.checkpoint_id
    assert db.execute("SELECT COUNT(*) FROM turns WHERE campaign_id=?", (campaign.id,)).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("wrong_profile", "SCHEMA_INVALID"),
        ("conflicting_type", "SCHEMA_INVALID"),
        ("length", "OUTPUT_TRUNCATED"),
        ("refusal", "MODEL_REFUSED"),
        ("missing_terminal", "MISSING_TERMINAL"),
    ],
)
def test_mocked_ollama_narrator_failures_do_not_commit(tmp_path, condition, expected):
    def response_for(cid, vid):
        if condition == "wrong_profile":
            text = _valid_segments(cid, "wrong-version")
        elif condition == "conflicting_type":
            text = json.dumps({"segments": [{"kind": "narration", "type": "dialogue", "text": "Sai"}]})
        else:
            text = _valid_segments(cid, vid)
        return _stream_response(
            text,
            finish_reason="length" if condition == "length" else "stop",
            terminal=condition != "missing_terminal",
            refusal=condition == "refusal",
        )

    db, owner, campaign, head, _, service, job, calls = _run_mocked_narrator(
        tmp_path, response_for, key=f"ollama-{condition}",
    )
    assert job["status"] == "failed"
    assert job["failure"]["code"] == expected
    assert len(calls) == 1
    assert get_branch_head(db, campaign.id, campaign.initial_branch_id, owner.id).checkpoint_id == head.checkpoint_id
    assert db.execute("SELECT COUNT(*) FROM turns WHERE campaign_id=?", (campaign.id,)).fetchone()[0] == 0


@pytest.mark.parametrize(("mode", "policy"), [("economy", "free_only"), ("quality", "capped_paid")])
def test_paid_ollama_profile_never_bypasses_cost_or_native_context_gate(tmp_path, mode, policy):
    db, owner, campaign, head, _ = _story(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail("Must not dispatch paid HTTP")))
    profile = _profile()
    service = GenerationService(
        db, OllamaCloudAdapter("fixture-only-secret", OLLAMA_CLOUD_ENDPOINT, profile=profile, http_client=client),
        profile={"roles": {"narrator": profile, "context": profile}},
    )
    with pytest.raises(ValidationError):
        service.generate(
            owner.id, campaign.id, campaign.initial_branch_id, "Yuna, tới lượt cậu.",
            idempotency_key=f"guard-{mode}", expected_checkpoint_id=head.checkpoint_id,
            mode=mode, policy=policy, cap="1.00" if policy == "capped_paid" else None,
        )
    assert db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 0


@pytest.mark.parametrize("legacy_plain", [False, True])
def test_player_agency_is_explicit_in_every_ollama_narrator_mode(tmp_path, legacy_plain):
    """A legacy/plain provider must not silently lose the player-agency contract."""
    db, _, _, _, yuna_id = _story(tmp_path)
    profile = {**_profile(), "legacy_plain_output": legacy_plain}
    service = GenerationService(db, None, profile={"roles": {"narrator": profile}})
    preview = {
        "action": "Lan bước tới cửa rồi dừng lại.",
        "blocks": [],
        "selected_characters": [{"character_id": yuna_id, "profile_version_id": "v1"}],
    }
    settings = {"budgets": {"narrator": {"input_limit": 12000, "requested_output": 400, "wrapper_buffer": 0}}}
    _, request, _ = service._narrator_request({}, profile, preview, settings)
    system = request["messages"][0]["content"]
    assert "Never narrate new actions, dialogue, thoughts, or decisions for the player persona." in system
    assert "Do not force A/B choices" in system
    assert "No invented canon" in system
