"""Quality regression for actual synthetic Ollama turn 2.

The live output described an *unwritten* player action: saying "I will check"
is not equivalent to starting to search. Keep this sample public/synthetic;
no BANGTAN or personal source material is involved.
"""
from live_ollama_three_turn_trial import _quality_flags


def _segments(narration, dialogue=""):
    rows = [{"kind": "narration", "text": narration}]
    if dialogue:
        rows.append({"kind": "dialogue", "character_id": "npc-vy-synthetic",
                     "profile_version_id": "vy-profile-v1", "text": dialogue})
    return rows


def test_live_turn_two_invented_player_search_is_not_an_agency_pass():
    observed = (
        "Vy hơi nhíu mày, vẻ mặt lộ rõ sự thắc mắc khi thấy "
        "Lan bắt đầu tìm kiếm quanh quầy."
    )
    assert _quality_flags(_segments(observed)) == (True, False, False)


def test_npc_response_and_repetition_of_player_authored_action_not_false_positive():
    allowed = (
        "Vy nhìn chiếc hộp gỗ Lan mở sẵn trên quầy và hỏi: "
        "Tờ giấy xanh đã mất rồi à?"
    )
    assert _quality_flags(_segments(allowed)) == (False, False, False)


def test_absent_character_and_unknown_secret_still_flagged():
    absent = _segments("Bình bước vào hiệu sách và lên tiếng.")
    leaked = _segments("Vy quay về phía Lan.", "Người giao hàng đã tráo tờ giấy.")
    assert _quality_flags(absent) == (False, True, False)
    assert _quality_flags(leaked) == (False, False, True)
