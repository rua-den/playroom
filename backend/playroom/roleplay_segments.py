"""Small, provider independent roleplay segment parser and validator."""

from __future__ import annotations

from typing import Mapping, Sequence
import json

from .domain import ValidationError


def _escaped(raw: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and raw[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _opening_delimiter(raw: str, cursor: int) -> tuple[int, str] | None:
    index = cursor
    while index < len(raw):
        if raw[index] == "*" and not _escaped(raw, index):
            if raw.startswith("**", index):
                return index, "**"
            return index, "*"
        index += 1
    return None


def _closing_delimiter(raw: str, start: int, delimiter: str) -> int:
    if delimiter == "**":
        return raw.find("**", start + 2)
    index = start + 1
    while index < len(raw):
        if raw[index] == "*" and not _escaped(raw, index):
            if raw.startswith("**", index):
                index += 2
                continue
            return index
        index += 1
    return -1


def parse_player_input(raw: str) -> list[dict[str, str]]:
    """Split single- or double-star action spans while retaining raw text."""
    if not isinstance(raw, str):
        raise ValidationError("Player input must be text")
    segments: list[dict[str, str]] = []
    cursor = 0
    while cursor < len(raw):
        opening = _opening_delimiter(raw, cursor)
        if opening is None:
            segments.append({"kind": "dialogue", "text": raw[cursor:]})
            break
        start, delimiter = opening
        if start > cursor:
            segments.append({"kind": "dialogue", "text": raw[cursor:start]})
        end = _closing_delimiter(raw, start, delimiter)
        if end < 0:
            # Keep malformed markup visible and attributable as player dialogue.
            malformed = raw[start:]
            if segments and segments[-1]["kind"] == "dialogue":
                segments[-1]["text"] += malformed
            else:
                segments.append({"kind": "dialogue", "text": malformed})
            break
        width = len(delimiter)
        segments.append({"kind": "action", "text": raw[start + width:end]})
        cursor = end + width
    if not segments:
        segments.append({"kind": "dialogue", "text": ""})
    return segments


def validate_narrator_segments(segments: Sequence[Mapping[str, object]], selected_characters: Mapping[str, str]) -> list[dict]:
    """Validate structured narrator output against the checkpoint selected cast."""
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)) or not segments:
        raise ValidationError("Narrator output must contain segments")
    result: list[dict] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            raise ValidationError("Narrator segment must be an object")
        kind = segment.get("kind")
        text = segment.get("text")
        if kind not in {"narration", "dialogue"} or not isinstance(text, str) or not text.strip():
            raise ValidationError("Narrator segment kind or text is malformed")
        item = {"kind": kind, "text": text}
        character_id = segment.get("character_id")
        profile_version_id = segment.get("profile_version_id")
        if kind == "dialogue":
            if not isinstance(character_id, str) or not isinstance(profile_version_id, str):
                raise ValidationError("NPC dialogue must identify its character and profile version")
            if selected_characters.get(character_id) != profile_version_id:
                raise ValidationError("Narrator dialogue references an unselected character version")
            item.update(character_id=character_id, profile_version_id=profile_version_id)
        elif character_id is not None or profile_version_id is not None:
            raise ValidationError("Narration cannot carry partial speaker attribution")
        result.append(item)
    return result


def parse_narrator_payload(raw: str, selected_characters: Mapping[str, str]) -> tuple[str, list[dict] | None]:
    """Decode structured narrator output, retaining ordinary text compatibility."""
    if not isinstance(raw, str):
        raise ValidationError("Narrator output must be text")
    if not raw.lstrip().startswith(("{", "[")):
        return raw, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Structured narrator output is not valid JSON") from exc
    segments = value.get("segments") if isinstance(value, dict) else value
    if isinstance(segments, Sequence) and not isinstance(segments, (str, bytes)):
        normalized_segments = []
        for segment in segments:
            if isinstance(segment, Mapping) and "type" in segment:
                if "kind" in segment and segment.get("kind") != segment.get("type"):
                    raise ValidationError("Narrator segment kind and type disagree")
                segment = {**segment, "kind": segment.get("type")}
            normalized_segments.append(segment)
        segments = normalized_segments
    validated = validate_narrator_segments(segments, selected_characters)
    return "\n".join(item["text"] for item in validated), validated
