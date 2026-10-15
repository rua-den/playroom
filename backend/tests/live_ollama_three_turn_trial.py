"""Three sequential synthetic Ollama Gemma4 turns, owner-authorized 2026-10-15.

The result is a narrator quality probe through Playroom's real SSE adapter,
not the full web UI or a durable Playroom campaign. No private user story.
Each turn is bounded; any failed/ambiguous attempt terminates the trial.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from decimal import Decimal, InvalidOperation

import httpx2 as httpx

from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT, OLLAMA_FREE_CLOUD_MODEL, OllamaCloudVerifier
from playroom.provider import OllamaCloudAdapter, ProviderFailure, ProviderResult
from playroom.roleplay_segments import parse_narrator_payload
from live_ollama_gemma4_smoke import _persist_verified_profile, _dry_adapter_contract


APPROVAL = "B4_THREE_SYNTHETIC_TURNS_2026_10_15"
MAX_TURNS = 3
MAX_OUTPUT_TOKENS = 640
MAX_USD_TRIAL = Decimal("0.01")
MAX_ESTIMATED_PER_TURN = Decimal("0.0015")
MODEL = "gemma4:31b"
VY_ID = "npc-vy-synthetic"
VY_VERSION = "vy-profile-v1"
CAST = {VY_ID: VY_VERSION}
ACTIONS = [
    '*Lan mở chiếc hộp gỗ trên quầy.* "Vy, cậu có thấy tờ giấy xanh không?"',
    '*Lan nhìn về phía cửa sổ, vẫn đứng cạnh quầy.* "Mình sẽ kiểm tra lại ngăn kéo."',
    '*Lan đặt chiếc hộp xuống.* "Đừng kể chuyện này với Bình khi mình chưa nói nhé."',
]
SYSTEM = (
    "You narrate an invented Vietnamese roleplay story. Reply ONLY with valid JSON "
    '{"segments":[{"kind":"narration","text":"..."},'
    '{"kind":"dialogue","text":"...","character_id":"npc-vy-synthetic",'
    '"profile_version_id":"vy-profile-v1"}]}. '
    "All response text should be Vietnamese. No code fences, analysis or text outside JSON. "
    "Only the present NPC Vy may speak, with exactly the selected id/version; "
    "Bình is absent and cannot speak or enter. "
    "Lan is controlled by the player: DO NOT invent new actions, speech, thoughts, goals, "
    "decisions or emotional reactions for Lan; existing player-authored actions may be acknowledged. "
    "Only the narrator knows that a delivery agent switched the blue paper. "
    "Vy has NOT observed or learned this fact; do not leak it into her dialogue. "
    "Respond with concrete plausible NPC behavior and preserve story continuity."
)


def _check_risk_allowance(reserve: Decimal) -> None:
    # 'reserve' is already either the TOTAL 3-turn allowance or ONE turn.
    # Multiplying the total again would incorrectly reject every trial.
    if reserve <= 0 or not reserve.is_finite() or reserve > MAX_USD_TRIAL:
        raise RuntimeError("Internal synthetic cost allowance violates owner approval")


def _credit_gate(api_key: str, reserve: Decimal) -> None:
    _check_risk_allowance(reserve)
    req = urllib.request.Request(
        "https://ollama.com/api/balance",
        headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=18) as response:
        data = json.load(response)
    try:
        included = Decimal(str(data["included"]["balance_usd"]))
        purchased = Decimal(str(data["purchased"]["balance_usd"]))
    except (TypeError, ValueError, InvalidOperation, KeyError):
        raise RuntimeError("Provider credit sources are unavailable; no request may be sent") from None
    if not included.is_finite() or not purchased.is_finite() or included < reserve or purchased != 0:
        raise RuntimeError("Included credits insufficient or purchased credits nonzero; stop before POST")
    print("BALANCE PRECHECK: included covers next conservative allowance; purchased zero (snapshot)")


def _quality_flags(segments: list[dict]) -> tuple[bool, bool, bool]:
    text = " ".join(s["text"] for s in segments)
    # Do NOT flag Lan opening/looking/placing the box: those are the user's
    # original actions. Flag NEW player choices and motions not in the prompt.
    agency = bool(re.search(
        r"Lan\s+(?:nghĩ|quyết định|tự nhủ|bước|chạy|rời|hứa|đồng ý|đáp|nói|cười|gật đầu)",
        text, re.I,
    ))
    absent = any(s.get("character_id") != VY_ID for s in segments if s["kind"] == "dialogue")
    absent = absent or bool(re.search(r"Bình\s+(?:bước vào|đứng ở quầy|lên tiếng|nói|đáp)", text, re.I))
    leaked = any(
        re.search(r"(?:giao hàng.{0,40}(?:tráo|đổi)|(?:tráo|đổi).{0,40}tờ giấy)", s["text"], re.I)
        for s in segments if s["kind"] == "dialogue"
    )
    return agency, absent, bool(leaked)


def main() -> int:
    if os.environ.get("B4_DRY_RUN") == "1":
        _dry_adapter_contract()
        assert MAX_TURNS == len(ACTIONS)
        assert MAX_ESTIMATED_PER_TURN * MAX_TURNS <= MAX_USD_TRIAL
        # Exercise BOTH branches of the guard, without reading the balance.
        _check_risk_allowance(MAX_ESTIMATED_PER_TURN)
        _check_risk_allowance(MAX_ESTIMATED_PER_TURN * MAX_TURNS)
        for invalid in (Decimal("0"), Decimal("-0.001"), MAX_USD_TRIAL + Decimal("0.000001")):
            try:
                _check_risk_allowance(invalid)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Invalid trial risk allowance was accepted")
        assert CAST == {VY_ID: VY_VERSION}
        print("THREE-TURN OFFLINE CONTRACT: PASS, zero network calls")
        return 0
    if os.environ.get("B4_THREE_TURN_APPROVAL") != APPROVAL or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        print("DENIED: one-shot approval missing or workflow rerun")
        return 2
    key = os.environ.get("OLLAMA_API_KEY")
    if not key:
        print("DENIED: secret absent")
        return 2

    stage, posts = "preflight", 0
    try:
        _credit_gate(key, MAX_ESTIMATED_PER_TURN * MAX_TURNS)
        stage = "catalog"
        with httpx.Client(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
            profile = OllamaCloudVerifier(http_client=client).verify(key, OLLAMA_FREE_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)
            if profile["model"] != MODEL or profile.get("free_starter_eligible") is not True:
                raise RuntimeError("Expected model unavailable")
            profile = _persist_verified_profile(profile)
            adapter = OllamaCloudAdapter(key, OLLAMA_CLOUD_ENDPOINT, profile=profile, http_client=client)
            messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
            for index, action in enumerate(ACTIONS, 1):
                stage = "turn_" + str(index) + "_preflight"
                _credit_gate(key, MAX_ESTIMATED_PER_TURN)
                context = {
                    "setting": "Hiệu sách vắng lúc tối, Lan và Vy ở quầy, Bình ở nơi khác.",
                    "selected_characters": [{"name": "Vy", "character_id": VY_ID,
                                              "profile_version_id": VY_VERSION, "present": True}],
                    "public_canon": "Một tờ giấy xanh từng nằm trong hộp gỗ, nội dung tờ giấy chưa ai biết.",
                    "narrator_private": "Người giao hàng đã tráo tờ giấy; Vy hoàn toàn không biết.",
                    "turn": index, "player_action": action,
                }
                messages.append({"role": "user", "content": json.dumps(context, ensure_ascii=False)})
                # Conservative byte-as-token proxy; do not exceed local USD allowance.
                wire_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
                estimate = Decimal(wire_bytes) * Decimal("0.00000014") + (
                    Decimal(MAX_OUTPUT_TOKENS) * Decimal("0.00000040")
                )
                if wire_bytes > 12000 or estimate > MAX_ESTIMATED_PER_TURN:
                    raise RuntimeError("Bounded model input/output estimate exceeded; no POST")
                stage = "turn_" + str(index) + "_stream"
                posts += 1  # conservative count: dispatch may have happened
                events = list(adapter.generate_text({
                    "model": MODEL, "messages": messages,
                    "reserved_completion_tokens": MAX_OUTPUT_TOKENS,
                }))
                errors = [event for event in events if isinstance(event, ProviderFailure)]
                if errors:
                    print(f"TURN {index}: PROVIDER FAILURE {errors[0].code}; no retry")
                    return 1
                result = next((event for event in reversed(events) if isinstance(event, ProviderResult)), None)
                if result is None or result.finish_reason != "stop":
                    print(f"TURN {index}: missing clean terminal frame; no retry")
                    return 1
                if not result.text.lstrip().startswith("{"):
                    print(f"TURN {index}: non-JSON reply; no retry")
                    return 1
                try:
                    narrative, segments = parse_narrator_payload(result.text, CAST)
                except Exception as exc:
                    print(f"TURN {index}: invalid JSON or speaker attribution: {type(exc).__name__}; no retry")
                    return 1
                if not segments:
                    print(f"TURN {index}: missing segments; no retry")
                    return 1
                agency, absent, leaked = _quality_flags(segments)
                usage = result.usage if isinstance(result.usage, dict) else {}
                prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
                print(f"TURN {index}: JSON/selected speaker PASS; segments={len(segments)}; "
                      f"agency_warning={agency}; absent_warning={absent}; knowledge_warning={leaked}")
                if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
                    computed_usd = Decimal(prompt_tokens) * Decimal("0.00000014") + (
                        Decimal(completion_tokens) * Decimal("0.00000040")
                    )
                    print(f"TURN {index}: tokens={prompt_tokens}/{completion_tokens}; "
                          f"calculated_usd={computed_usd} (NOT vendor invoice)")
                safe = re.sub(r"[\x00-\x1f\x7f]", " ", narrative)[:420]
                print(f"TURN {index} SYNTHETIC EXCERPT: {safe}")
                if agency or absent or leaked:
                    print(f"TURN {index}: semantic quality needs review; STOP (no further calls)")
                    return 1
                messages.append({"role": "assistant", "content": result.text})
            print("THREE-TURN LIVE RESULT: structurally and heuristic checks PASS")
            print("LIVE MODEL POSTS:", posts)
            print("Physical device, browser reconnect, account invoice: NOT tested")
            return 0
    except Exception as exc:
        print("THREE-TURN LIVE RESULT: stopped without retry at", stage,
              "exception:", type(exc).__name__, "posts_started:", posts)
        return 1


if __name__ == "__main__":
    sys.exit(main())
