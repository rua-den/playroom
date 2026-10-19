"""Owner-authorized, strictly bounded gpt-oss:120b story-quality probe.

Only synthetic Lan/Vy text, never BANGTAN canon. One first-attempt workflow,
at most three real provider POSTs, no fallback or retry, no credential logs.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

import httpx2 as httpx

from playroom.model_profiles import (
    OLLAMA_CLOUD_API_MODEL, OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT,
    OllamaCloudVerifier,
)
from playroom.provider import OllamaCloudAdapter, ProviderFailure, ProviderResult
from playroom.roleplay_segments import parse_narrator_payload
from live_ollama_gemma4_smoke import _persist_verified_profile
from live_ollama_three_turn_trial import ACTIONS, SYSTEM, CAST, _quality_flags

APPROVAL = "OWNER_GPTOSS120B_THREE_TURN_2026_10_19"
MAX_TURNS = 3
MAX_OUTPUT_TOKENS = 960
MAX_WIRE_BYTES = 5000
MAX_USD = Decimal("0.01")
PROMPT_RATE = Decimal("0.00000015")
OUTPUT_RATE = Decimal("0.00000060")
# Conservative byte-as-token proxy, as in the existing three-turn runner.
MAX_PER_TURN_RESERVE = (PROMPT_RATE * MAX_WIRE_BYTES) + (OUTPUT_RATE * MAX_OUTPUT_TOKENS)
TOTAL_RESERVE = MAX_PER_TURN_RESERVE * MAX_TURNS


def _read_balance(key: str) -> tuple[Decimal, Decimal]:
    request = urllib.request.Request(
        "https://ollama.com/api/balance",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    with urllib.request.build_opener(NoRedirect).open(request, timeout=18) as response:
        data = json.load(response)
    try:
        included = Decimal(str(data["included"]["balance_usd"]))
        purchased = Decimal(str(data["purchased"]["balance_usd"]))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise RuntimeError("Credit source could not be verified; no inference") from None
    if not all(x.is_finite() and x >= 0 for x in (included, purchased)):
        raise RuntimeError("Credit source is invalid; no inference")
    return included, purchased


def _gate(key: str, reserve: Decimal) -> None:
    if not reserve.is_finite() or reserve <= 0 or reserve > MAX_USD:
        raise RuntimeError("Requested reserve exceeds the approved bound")
    included, purchased = _read_balance(key)
    if purchased != 0 or included < reserve:
        raise RuntimeError("No verified sufficient included credits with purchased bucket zero")
    print("CREDIT PREFLIGHT: included covers reserve, purchased zero (snapshot only)")


def _dry_contract() -> None:
    assert MAX_TURNS == len(ACTIONS) == 3
    assert Decimal("0") < TOTAL_RESERVE <= MAX_USD
    assert OLLAMA_CLOUD_API_MODEL == "gpt-oss:120b"
    fixture = {
        "provider": "ollama", "endpoint": OLLAMA_CLOUD_ENDPOINT,
        "model": OLLAMA_CLOUD_API_MODEL, "model_label": OLLAMA_CLOUD_MODEL,
        "context_limit": 131072, "output_limit": 4096,
        "credential_tier": "paid", "pricing_verified": True,
        "structured_output": False, "native_structured_output": False,
        "supported_parameters": ["max_tokens"],
        "pricing": {"prompt": str(PROMPT_RATE), "completion": str(OUTPUT_RATE)},
    }
    pinned = _persist_verified_profile(fixture)
    with httpx.Client(timeout=5.0) as client:
        adapter = OllamaCloudAdapter(
            "synthetic-no-secret", OLLAMA_CLOUD_ENDPOINT, profile=pinned, http_client=client
        )
        payload = adapter._payload({
            "model": OLLAMA_CLOUD_API_MODEL,
            "reserved_completion_tokens": MAX_OUTPUT_TOKENS,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps({"player_action": ACTIONS[0]}, ensure_ascii=False)}],
        })
    assert payload["model"] == "gpt-oss:120b"
    assert payload["max_tokens"] == MAX_OUTPUT_TOKENS
    assert payload["stream"] is True
    assert "provider" not in payload
    assert _quality_flags([{"kind": "narration", "text": "Lan bắt đầu tìm kiếm quanh quầy."}])[0]
    print("GPT-OSS 120B OFFLINE CONTRACT: PASS; zero HTTP calls")


def main() -> int:
    if os.environ.get("GPTOSS_DRY_RUN") == "1":
        _dry_contract()
        return 0
    if (os.environ.get("GPTOSS_LIVE_APPROVAL") != APPROVAL
            or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
        print("DENIED: first-attempt, owner-authorized workflow only")
        return 2
    key = os.environ.get("OLLAMA_API_KEY")
    if not key:
        print("DENIED: missing Ollama secret")
        return 2

    stage, posts = "preflight", 0
    try:
        # Requires the full conservative trial allowance before any dispatch.
        _gate(key, TOTAL_RESERVE)
        stage = "verify_model"
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            profile = OllamaCloudVerifier(http_client=client).verify(
                key, OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT
            )
            if profile["model"] != OLLAMA_CLOUD_API_MODEL:
                raise RuntimeError("Wrong verified model")
            if profile.get("free_starter_eligible") is not False:
                raise RuntimeError("Unexpected entitlement mapping: abort")
            profile = _persist_verified_profile(profile)
            adapter = OllamaCloudAdapter(key, OLLAMA_CLOUD_ENDPOINT, profile=profile, http_client=client)
            messages = [{"role": "system", "content": SYSTEM}]
            for index, action in enumerate(ACTIONS, 1):
                stage = f"turn_{index}_preflight"
                _gate(key, MAX_PER_TURN_RESERVE)
                context = {
                    "setting": "Hiệu sách vắng lúc tối, Lan và Vy ở quầy, Bình ở nơi khác.",
                    "selected_characters": [{
                        "name": "Vy", "character_id": "npc-vy-synthetic",
                        "profile_version_id": "vy-profile-v1", "present": True,
                    }],
                    "public_canon": "Một tờ giấy xanh từng nằm trong hộp gỗ, nội dung tờ giấy chưa ai biết.",
                    "narrator_private": "Người giao hàng đã tráo tờ giấy; Vy hoàn toàn không biết.",
                    "turn": index, "player_action": action,
                }
                messages.append({"role": "user", "content": json.dumps(context, ensure_ascii=False)})
                bytes_on_wire = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
                if bytes_on_wire > MAX_WIRE_BYTES:
                    raise RuntimeError("Input limit exceeded before dispatch")
                stage = f"turn_{index}_stream"
                posts += 1  # Count possible dispatch conservatively.
                events = list(adapter.generate_text({
                    "model": OLLAMA_CLOUD_API_MODEL,
                    "messages": messages,
                    "reserved_completion_tokens": MAX_OUTPUT_TOKENS,
                }))
                failures = [x for x in events if isinstance(x, ProviderFailure)]
                if failures:
                    print(f"TURN {index}: PROVIDER_FAILURE={failures[0].code}; no retry")
                    return 1
                result = next((x for x in reversed(events) if isinstance(x, ProviderResult)), None)
                if result is None or result.finish_reason != "stop":
                    print(f"TURN {index}: missing clean terminal frame; no retry")
                    return 1
                try:
                    narrative, segments = parse_narrator_payload(result.text, CAST)
                except Exception as exc:
                    print(f"TURN {index}: invalid structured response {type(exc).__name__}; no retry")
                    return 1
                if not segments:
                    print(f"TURN {index}: no segments; no retry")
                    return 1
                agency, absent, leak = _quality_flags(segments)
                usage = result.usage if isinstance(result.usage, dict) else {}
                pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
                print(f"TURN {index}: segments={len(segments)} agency_warning={agency} "
                      f"absent_warning={absent} knowledge_warning={leak}")
                if isinstance(pt, int) and isinstance(ct, int):
                    estimate = PROMPT_RATE * pt + OUTPUT_RATE * ct
                    print(f"TURN {index}: tokens={pt}/{ct}, calculated_usd={estimate} (not vendor invoice)")
                # Public synthetic text only. Strip controls and minimize logs.
                excerpt = re.sub(r"[\x00-\x1f\x7f]", " ", narrative)[:680]
                print(f"TURN {index} SYNTHETIC EXCERPT: {excerpt}")
                if agency or absent or leak:
                    print(f"TURN {index}: SEMANTIC_WARNING, STOP; no retry")
                    return 1
                messages.append({"role": "assistant", "content": result.text})
        print(f"GPT-OSS LIVE RESULT: PASS; model=gpt-oss:120b; posts_started={posts}")
        return 0
    except Exception as exc:
        print(f"GPT-OSS LIVE RESULT: STOPPED at {stage}: {type(exc).__name__}; posts_started={posts}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
