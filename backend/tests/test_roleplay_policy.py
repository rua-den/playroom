import unicodedata

import pytest

from playroom.roleplay_policy import PlayerAgencyViolation, validate_player_agency


def persona(name="Henn", aliases=None):
    return {"name": name, "aliases": aliases or []}


def narration(text):
    return [{"kind": "narration", "text": text}]


def test_rejects_new_physical_action_not_authored_by_player():
    with pytest.raises(PlayerAgencyViolation):
        validate_player_agency(
            "Để tớ xem thử ngăn kéo nhé.",
            narration("Lan mở ngăn kéo, tìm thấy tờ giấy rồi nhặt nó lên."),
            persona("Lan"),
        )


def test_allows_same_concrete_action_when_player_authored_it():
    validate_player_agency(
        "**Lan mở ngăn kéo và nhặt tờ giấy lên.**",
        narration("Lan mở ngăn kéo rồi nhặt tờ giấy lên."),
        persona("Lan"),
    )


def test_rejects_new_emotion_decision_or_gesture_for_henn():
    for text in [
        "Henn gật đầu.",
        "Henn mỉm cười.",
        "Henn thở dài.",
        "Henn quyết định đi theo Yuna.",
        "Henn cảm thấy nhẹ nhõm.",
    ]:
        with pytest.raises(PlayerAgencyViolation):
            validate_player_agency("Ừ, tớ nghe đây.", narration(text), persona())


def test_player_authored_henn_gesture_is_allowed():
    validate_player_agency(
        "**Henn gật đầu** Ừ.",
        narration("Henn gật đầu."),
        persona(),
    )


def test_npc_sentence_with_henn_as_object_is_not_misattributed():
    validate_player_agency(
        "Ừ.",
        narration("Yuna nhìn Henn rồi mỉm cười."),
        persona(),
    )


def test_npc_dialogue_can_mention_player_without_becoming_player_action():
    validate_player_agency(
        "Ừ.",
        [{"kind": "dialogue", "text": "Henn gật đầu đi.", "character_id": "yuna", "profile_version_id": "yuna-v1"}],
        persona(),
    )


def test_unicode_nfd_player_action_still_matches_authorized_action():
    action = unicodedata.normalize("NFD", "**Henn gật đầu**")
    validate_player_agency(action, narration("Henn gật đầu."), persona())
