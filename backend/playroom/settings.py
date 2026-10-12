from __future__ import annotations

import hashlib
import json


# Internal deterministic fixture profile. It is not a provider model or a claim
# about any external model's capabilities; live profiles require verified caps.
DEFAULT_TEST_CONTEXT_PROFILE = {
    "profile_id": "fake-context-test",
    "label": "Synthetic fixture only",
    "is_test_profile": True,
    "input_limit": 12000,
    "context_window": 16512,
    "output_limit": 4000,
    "wrapper_buffer": 512,
    "requested_output": 4000,
    "token_count_mode": "estimated",
}

DEFAULT_NARRATOR_PROFILE = {
    "profile_id": "fake-narrator-test",
    "label": "Synthetic fixture narrator",
    "provider": "fake",
    "endpoint": "fake://local",
    "model": "synthetic-fixture",
    "context_limit": 12000,
    "output_limit": 4000,
    "credential_tier": "free",
    "pricing_verified": True,
    "secret_version": "synthetic",
    "is_test_profile": True,
}


def config_hash(config: dict) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
