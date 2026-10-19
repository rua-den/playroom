"""3-turn Ollama Cloud model A/B using only user-approved PUBLIC-SAFE Henn/Yuna setup.

NOT the private BANGTAN 001–156 source; no canon details, credentials or
personal checkpoint files are committed. Do not treat this as full-canon E2E.
One first-attempt, six-post maximum. No retry, no fallback, no app commits.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from decimal import Decimal

import httpx2 as httpx

from playroom.model_profiles import (
    OLLAMA_CLOUD_MODELS, OLLAMA_CLOUD_ENDPOINT, OllamaCloudVerifier,
)
from playroom.provider import OllamaCloudAdapter, ProviderFailure, ProviderResult
from playroom.roleplay_segments import parse_narrator_payload
from live_ollama_gemma4_smoke import _persist_verified_profile

APPROVAL = "OWNER_BANGTAN_MINIMAL_3X2_2026_10_20"
MODELS = ("gemma4:31b-cloud", "gpt-oss:120b-cloud")
MAX_OUTPUT = 1600
MAX_WIRE_BYTES = 10000
MAX_POSTS = 6
MAX_TOTAL_USD = Decimal("0.03")
# Upper bound uses pricier GPT-OSS for *both*, 10k bytes as 10k tokens.
MAX_PER_POST = MAX_WIRE_BYTES * Decimal("0.00000015") + MAX_OUTPUT * Decimal("0.00000060")
ALLOWANCE = MAX_PER_POST * MAX_POSTS
YUNA_ID = "npc-yuna-public-safe-eval"
YUNA_VERSION = "yuna-test-only-v1"
SELECTED = {YUNA_ID: YUNA_VERSION}
ACTIONS = (
    "*Henn ở phòng riêng, gọi điện cho Yuna. Khi cuộc gọi nối máy, Henn nói:* "
    "'Yuna, mai ra sân tập đôi sớm chút nhé? Tớ muốn tập lại mấy pha bị điều cầu hôm trước.'",
    "*Henn bật loa ngoài, đặt sổ tập lên bàn và cầm bút.* "
    "'Ừ, cậu nói thẳng đi: đôi mình cần sửa điều gì nhất?'",
    "*Henn khoanh tròn một mục trong sổ luyện tập.* "
    "'Tớ chọn tập đổi vị trí và cứu cầu cuối sân trước. Buổi tập tới mình thử cách đó nhé?'",
)
SYSTEM = (
    "Bạn là người kể truyện tương tác thanh xuân học đường bằng tiếng Việt, "
    "đối thoại đời thường, hài hước nhưng tự nhiên. Đây là bản A/B test không "
    "thuộc chương truyện chính. Nhân vật người chơi là Henn, tóc bạch kim, học "
    "giỏi và mạnh về thể thao; Yuna là bạn thân, chuyên cầu lông, tính tình "
    "hoạt bát. Henn ở phòng riêng và Yuna chỉ hiện diện qua một cuộc gọi điện thoại. "
    "DỮ LIỆU THỬ TỐI THIỂU, không có file canon BANGTAN và không suy diễn lịch sử "
    "không được cung cấp. Chỉ Henn do người chơi điều khiển: TUYỆT ĐỐI KHÔNG "
    "TỰ THÊM hành động, lời thoại, cảm xúc, suy nghĩ, quyết định của Henn ngoài "
    "hành động mới được đưa vào. Không tự đặt người khác vào phòng; không tự "
    "cho Jungkook, Mia hoặc bất kỳ nhân vật vắng mặt nói chuyện. Không ép "
    "tình cảm, không spoil bí mật. Hành động của người chơi đã được cung cấp "
    "ở đầu vào, chỉ tiếp tục miêu tả hoàn cảnh và phản ứng của Yuna. "
    "Trả về DUY NHẤT JSON có segments: mỗi phần là "
    "{kind:'narration',text:'...'} hoặc "
    "{kind:'dialogue',text:'...',character_id:'npc-yuna-public-safe-eval',"
    "profile_version_id:'yuna-test-only-v1'}. "
    "Không có dialogue của Henn. Nếu có Markdown code fence, phải là duy nhất "
    "một khối JSON hoàn chỉnh. Tạo 150–300 từ tiếng Việt cho mỗi lượt."
)

def _gate(key: str):
    """Included-credit only. Snapshot gate reserves ALL six max-size dispatches."""
    if ALLOWANCE > MAX_TOTAL_USD:
        raise RuntimeError("Budget estimate outside owner-approved ceiling")
    req = urllib.request.Request(
        "https://ollama.com/api/balance",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    with urllib.request.build_opener(NoRedirect).open(req, timeout=18) as res:
        payload = json.load(res)
    included = Decimal(str(payload["included"]["balance_usd"]))
    purchased = Decimal(str(payload["purchased"]["balance_usd"]))
    if not all(x.is_finite() and x >= 0 for x in (included, purchased)):
        raise RuntimeError("Unverified credit status")
    if included < ALLOWANCE or purchased != 0:
        raise RuntimeError("Not enough included credit or purchased credit not zero")
    print("CREDIT GATE PASS: all 6 posts reserved in included credit (snapshot); purchased=0")

def _messages(action: str, prior: list[tuple[str, str]]) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM}]
    for a, response in prior:
        messages.extend((
            {"role": "user", "content": a},
            {"role": "assistant", "content": response},
        ))
    messages.append({"role": "user", "content": json.dumps({
        "player_action": action, "selected_characters": [{
            "name": "Yuna", "character_id": YUNA_ID,
            "profile_version_id": YUNA_VERSION, "present_by_phone_only": True,
        }], "physical_scene_cast": ["Henn"], "test_only": True,
    }, ensure_ascii=False)})
    return messages

def _contract():
    assert len(ACTIONS) == 3 and len(MODELS) * len(ACTIONS) == MAX_POSTS
    assert 0 < ALLOWANCE <= MAX_TOTAL_USD
    assert OLLAMA_CLOUD_MODELS[MODELS[0]]["api_model"] == "gemma4:31b"
    assert OLLAMA_CLOUD_MODELS[MODELS[1]]["api_model"] == "gpt-oss:120b"
    assert all(len(json.dumps(_messages(a, []), ensure_ascii=False).encode()) < MAX_WIRE_BYTES for a in ACTIONS)
    raw = "```json\n" + json.dumps({"segments": [
        {"kind": "narration", "text": "Yuna cười qua điện thoại."},
        {"kind": "dialogue", "text": "Tập thôi!", "character_id": YUNA_ID,
         "profile_version_id": YUNA_VERSION},
    ]}, ensure_ascii=False) + "\n```"
    display, segments = parse_narrator_payload(raw, SELECTED)
    assert len(segments) == 2 and "Tập thôi" in display
    print("PUBLIC-SAFE HENN/YUNA DRY CONTRACT PASS: two models, 3 actions, no requests")

def main() -> int:
    if os.getenv("BANGTAN_MINIMAL_DRY") == "1":
        _contract()
        return 0
    if (os.getenv("BANGTAN_MINIMAL_APPROVAL") != APPROVAL or
            os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        print("LIVE DENIED: explicit first-attempt main-push approval required")
        return 2
    key = os.getenv("OLLAMA_API_KEY")
    if not key:
        print("LIVE DENIED: missing Ollama key")
        return 2
    post_count = 0
    try:
        _gate(key)
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            for model_label in MODELS:
                profile = OllamaCloudVerifier(http_client=client).verify(
                    key, model_label, OLLAMA_CLOUD_ENDPOINT
                )
                pinned = _persist_verified_profile(profile)
                expected_model = OLLAMA_CLOUD_MODELS[model_label]["api_model"]
                if pinned.get("model") != expected_model:
                    raise RuntimeError("Unexpected provider model identity")
                adapter = OllamaCloudAdapter(
                    key, OLLAMA_CLOUD_ENDPOINT, profile=pinned, http_client=client
                )
                prior = []
                for index, action in enumerate(ACTIONS, 1):
                    messages = _messages(action, prior)
                    byte_count = len(json.dumps(messages, ensure_ascii=False).encode())
                    if byte_count > MAX_WIRE_BYTES:
                        print(f"{expected_model} TURN {index}: input over limit; stop")
                        return 1
                    post_count += 1
                    events = list(adapter.generate_text({
                        "model": expected_model, "messages": messages,
                        "reserved_completion_tokens": MAX_OUTPUT,
                    }))
                    failure = next((x for x in events if isinstance(x, ProviderFailure)), None)
                    if failure:
                        print(f"{expected_model} TURN {index}: provider={failure.code}; stop no retry")
                        return 1
                    result = next((x for x in reversed(events) if isinstance(x, ProviderResult)), None)
                    if not result or result.finish_reason != "stop":
                        print(f"{expected_model} TURN {index}: no clean terminal response")
                        return 1
                    try:
                        rendered, segments = parse_narrator_payload(result.text, SELECTED)
                    except Exception as error:
                        print(f"{expected_model} TURN {index}: JSON/CAST_INVALID {type(error).__name__}")
                        return 1
                    warning = segments is None
                    agency = bool(re.search(r"\bHenn\b.{0,110}\b(?:nghĩ|quyết định|bước|đứng dậy|cười|mỉm cười|chợt nhớ|cảm thấy)", rendered, re.I))
                    excerpt = re.sub(r"[\x00-\x1f\x7f]", " ", rendered)[:1300]
                    usage = result.usage if isinstance(result.usage, dict) else {}
                    print(f"{expected_model} TURN {index}: format_warning={warning} "
                          f"agency_suspected={agency} segments={len(segments or [])} "
                          f"tokens={usage.get('prompt_tokens')}/{usage.get('completion_tokens')}")
                    print(f"{expected_model} TURN {index} STORY: {excerpt}")
                    if warning:
                        print(f"{expected_model} TURN {index}: unstructured output, stop")
                        return 1
                    prior.append((messages[-1]["content"], result.text))
        print(f"REAL OLLAMA MINI-AB DONE: posts_started={post_count}/6; NOT full canon")
        return 0
    except Exception as error:
        print(f"REAL OLLAMA MINI-AB STOP: {type(error).__name__}; posts_started={post_count}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
