"""B2: contract tests for a paid Ollama Cloud narrator (no live API calls)."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx2 as httpx
import pytest

from playroom.auth import create_owner
from playroom.campaigns import create_campaign
from playroom.db import connect, migrate
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
