"""Regression: live Gemma plain-text narration must not crash the quality probe.

This is an evaluation-only fallback; app narration segment validation remains
unchanged. Plain text is tagged as non-structured, never represented as PASS.
"""
import pytest

from live_ollama_long_story_trial import _review_segments


def test_plain_narration_is_visible_but_warns_about_format():
    narrative = "Vy quay lại hỏi Lan: Cậu tìm phong bì xanh à?"
    segments, warning = _review_segments(narrative, None)
    assert warning is True
    assert segments == [{"kind": "narration", "text": narrative}]


def test_valid_structured_segments_keep_attribution_and_do_not_warn():
    segments = [
        {"kind": "narration", "text": "Vy nhìn về phía quầy."},
        {"kind": "dialogue", "character_id": "npc-vy-synthetic",
         "profile_version_id": "vy-v1", "text": "Có chuyện gì vậy?"},
    ]
    parsed, warning = _review_segments("Vy nhìn về phía quầy.\nCó chuyện gì vậy?", segments)
    assert parsed == segments
    assert warning is False


def test_empty_plain_response_does_not_count_as_valid_turn():
    with pytest.raises(ValueError, match="Empty"):
        _review_segments("  ", None)
