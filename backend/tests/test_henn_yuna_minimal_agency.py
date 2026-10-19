"""Regression of actual public-minimal Ollama Henn/Yuna agency output.

These strings are from synthetic public run #39308537959, NOT from the
private BANGTAN 001-156 file. An automated regex warning is only a hint.
"""
from live_henn_yuna_minimal_ollama_comparison import ACTIONS, _agency_warnings


def test_gptoss_inserted_henn_emotion_round_one_is_not_silently_clean():
    output = "Cuộc trò chuyện tiếp tục, khiến Henn cảm thấy chuẩn bị cho buổi tập đã đầy hứng khởi."
    assert "invented_Henn_emotion_or_decision" in _agency_warnings(output, ACTIONS[0])


def test_gptoss_inserted_henn_smile_and_extra_note_round_two_are_flagged():
    output = "Yuna cười khúc khích, khiến Henn nở nụ cười rạng rỡ. Henn lắc bút, chuẩn bị ghi lại mọi chi tiết."
    assert "invented_Henn_emotion_or_decision" in _agency_warnings(output, ACTIONS[1])


def test_gptoss_inserted_henn_sigh_and_agreement_round_three_are_flagged():
    output = "Henn thở dài, mắt sáng lên khi tưởng tượng ra bài tập. Henn gật đầu, bút lập tức ghi lại mọi chi tiết."
    assert "invented_Henn_emotion_or_decision" in _agency_warnings(output, ACTIONS[2])


def test_player_authored_action_does_not_trigger_new_emotion_warning():
    assert "invented_Henn_emotion_or_decision" not in _agency_warnings(ACTIONS[1], ACTIONS[1])
    assert "invented_Henn_emotion_or_decision" not in _agency_warnings(ACTIONS[2], ACTIONS[2])


def test_npc_only_speech_does_not_trigger_henn_agency_warning():
    output = "Yuna cười giòn ở đầu dây rồi giải thích cách đổi vị trí."
    assert _agency_warnings(output, ACTIONS[0]) == []
