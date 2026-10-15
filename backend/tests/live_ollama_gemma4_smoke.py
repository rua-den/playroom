"""Owner-authorized, one-shot *synthetic* Gemma4 Cloud stream smoke.

Not a unit test and not the full Playroom B4 live/phone acceptance.
Run ONLY by the tightly gated protected-main workflow. No automatic retries.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

import httpx

from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT, OLLAMA_FREE_CLOUD_MODEL, OllamaCloudVerifier
from playroom.provider import OllamaCloudAdapter, ProviderFailure, ProviderResult
from playroom.roleplay_segments import parse_narrator_payload


MODEL = "gemma4:31b"
MAX_OUTPUT_TOKENS = 500
OWNER_APPROVED_MAX_USD = Decimal("0.01")
# Extra conservative estimate for one short synthetic call, not a vendor hard cap.
ESTIMATED_RESERVATION_USD = Decimal("0.002")
APPROVAL_MARKER = "B4_SYNTHETIC_GEMMA4_2026_10_15"


def _balance_status(secret: str) -> None:
    req = urllib.request.Request(
        "https://ollama.com/api/balance",
        headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            payload = json.load(response)
        included = Decimal(str(payload["included"]["balance_usd"]))
        purchased = Decimal(str(payload["purchased"]["balance_usd"]))
    except (KeyError, TypeError, ValueError, InvalidOperation, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Balance source is unavailable or unexpected; no inference sent") from None
    if not included.is_finite() or not purchased.is_finite() or purchased < 0:
        raise RuntimeError("Balance source invalid; no inference sent")
    if purchased != 0 or included < ESTIMATED_RESERVATION_USD:
        raise RuntimeError("Purchased credits present or included credits below reserved threshold; no inference sent")
    # Do not print actual amounts or account identity.
    print("PRECHECK: included balance sufficient; purchased balance zero (snapshot, not lockout)")
    print("PRECHECK: one call, max output tokens:", MAX_OUTPUT_TOKENS)
    print("PRECHECK: conservative estimated USD <= 0.002; owner risk ceiling USD <= 0.01")


def main() -> int:
    if os.environ.get("B4_LIVE_APPROVAL") != APPROVAL_MARKER:
        print("DENIED: B4 approval marker absent; no inference")
        return 2
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        print("DENIED: one-shot trial cannot run on a workflow rerun")
        return 2
    secret = os.environ.get("OLLAMA_API_KEY", "")
    if not secret:
        print("DENIED: API secret unavailable")
        return 2
    if ESTIMATED_RESERVATION_USD > OWNER_APPROVED_MAX_USD:
        print("DENIED: local reservation exceeds approved risk ceiling")
        return 2
    try:
        _balance_status(secret)
        with httpx.Client(timeout=httpx.Timeout(75.0, connect=15.0)) as client:
            verifier = OllamaCloudVerifier(http_client=client)
            profile = verifier.verify(secret, OLLAMA_FREE_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT)
            if profile["model"] != MODEL or profile.get("free_starter_eligible") is not True:
                print("DENIED: Gemma4 catalog or model identity not verified")
                return 2

            selected = {"npc-vy-synthetic": "vy-profile-v1"}
            system = (
                "You narrate an invented Vietnamese roleplay scene. Reply in Vietnamese ONLY as one "
                "compact JSON object with a 'segments' array; do not use Markdown or commentary. "
                "Each segment is either {'kind':'narration','text':'...'} or "
                "{'kind':'dialogue','text':'...', 'character_id':'npc-vy-synthetic',"
                "'profile_version_id':'vy-profile-v1'}. "
                "ONLY Vy is a permitted speaker. The player Lan controls Lan's actions, thoughts, "
                "speech and decisions: NEVER invent an additional action, speech or decision for Lan. "
                "Binh is absent and must NOT appear or speak. "
                "Vy does not know the private narrator fact about the delivery agent."
            )
            scenario = {
                "setting": "Cửa hiệu sách nhỏ lúc tối. Lan ở quầy; Vy cũng đang ở đó.",
                "player": "Lan",
                "player_action": "*Lan mở chiếc hộp gỗ trên quầy.* \"Vy, cậu có thấy tờ giấy xanh không?\"",
                "selected_characters": [{
                    "character_id": "npc-vy-synthetic",
                    "profile_version_id": "vy-profile-v1",
                    "name": "Vy", "present": True,
                    "known_facts": ["Có chiếc hộp gỗ trên quầy", "Có tờ giấy màu xanh trước đây"],
                }],
                "absent_character": {"name": "Bình", "present": False},
                "public_fact": "Nội dung tờ giấy xanh chưa ai biết.",
                "narrator_private_fact": "Một người giao hàng đã tráo tờ giấy, Vy không biết.",
                "desired_effect": "Vy đáp lời Lan tự nhiên và câu chuyện có phản ứng cụ thể.",
            }
            messages = [{"role": "system", "content": system}, {
                "role": "user", "content": json.dumps(scenario, ensure_ascii=False),
            }]
            # Byte length is used as a conservative input-token proxy for this
            # deliberately small synthetic request. This is NOT provider billing.
            payload_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
            estimated = Decimal(payload_bytes) * Decimal("0.00000014") + (
                Decimal(MAX_OUTPUT_TOKENS) * Decimal("0.00000040")
            )
            if estimated > ESTIMATED_RESERVATION_USD or payload_bytes > 7000:
                print("DENIED: synthetic request exceeds local bounded estimate")
                return 2
            adapter = OllamaCloudAdapter(secret, OLLAMA_CLOUD_ENDPOINT, profile=profile, http_client=client)
            # EXACTLY ONE POST. Do not retry a timeout/429/partial response.
            events = list(adapter.generate_text({
                "model": MODEL, "messages": messages,
                "reserved_completion_tokens": MAX_OUTPUT_TOKENS,
            }))
            failures = [event for event in events if isinstance(event, ProviderFailure)]
            if failures:
                print("LIVE RESULT: PROVIDER FAILURE:", failures[0].code)
                print("LIVE RESULT: no retries")
                return 1
            result = next((event for event in reversed(events) if isinstance(event, ProviderResult)), None)
            if result is None:
                print("LIVE RESULT: no valid terminal response; do not retry")
                return 1
            if result.finish_reason != "stop":
                print("LIVE RESULT: non-stop finish reason", result.finish_reason)
                return 1
            raw = result.text.strip()
            if not raw.startswith("{"):
                print("LIVE RESULT: JSON contract not followed; no retries")
                return 1
            try:
                narrative, segments = parse_narrator_payload(raw, selected)
            except Exception as exc:
                print("LIVE RESULT: JSON/attribution rejected:", type(exc).__name__)
                return 1
            if not segments:
                print("LIVE RESULT: missing valid structured segments")
                return 1
            kinds = [segment["kind"] for segment in segments]
            suspicious = bool(re.search(r"Lan\\s+(?:nghĩ|quyết định|bước|chạy|nói|đáp|đặt|mở)", narrative, re.I))
            private_leak = bool(re.search(r"giao hàng.{0,35}(?:tráo|đổi|giấu)", narrative, re.I))
            absent_speaker = any(segment.get("character_id") != "npc-vy-synthetic"
                                 for segment in segments if segment["kind"] == "dialogue")
            usage = result.usage if isinstance(result.usage, dict) else {}
            print("LIVE RESULT: STREAM TERMINAL PASS; finish=stop")
            print("LIVE RESULT: structured JSON+speaker/version:", "PASS")
            print("LIVE RESULT: segments", len(segments), "kinds", ",".join(kinds))
            print("LIVE RESULT: player-agency heuristic warning:", suspicious)
            print("LIVE RESULT: private-knowledge heuristic warning:", private_leak)
            print("LIVE RESULT: absent or forged dialogue:", absent_speaker)
            print("LIVE RESULT: usage available:", isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int))
            if isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int):
                print("LIVE RESULT: usage tokens (input/output):", usage["prompt_tokens"], usage["completion_tokens"])
                calculated = Decimal(usage["prompt_tokens"]) * Decimal("0.00000014") + (
                    Decimal(usage["completion_tokens"]) * Decimal("0.00000040")
                )
                print("LIVE RESULT: calculated USD from public rate (not invoice):", calculated)
            excerpt = re.sub(r"[\\x00-\\x1f\\x7f]", " ", narrative)[:650]
            print("SYNTHETIC NARRATIVE EXCERPT:", excerpt)
            if suspicious or private_leak or absent_speaker:
                print("LIVE QUALITY: NEEDS REVIEW; no automatic continuation")
                return 1
            print("LIVE QUALITY: first synthetic stream structurally PASS; semantic/manual review required")
            print("LIVE REQUEST COUNT: 1")
            return 0
    except Exception as exc:
        # Do not expose secret-bearing requests/headers/URLs or raw responses.
        print("LIVE RESULT: aborted without retry; exception class:", type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
