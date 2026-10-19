"""Public MINIMAL Henn/Yuna 3-action Ollama A/B test.

This intentionally does NOT include the private BANGTAN 001-156 canon, any
personal story snippets, conversation history, or file attachments. The private
full-canon 87KB request is only built/tested locally, not submitted to CI.

This verifies real Ollama text on a minimal story fixture. It cannot measure
full-canon recall or Playroom campaign persistence.
"""
from __future__ import annotations

import json
import os
import re
import sys
from decimal import Decimal

import httpx2 as httpx

from playroom.model_profiles import OLLAMA_CLOUD_ENDPOINT, OLLAMA_CLOUD_MODELS, OllamaCloudVerifier
from playroom.provider import OllamaCloudAdapter, ProviderFailure, ProviderResult
from playroom.roleplay_segments import parse_narrator_payload
from live_ollama_gemma4_smoke import _persist_verified_profile
from live_ollama_long_story_trial import _credit

APPROVAL = "OWNER_HENN_YUNA_PUBLIC_MINIMAL_6_COMPLETIONS_20261020"
MODELS = ("gemma4:31b-cloud", "gpt-oss:120b-cloud")
CAST = {"npc-yuna-test-public": "yuna-profile-test-v1"}
MAX_OUTPUT = 1400
MAX_WIRE_BYTES = 16000
TURNS = 3
TOTAL_CAP = Decimal("0.025")
ACTIONS = [
    '*Henn vẫn ở phòng riêng, chủ động gọi điện cho Yuna. Khi cuộc gọi kết nối, Henn nói:* "Yuna, mai ra sân tập đôi sớm chút nhé? Tớ muốn tập lại mấy pha bị điều cầu hôm trước."',
    '*Henn bật loa ngoài, đặt sổ ghi chép buổi tập lên bàn và cầm bút.* "Ừ, cậu nói thẳng đi: đôi mình cần sửa điều gì nhất?"',
    '*Henn khoanh tròn một mục trong sổ luyện tập.* "Tớ chọn tập đổi vị trí và cứu cầu cuối sân trước. Vậy buổi tập tới hai đứa thử cách đó nhé?"',
]
SYSTEM = (
    "Đây là bài thử nghiệm MINIMAL BANGTAN-inspired nhưng KHÔNG có canon gốc. "
    "Bối cảnh thanh xuân học đường Việt Nam. Henn là nữ sinh tóc bạch kim, "
    "vận động viên thể thao; Yuna là bạn thân, chơi cầu lông, năng động, hài hước "
    "và có chiến thuật. Lúc này Henn ở một mình trong phòng ngủ. "
    "Yuna chỉ xuất hiện qua ĐIỆN THOẠI, tuyệt đối không xuất hiện vật lý trong phòng. "
    "Không đưa NPC khác vào đối thoại, không ép tình cảm, không tự suy đoán về các chương trước. "
    "Người chơi được quyền viết các action Henn cụ thể bên dưới CHỈ trong bài test này; "
    "tuyệt đối không tự viết tiếp suy nghĩ, cảm xúc, lời nói, hành động hoặc quyết định của Henn. "
    "Ý định của Henn không đồng nghĩa Henn đã thực hiện. "
    "Hãy miêu tả Yuna phản ứng sinh động, dí dỏm, có tiến triển nội dung chiến thuật đôi nữ; "
    "ngôn ngữ tự nhiên, không sáo rỗng, không lặp cảnh ánh đèn dài dòng. "
    "Mỗi lượt khoảng 130-240 từ tiếng Việt, ngắn cũng được nếu hợp cảnh. "
    "Phản hồi chỉ là một JSON object có segments array; mỗi narration chỉ có kind/text, "
    "mỗi dialogue của Yuna phải dùng character_id=npc-yuna-test-public và "
    "profile_version_id=yuna-profile-test-v1. Không xuất lời thoại của Henn. "
    "Không Markdown, code fences, lời giải thích hoặc lựa chọn A/B."
)


def reserve(model_label: str) -> Decimal:
    model = OLLAMA_CLOUD_MODELS[model_label]
    return (Decimal(model["prompt_price"]) * MAX_WIRE_BYTES
            + Decimal(model["completion_price"]) * MAX_OUTPUT)


def safe_excerpt(text: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", text)[:1800]


def _gate_contract() -> None:
    assert len(ACTIONS) == TURNS
    assert sum((reserve(m) * TURNS for m in MODELS), Decimal(0)) < TOTAL_CAP
    for model in MODELS:
        assert model in OLLAMA_CLOUD_MODELS
        assert OLLAMA_CLOUD_MODELS[model]["api_model"] in {"gemma4:31b", "gpt-oss:120b"}
    # The exact fenced Gemma JSON format is accepted by production's parser.
    raw = '```json\n{"segments":[{"kind":"narration","text":"Yuna cười."},' + (
        '{"kind":"dialogue","text":"Mai tập nhé!",'
        '"character_id":"npc-yuna-test-public","profile_version_id":"yuna-profile-test-v1"}]'
        '}\n```'
    )
    display, segments = parse_narrator_payload(raw, CAST)
    assert len(segments) == 2 and "Mai tập nhé!" in display
    print("HENN/YUNA MINIMAL OFFLINE PASS: 3 fixed actions; 2 pinned models; no inference")


def _agency_warnings(text: str, action: str) -> list[str]:
    # Heuristic reviewer hints only; not an authoritative semantic detector.
    patterns = {
        "new_Henn_thought": r"Henn[^.!?\n]{0,100}(?:nghĩ thầm|thầm nghĩ|chợt nhận ra|tự nhủ)",
        "new_Henn_unrelated_action": r"Henn[^.!?\n]{0,100}(?:đứng dậy|bước ra|rời phòng|ngủ thiếp)",
        "invented_Henn_emotion_or_decision": (
            r"\bHenn\s+(?:cảm thấy|nở nụ cười|thở dài|gật đầu|lắc bút|"
            r"tưởng tượng|mỉm cười|quyết định|chợt nhớ|tự nhủ)\b"
        ),
        "Yuna_physical_teleport": r"Yuna[^.!?\n]{0,120}(?:bước vào phòng Henn|ngồi xuống cạnh Henn|đứng sau lưng Henn)",
    }
    return [name for name, pat in patterns.items()
            if re.search(pat, text, re.I) and not re.search(pat, action, re.I)]


def main() -> int:
    if os.getenv("HENN_YUNA_DRY_RUN") == "1":
        _gate_contract()
        return 0
    if (os.getenv("HENN_YUNA_LIVE_APPROVAL") != APPROVAL
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        print("DENIED: owner approval / first attempt required")
        return 2
    key = os.getenv("OLLAMA_API_KEY")
    if not key:
        print("DENIED: Ollama key is unavailable")
        return 2
    dispatched, completed, violations = 0, 0, 0
    try:
        total = sum((reserve(m) * TURNS for m in MODELS), Decimal(0))
        _credit(key, total)
        with httpx.Client(timeout=httpx.Timeout(120, connect=15)) as client:
            for model_label in MODELS:
                model_id = OLLAMA_CLOUD_MODELS[model_label]["api_model"]
                profile = OllamaCloudVerifier(http_client=client).verify(
                    key, model_label, OLLAMA_CLOUD_ENDPOINT
                )
                if profile["model"] != model_id:
                    raise RuntimeError("Unexpected verified model")
                adapter = OllamaCloudAdapter(
                    key, OLLAMA_CLOUD_ENDPOINT,
                    profile=_persist_verified_profile(profile), http_client=client
                )
                messages = [{"role": "system", "content": SYSTEM}]
                for index, action in enumerate(ACTIONS, 1):
                    _credit(key, reserve(model_label))
                    messages.append({"role": "user", "content": json.dumps({
                        "test": "public_minimal_only_not_full_canon",
                        "turn": index, "player_action": action,
                        "scene": "Henn's bedroom, Yuna connected by phone only",
                        "selected_characters": [
                            {"character_id": list(CAST)[0],
                             "profile_version_id": list(CAST.values())[0],
                             "name": "Yuna", "present_via": "phone"}
                        ],
                    }, ensure_ascii=False)})
                    size = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
                    if size > MAX_WIRE_BYTES:
                        print(f"STOP {model_id} round={index}: input size guard")
                        return 1
                    dispatched += 1
                    events = list(adapter.generate_text({
                        "model": model_id, "messages": messages,
                        "reserved_completion_tokens": MAX_OUTPUT,
                    }))
                    failure = next((x for x in events if isinstance(x, ProviderFailure)), None)
                    if failure:
                        print(f"STOP {model_id} round={index}: provider={failure.code}; no retry")
                        break
                    result = next((x for x in reversed(events) if isinstance(x, ProviderResult)), None)
                    if result is None or result.finish_reason != "stop":
                        print(f"STOP {model_id} round={index}: no terminal; no retry")
                        break
                    try:
                        output, segments = parse_narrator_payload(result.text, CAST)
                    except Exception as exc:
                        print(f"FORMAT WARNING {model_id} round={index}: {type(exc).__name__}")
                        output, segments = result.text, None
                    warnings = _agency_warnings(output, action)
                    if warnings:
                        violations += 1
                    usage = result.usage if isinstance(result.usage, dict) else {}
                    print(f"MODEL={model_id} ROUND={index} format={'structured' if segments else 'plain_or_invalid'} "
                          f"segments={len(segments) if segments else 0} "
                          f"agency_hints={','.join(warnings) if warnings else 'none'} "
                          f"tokens={usage.get('prompt_tokens')}/{usage.get('completion_tokens')}")
                    print(f"MODEL={model_id} ROUND={index} PUBLIC MINIMAL NARRATION: {safe_excerpt(output)}")
                    completed += 1
                    messages.append({"role": "assistant", "content": result.text})
        print(f"COMPARISON RESULT: completed={completed}/6 dispatched={dispatched} "
              f"agency_heuristic_affected_rounds={violations} "
              "mode=public_minimal_not_full_private_canon")
        return 0 if completed == 6 else 1
    except Exception as exc:
        print(f"COMPARISON STOP: {type(exc).__name__} dispatched={dispatched} completed={completed}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
