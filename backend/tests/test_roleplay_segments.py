import pytest

from playroom.domain import ValidationError
from playroom.roleplay_segments import parse_player_input, parse_narrator_payload, validate_narrator_segments


def test_parse_player_input_preserves_order_and_distinguishes_actions():
    assert parse_player_input("Xin chào **vẫy tay** rồi **nghĩ thầm**.") == [
        {"kind": "dialogue", "text": "Xin chào "},
        {"kind": "action", "text": "vẫy tay"},
        {"kind": "dialogue", "text": " rồi "},
        {"kind": "action", "text": "nghĩ thầm"},
        {"kind": "dialogue", "text": "."},
    ]


def test_parse_player_input_supports_multiline_and_empty_action():
    assert parse_player_input("**\nđứng lại\n**\n****") == [
        {"kind": "action", "text": "\nđứng lại\n"},
        {"kind": "dialogue", "text": "\n"},
        {"kind": "action", "text": ""},
    ]


def test_unclosed_action_delimiter_remains_plain_dialogue():
    assert parse_player_input("Nói **chưa xong") == [{"kind": "dialogue", "text": "Nói **chưa xong"}]


def test_parse_player_input_supports_single_star_mixed_prose_and_dialogue():
    assert parse_player_input("Bước vào *nhìn quanh* rồi nói: Xin chào.") == [
        {"kind": "dialogue", "text": "Bước vào "},
        {"kind": "action", "text": "nhìn quanh"},
        {"kind": "dialogue", "text": " rồi nói: Xin chào."},
    ]


def test_single_star_escaped_empty_and_unmatched_are_safe_and_double_star_stays_intact():
    assert parse_player_input(r"\*không phải hành động\*") == [{"kind": "dialogue", "text": r"\*không phải hành động\*"}]
    assert parse_player_input("Nói * rồi tiếp tục") == [{"kind": "dialogue", "text": "Nói * rồi tiếp tục"}]
    assert parse_player_input("**đậm hoặc hành động** và *làm*") == [
        {"kind": "action", "text": "đậm hoặc hành động"},
        {"kind": "dialogue", "text": " và "},
        {"kind": "action", "text": "làm"},
    ]


def test_validate_narrator_segments_requires_selected_stable_character_version():
    selected = {"char-linh": "profile-linh-v3"}
    segments = [
        {"kind": "narration", "text": "Mưa rơi."},
        {"kind": "dialogue", "text": "Đừng đi.", "character_id": "char-linh", "profile_version_id": "profile-linh-v3"},
    ]
    assert validate_narrator_segments(segments, selected) == segments


@pytest.mark.parametrize(
    "segments",
    [
        [{"kind": "dialogue", "text": "Ai đó.", "character_id": "invented", "profile_version_id": "profile-linh-v3"}],
        [{"kind": "dialogue", "text": "Sai bản.", "character_id": "char-linh", "profile_version_id": "profile-linh-v2"}],
        [{"kind": "dialogue", "text": "Thiếu người nói."}],
        [{"kind": "banter", "text": "Sai loại."}],
        [{"kind": "narration", "text": "   "}],
        [],
    ],
)
def test_validate_narrator_segments_rejects_ambiguous_or_malformed_output(segments):
    with pytest.raises(ValidationError):
        validate_narrator_segments(segments, {"char-linh": "profile-linh-v3"})


def test_parse_narrator_payload_renders_valid_structured_output_without_json_markup():
    display, segments = parse_narrator_payload('{"segments":[{"kind":"narration","text":"Mưa rơi."},{"kind":"dialogue","text":"Vào đi.","character_id":"char-linh","profile_version_id":"profile-linh-v3"}]}', {"char-linh": "profile-linh-v3"})
    assert display == "Mưa rơi.\nVào đi."
    assert segments[1]["character_id"] == "char-linh"


def test_parse_narrator_payload_normalizes_provider_type_alias_to_kind():
    display, segments = parse_narrator_payload('{"segments":[{"type":"narration","text":"Mưa rơi."},{"type":"dialogue","text":"Vào đi.","character_id":"char-linh","profile_version_id":"profile-linh-v3"}]}', {"char-linh": "profile-linh-v3"})
    assert display == "Mưa rơi.\nVào đi."
    assert segments == [{"kind": "narration", "text": "Mưa rơi."}, {"kind": "dialogue", "text": "Vào đi.", "character_id": "char-linh", "profile_version_id": "profile-linh-v3"}]


def test_parse_narrator_payload_rejects_conflicting_kind_and_type_aliases():
    with pytest.raises(ValidationError, match="kind and type disagree"):
        parse_narrator_payload('{"segments":[{"kind":"narration","type":"dialogue","text":"Sai."}]}', {})


def test_parse_narrator_payload_rejects_json_shaped_invalid_output():
    with pytest.raises(ValidationError):
        parse_narrator_payload('{"segments":[{"kind":"dialogue","text":"Invented","character_id":"nope","profile_version_id":"profile-linh-v3"}]}', {"char-linh": "profile-linh-v3"})
