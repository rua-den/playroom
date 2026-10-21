import unicodedata

import pytest

from playroom.roleplay_policy import GroundingViolation, NpcKnowledgeViolation, PlayerAgencyViolation, validate_grounded_precision, validate_npc_knowledge, validate_player_agency


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



def preview(*blocks, action="Ừ.", selected=None):
    return {
        "action": action,
        "blocks": list(blocks),
        "selected_characters": selected or [
            {"character_id": "yuna", "name": "Yuna", "present": True},
            {"character_id": "linh", "name": "Linh", "present": True},
        ],
    }


def restricted(text, scope="narrator_only", known_by=None):
    return {
        "id": "memory-secret",
        "type": "memory",
        "text": text,
        "knowledge_scope": scope,
        "known_by": known_by or [],
    }


def npc_dialogue(character_id, text):
    return [{"kind": "dialogue", "text": text, "character_id": character_id, "profile_version_id": f"{character_id}-v1"}]


def test_narrator_only_code_cannot_leak_into_npc_dialogue_even_with_unicode_variant():
    with pytest.raises(NpcKnowledgeViolation):
        validate_npc_knowledge(
            npc_dialogue("yuna", "B17 có lẽ là mã của một ngăn tủ."),
            preview(restricted(unicodedata.normalize("NFD", "Mã B-17 là ngăn tủ số 17."))),
        )


def test_known_by_fact_is_allowed_only_for_listed_npc():
    context = preview(restricted("Chiếc chìa khóa nằm dưới chậu cây.", "known_by", ["linh"]))
    validate_npc_knowledge(npc_dialogue("linh", "Chìa khóa nằm dưới chậu cây."), context)
    with pytest.raises(NpcKnowledgeViolation):
        validate_npc_knowledge(npc_dialogue("yuna", "Chìa khóa nằm dưới chậu cây."), context)


def test_narration_may_use_narrator_only_fact():
    validate_npc_knowledge(
        [{"kind": "narration", "text": "Mã B-17 nằm trên mặt sau tờ giấy."}],
        preview(restricted("Mã B-17 nằm trên mặt sau tờ giấy.")),
    )


def test_paraphrase_with_same_distinctive_entities_is_caught():
    with pytest.raises(NpcKnowledgeViolation):
        validate_npc_knowledge(
            npc_dialogue("yuna", "Người giao hàng đã đổi tờ giấy."),
            preview(restricted("Người giao hàng đã tráo tờ giấy.")),
        )


def test_unrelated_dialogue_with_only_one_common_word_is_not_blocked():
    validate_npc_knowledge(
        npc_dialogue("yuna", "Tớ để tờ giấy lên bàn nhé."),
        preview(restricted("Người giao hàng đã tráo tờ giấy.")),
    )


def test_player_can_disclose_restricted_fact_in_dialogue_to_present_npc():
    context = preview(
        restricted("Mã B-17 là mã ngăn tủ."),
        action="Yuna, B-17 là mã ngăn tủ.",
        selected=[{"character_id": "yuna", "name": "Yuna", "present": True}],
    )
    validate_npc_knowledge(npc_dialogue("yuna", "B17 là mã ngăn tủ à?"), context)


def test_player_thought_does_not_disclose_secret_to_npc():
    context = preview(
        restricted("Mã B-17 là mã ngăn tủ."),
        action="**Henn nghĩ B-17 là mã ngăn tủ.**",
        selected=[{"character_id": "yuna", "name": "Yuna", "present": True}],
    )
    with pytest.raises(NpcKnowledgeViolation):
        validate_npc_knowledge(npc_dialogue("yuna", "B17 là mã ngăn tủ."), context)



def test_rejects_new_exact_clock_time_not_present_in_context():
    context = preview(
        {"id": "scene", "type": "scene", "text": "Cuối buổi chiều, cả hai vẫn ở thư viện."},
        action="Mình đi tiếp nhé.",
    )
    with pytest.raises(GroundingViolation):
        validate_grounded_precision(
            [{"kind": "narration", "text": "Đồng hồ chỉ đúng 17:12 khi Yuna khép cửa."}],
            context,
        )


def test_allows_exact_clock_time_when_player_supplied_it():
    context = preview(action="**Henn nhìn đồng hồ: 17:12.**")
    validate_grounded_precision(
        [{"kind": "narration", "text": "17:12, tiếng chuông ngoài hành lang vang lên."}],
        context,
    )


def test_allows_exact_clock_time_when_context_already_contains_it():
    context = preview(
        {"id": "memory-time", "type": "memory", "text": "Tin nhắn được gửi lúc 17:19.", "knowledge_scope": "public", "known_by": []},
        action="Yuna, kiểm tra lại tin nhắn đi.",
    )
    validate_grounded_precision(
        npc_dialogue("yuna", "Tin nhắn lúc 17:19 đúng không?"),
        context,
    )


def test_rejects_unicode_fullwidth_clock_variant_when_not_grounded():
    context = preview(action="Tiếp tục.")
    with pytest.raises(GroundingViolation):
        validate_grounded_precision(
            [{"kind": "narration", "text": "Cuộc gọi bắt đầu lúc ６：００."}],
            context,
        )


def test_does_not_treat_chapter_number_or_score_as_clock_time():
    context = preview(action="Chương 157 bắt đầu.")
    validate_grounded_precision(
        [{"kind": "narration", "text": "Chương 157 tiếp tục với tỉ số 21-19."}],
        context,
    )
