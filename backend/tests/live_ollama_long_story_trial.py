"""One-shot synthetic long-story quality probe against Ollama Cloud gpt-oss:120b.

No private BANGTAN data. Emulates a reviewed chapter-156 backstory with a
fictional school, 24 fresh player-controlled rounds, 4 NPCs and 6 scenes.
Uses the real Playroom Ollama SSE adapter, but NOT the full Playroom app or DB.
Heuristic warnings are observations, not automatic proof of story quality.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

import httpx2 as httpx

from playroom.model_profiles import (
    OLLAMA_CLOUD_API_MODEL, OLLAMA_CLOUD_MODEL, OLLAMA_CLOUD_MODELS,
    OLLAMA_FREE_CLOUD_MODEL, OLLAMA_CLOUD_ENDPOINT, OllamaCloudVerifier,
)
from playroom.provider import OllamaCloudAdapter, ProviderFailure, ProviderResult
from playroom.roleplay_segments import parse_narrator_payload
from live_ollama_gemma4_smoke import _persist_verified_profile
from live_ollama_three_turn_trial import _quality_flags

# Keep the previously accepted gpt-oss one-shot workflow unchanged.
# A separate first-attempt workflow enables a fair, SAME-FIXTURE comparison
# with strict allowlisted model labels; neither mode can use arbitrary endpoints.
COMPARISON_MODE = os.getenv("LONG_STORY_COMPARISON") == "1"
MODEL_LABEL = (
    os.getenv("LONG_STORY_MODEL_LABEL", "") if COMPARISON_MODE else OLLAMA_CLOUD_MODEL
)
if MODEL_LABEL not in {OLLAMA_CLOUD_MODEL, OLLAMA_FREE_CLOUD_MODEL}:
    raise RuntimeError("Only the two pinned Ollama models can be compared")
MODEL_SPEC = OLLAMA_CLOUD_MODELS[MODEL_LABEL]
APPROVAL = (
    "OWNER_GEMMA_GPTOSS_SAME_24_2026_10_20"
    if COMPARISON_MODE else "OWNER_LONG_STORY_24_TURNS_2026_10_19"
)
MODEL = MODEL_SPEC["api_model"]
MAX_TURNS = 24
MAX_OUTPUT_TOKENS = 1600
MAX_WIRE_BYTES = 16000
MAX_TOTAL_USD = Decimal("0.085")
PROMPT_RATE = Decimal(MODEL_SPEC["prompt_price"])
OUTPUT_RATE = Decimal(MODEL_SPEC["completion_price"])
RESERVE_PER_TURN = PROMPT_RATE * MAX_WIRE_BYTES + OUTPUT_RATE * MAX_OUTPUT_TOKENS
TOTAL_RESERVE = RESERVE_PER_TURN * MAX_TURNS
CAST = {
    "npc-vy-synthetic": "vy-v1",
    "npc-binh-synthetic": "binh-v1",
    "npc-mai-synthetic": "mai-v1",
    "npc-khoa-synthetic": "khoa-v1",
}
NAMES = {
    "Vy": "npc-vy-synthetic", "Bình": "npc-binh-synthetic",
    "Mai": "npc-mai-synthetic", "Khoa": "npc-khoa-synthetic",
}
HISTORY_156 = (
    "Synthetic chapter-156 checkpoint only (not a real transcript): "
    "Lan is the sole player-controlled persona. "
    "The school Thuỷ Tinh won a badminton friendship match; no romance is established. "
    "Vy is an energetic, quick-witted badminton captain and Lan's close friend. "
    "Bình is a meticulous student photographer who hates being blamed without proof. "
    "Mai is a composed class representative who values consent and clear evidence. "
    "Khoa is a witty equipment monitor; he jokes when nervous but is loyal. "
    "A blue envelope with event photos vanished at 18:00; no one has verified who moved it. "
    "A silver bookmark bearing a tiny star is the only public clue. "
    "The wall clock in the library runs seven minutes slow (Lan learned this earlier). "
    "A warm-up whistle belongs to Khoa, not Bình. "
    "Public history spans 156 hypothetical chapter summaries, but there are NO replayable "
    "chat turns; NEVER invent missing chapters. Characters know only stated facts. "
    "The player chooses every Lan action, thought, dialogue, relationship and emotion."
)
PRIVATE_SECRET = (
    "Narrator-only: a storage clerk placed the real envelope inside locker B-17. "
    "No NPC knows this unless the player discovers the evidence and tells them. "
    "Do not casually expose the answer or let an NPC guess it as certainty."
)
SYSTEM = (
    "You are a Vietnamese interactive youth-school story narrator, balancing gentle humor, "
    "scene progression and meaningful NPC reactions. Use the chapter-156 checkpoint below. "
    "The player alone controls Lan: never invent Lan's motions, speech, thoughts, emotion, "
    "relationship decisions or completed actions. A stated intention is NOT an executed action. "
    "Never force romance, A/B menus or game mechanics. NPC voices must be distinct, no extra "
    "speaker or knowledge. Narrate NPCs and setting; never narrate Lan beyond the EXACT "
    "player-authored action. Do not add Lan moving, opening objects, searching, smiling, sighing, "
    "thinking or agreeing unless the player explicitly wrote it. An intention is not an action. "
    "Until chapter 176, the locker code B-17 must not appear in either narration or dialogue; "
    "even the narrator must preserve the mystery. "
    "Respond naturally to the LAST player action with a meaningful "
    "change or question. Aim for 140-260 Vietnamese words per reply where appropriate. "
    "The allowed present NPCs are supplied PER TURN. Their exact IDs and profile versions must be "
    "copied from selected_characters. Only those NPCs may speak; others cannot walk into the "
    "scene unless the player's action explicitly introduces them. "
    "Reply ONLY one JSON object with a segments array: "
    "{\"segments\":[{\"kind\":\"narration\",\"text\":\"...\"},"
    "{\"kind\":\"dialogue\",\"text\":\"...\","
    "\"character_id\":\"selected npc id\",\"profile_version_id\":\"selected version\"}]}. "
    "No analysis, code fences, additional fields or explanations. "
    + HISTORY_156 + " " + PRIVATE_SECRET
)

# Pre-authored PLAYER actions. NPCs change only when the PLAYER travels to a new scene.
# This is entirely fictional, not derived from the user's private campaign.
SCENES = (
    ("Library", ("Vy",), (
        "*Lan mở chiếc hộp giấy trên quầy.* \"Vy, phong bì xanh lúc chiều đâu rồi?\"",
        "*Lan vẫn đứng yên.* \"Để tớ xem thử ngăn kéo nhé.\"",
        "*Lan chỉ vào đồng hồ trên tường.* \"Nhớ là nó chạy chậm bảy phút đấy.\"",
        "*Lan đặt dấu trang bạc lên bàn.* \"Có hình ngôi sao nhỏ, cậu nhận ra không?\"",
    )),
    ("Classroom", ("Mai",), (
        "*Lan bước vào lớp, tìm gặp Mai.* \"Tớ muốn kiểm tra danh sách người nhận ảnh.\"",
        "*Lan đưa Mai tờ đăng ký.* \"Đừng ghi tên ai vào diện nghi vấn khi chưa có chứng cứ nhé.\"",
        "*Lan ngồi xuống ghế gần cửa sổ.* \"Cậu nhớ hôm thi đấu ai giữ chìa khóa kho?\"",
        "*Lan mỉm cười trêu.* \"Nếu có giải cho người giữ sổ ngăn nắp thì cậu vô địch rồi.\"",
    )),
    ("Gym", ("Khoa",), (
        "*Lan đến nhà thi đấu gặp Khoa.* \"Có ai thấy chiếc còi khởi động của cậu không?\"",
        "*Lan đứng cạnh vạch sân.* \"Tớ không muốn đổ oan cho Bình.\"",
        "*Lan đưa Khoa chiếc dấu trang bạc.* \"Ngôi sao này có quen không?\"",
        "*Lan chỉ về cửa kho nhưng không mở.* \"Cậu có thể xem giúp lịch trực tối qua không?\"",
    )),
    ("Photo room", ("Bình",), (
        "*Lan gõ cửa phòng ảnh, đợi Bình mời vào.* \"Tớ đến để nghe phía cậu trước.\"",
        "*Lan đưa bản chụp lịch thi đấu.* \"Khung giờ này có người ghi nhầm không?\"",
        "*Lan nhìn vào máy ảnh trên bàn.* \"Nếu cần, tớ có thể cùng cậu kiểm tra ảnh gốc.\"",
        "*Lan lật mặt sau chiếc dấu trang.* \"Ở đây có dấu mực, cậu nghĩ nó từ đâu?\"",
    )),
    ("Hallway", ("Vy", "Mai"), (
        "*Lan chủ động gọi Vy và Mai ra hành lang.* \"Mình so lại ba đầu mối nhé.\"",
        "*Lan chỉ cho cả hai ghi chú đồng hồ chạy chậm bảy phút.* \"Đừng quên điều này.\"",
        "*Lan ngừng ở ngã rẽ.* \"Tớ chưa biết ai đã chuyển phong bì. Hai cậu đoán gì?\"",
        "*Lan nhặt một tờ giấy vừa rơi xuống ngay trước mặt.* \"Trên giấy viết B-17.\"",
    )),
    ("Courtyard next morning", ("Bình", "Khoa", "Vy"), (
        "*Lan bước ra sân trường sáng hôm sau, gặp Bình, Khoa và Vy.* \"Tớ tìm thấy ký hiệu B-17.\"",
        "*Lan hỏi cả ba.* \"Có ai nhớ chiếc dấu trang bạc có ngôi sao không?\"",
        "*Lan nhắc lại.* \"Đồng hồ thư viện chậm bảy phút, vậy mốc 18:00 có đáng tin không?\"",
        "*Lan giơ tờ giấy B-17 lên nhưng chưa mở bất kỳ tủ nào.* \"Theo mọi người, bước kế tiếp nên là gì?\"",
    )),
)
STEPS = [
    {"scene": scene, "present": cast, "action": action, "chapter": 157 + i}
    for i, (scene, cast, action) in enumerate(
        (scene, cast, action)
        for scene, cast, actions in SCENES
        for action in actions
    )
]
# The synthetic event ledger contains only PLAYER-authored actions.
PLAYER_LEDGER = {
    3: "Lan told Vy the library clock runs seven minutes slow.",
    4: "Lan showed Vy a silver bookmark with a small star.",
    10: "Lan explicitly said she does not want to blame Bình without evidence.",
    18: "Lan showed Mai and Vy the seven-minute clock discrepancy.",
    20: "Lan picked up a note with the marking B-17; no locker was opened.",
}


def _credit(key: str, required: Decimal) -> None:
    if required <= 0 or not required.is_finite() or required > MAX_TOTAL_USD:
        raise RuntimeError("Trial estimate exceeded the approved allowance")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    req = urllib.request.Request(
        "https://ollama.com/api/balance",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=18) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Read-only credit check HTTP {exc.code}; no completion sent") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise RuntimeError("Read-only credit check unavailable; no completion sent") from None
    try:
        included = Decimal(str(payload["included"]["balance_usd"]))
        purchased = Decimal(str(payload["purchased"]["balance_usd"]))
    except (TypeError, ValueError, KeyError, InvalidOperation):
        raise RuntimeError("Credit source is unavailable; no provider call") from None
    if not all(x.is_finite() and x >= 0 for x in (included, purchased)):
        raise RuntimeError("Credit buckets are invalid")
    if included < required or purchased != 0:
        raise RuntimeError("Insufficient included credit or purchased-credit bucket not zero")
    print("CREDIT GATE: sufficient included balance; purchased zero (snapshot)")


def _messages(index: int, completed: list[tuple[str, str]]) -> list[dict]:
    # A bounded sliding raw context plus a durable structured PLAYER event ledger;
    # unlike a real Playroom campaign this runner does NOT test DB memory selection.
    step = STEPS[index]
    memo = [PLAYER_LEDGER[k] for k in sorted(PLAYER_LEDGER) if k <= index + 1]
    selected = [
        {"name": name, "character_id": NAMES[name],
         "profile_version_id": CAST[NAMES[name]], "present": True}
        for name in step["present"]
    ]
    recent = completed[-6:]
    messages = [{"role": "system", "content": SYSTEM}]
    for action, result in recent:
        messages.append({"role": "user", "content": action})
        messages.append({"role": "assistant", "content": result})
    context = {
        "scene": step["scene"],
        "chapter_number": step["chapter"],
        "player_action": step["action"],
        "selected_characters": selected,
        "player_event_ledger": memo,
        "no_invented_chapters": True,
    }
    messages.append({"role": "user", "content": json.dumps(context, ensure_ascii=False)})
    return messages


def _pack_messages(index: int, completed: list[tuple[str, str]]) -> tuple[list[dict], int, int]:
    """Retain canon and latest player ledger; trim old raw turns first."""
    count = min(6, len(completed))
    while True:
        history = completed[-count:] if count else []
        messages = _messages(index, history)
        wire_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        if wire_bytes <= MAX_WIRE_BYTES or count == 0:
            return messages, wire_bytes, count
        count -= 1


def _dry() -> None:
    assert len(STEPS) == MAX_TURNS == 24
    assert len(SCENES) == 6
    assert [s["chapter"] for s in STEPS] == list(range(157, 181))
    assert TOTAL_RESERVE < MAX_TOTAL_USD
    assert OLLAMA_CLOUD_MODELS[MODEL_LABEL]["api_model"] == MODEL
    assert all("Lan" in step["action"] or "Tớ" in step["action"] for step in STEPS)
    assert len(json.dumps(_messages(0, []), ensure_ascii=False).encode()) <= MAX_WIRE_BYTES
    synthetic_long_turns = [
        ("*Lan nhìn quanh.*", json.dumps({"segments": [
            {"kind": "narration", "text": "Đây là dữ liệu giả lập." * 220}
        ]}, ensure_ascii=False))
        for _ in range(6)
    ]
    packed, length, count = _pack_messages(21, synthetic_long_turns)
    assert length <= MAX_WIRE_BYTES and count < 6
    assert packed[0]["role"] == "system"
    assert "player_event_ledger" in packed[-1]["content"]
    assert _quality_flags([{"kind": "narration", "text": "Lan bắt đầu tìm kiếm quanh quầy."}])[0]
    print(f"LONG STORY OFFLINE CONTRACT: PASS; model={MODEL} 24 actions, 6 scenes, 0 provider calls")


def main() -> int:
    if os.getenv("LONG_STORY_DRY_RUN") == "1":
        _dry()
        return 0
    if (os.getenv("LONG_STORY_APPROVAL") != APPROVAL
            or os.getenv("GITHUB_RUN_ATTEMPT") != "1"):
        print("DENIED: only approved first run on main may dispatch")
        return 2
    key = os.getenv("OLLAMA_API_KEY")
    if not key:
        print("DENIED: missing provider secret")
        return 2
    completed: list[tuple[str, str]] = []
    alerts: list[tuple[int, str]] = []
    posts = 0
    stage = "preflight"
    try:
        _credit(key, TOTAL_RESERVE)
        stage = "model_verification"
        with httpx.Client(timeout=httpx.Timeout(150, connect=15)) as http_client:
            profile = OllamaCloudVerifier(http_client=http_client).verify(
                key, MODEL_LABEL, OLLAMA_CLOUD_ENDPOINT
            )
            if profile["model"] != MODEL:
                raise RuntimeError("Unexpected model ID")
            pinned = _persist_verified_profile(profile)
            adapter = OllamaCloudAdapter(
                key, OLLAMA_CLOUD_ENDPOINT, profile=pinned, http_client=http_client
            )
            for i, step in enumerate(STEPS):
                stage = f"chapter_{step['chapter']}_preflight"
                # The initial gate reserves the full worst-case allowance. Recheck
                # every 6 turns instead of hammering the balance endpoint 24 times.
                # Never advance if a periodic read-only check fails.
                if i > 0 and i % 6 == 0:
                    _credit(key, RESERVE_PER_TURN * (MAX_TURNS - i))
                messages, wire_bytes, packed_turns = _pack_messages(i, completed)
                if packed_turns < min(6, len(completed)):
                    print(f"CHAPTER {step['chapter']}: context packed to {packed_turns} recent turns, "
                          f"wire_bytes={wire_bytes}; canon and player ledger retained")
                if wire_bytes > MAX_WIRE_BYTES:
                    print(f"CHAPTER {step['chapter']}: required context too large ({wire_bytes}); no POST")
                    break
                stage = f"chapter_{step['chapter']}_dispatch"
                posts += 1
                events = list(adapter.generate_text({
                    "model": MODEL, "messages": messages,
                    "reserved_completion_tokens": MAX_OUTPUT_TOKENS,
                }))
                failures = [x for x in events if isinstance(x, ProviderFailure)]
                if failures:
                    print(f"CHAPTER {step['chapter']}: PROVIDER_FAILURE {failures[0].code}; no retry")
                    break
                result = next((x for x in reversed(events) if isinstance(x, ProviderResult)), None)
                if not result or result.finish_reason != "stop":
                    print(f"CHAPTER {step['chapter']}: incomplete provider result; no retry")
                    break
                selected = {NAMES[n]: CAST[NAMES[n]] for n in step["present"]}
                try:
                    narrative, segments = parse_narrator_payload(result.text, selected)
                except Exception as exc:
                    print(f"CHAPTER {step['chapter']}: JSON/CAST_INVALID {type(exc).__name__}; no retry")
                    break
                agency = _quality_flags(segments)[0]
                forbidden = "B-17" in narrative and step["chapter"] < 176
                if agency:
                    alerts.append((step["chapter"], "agency_suspected"))
                if forbidden:
                    alerts.append((step["chapter"], "secret_knowledge_suspected"))
                char_count = len(narrative)
                usage = result.usage if isinstance(result.usage, dict) else {}
                print(f"CHAPTER {step['chapter']} [{step['scene']}]: "
                      f"chars={char_count} segments={len(segments)} "
                      f"agency_warning={agency} knowledge_warning={forbidden} "
                      f"tokens={usage.get('prompt_tokens')}/{usage.get('completion_tokens')}")
                safe = re.sub(r"[\x00-\x1f\x7f]", " ", narrative)[:850]
                print(f"CHAPTER {step['chapter']} EXCERPT: {safe}")
                completed.append((step["action"], result.text))
                # Give the provider a small inter-request gap; no completion retries.
                if i + 1 < MAX_TURNS:
                    time.sleep(1)
            print(f"LONG STORY RESULT: model={MODEL} turns={len(completed)}/{MAX_TURNS} posts_started={posts} "
                  f"heuristic_warnings={len(alerts)}; reviewer must inspect prose")
            for chapter, code in alerts:
                print(f"QUALITY FLAG: chapter={chapter} code={code}")
            print("Synthetic adapter-only trial, NOT Playroom DB import/persistence or a direct GPT benchmark")
            return 0 if len(completed) == MAX_TURNS else 1
    except Exception as exc:
        # Do not dump exceptions or frames containing private prompt/credential.
        # A bounded list of filenames/functions/lines gives enough diagnostic
        # signal without logging model request bodies or authentication headers.
        safe_frames = [
            f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
            for frame in traceback.extract_tb(exc.__traceback__)
            if frame.filename.endswith((
                "live_ollama_long_story_trial.py", "provider.py",
                "provider_wire.py", "model_profiles.py",
            ))
        ][-5:]
        print(f"LONG STORY STOP: {stage} exception={type(exc).__name__} "
              f"posts_started={posts} trace_functions={'|'.join(safe_frames)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
