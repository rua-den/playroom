"""Provider-independent roleplay safety checks for player agency."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Sequence

from .domain import ValidationError
from .roleplay_segments import parse_player_input


class PlayerAgencyViolation(ValidationError):
    """Narrator authored a new action/state for the player-controlled persona."""


_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nod", ("gật đầu",)),
    ("shake_head", ("lắc đầu",)),
    ("smile", ("mỉm cười", "nở nụ cười", "cười")),
    ("sigh", ("thở dài",)),
    ("feel", ("cảm thấy",)),
    ("decide", ("quyết định",)),
    ("think", ("nghĩ thầm", "thầm nghĩ", "tự nhủ")),
    ("remember", ("chợt nhớ",)),
    ("imagine", ("tưởng tượng",)),
    ("agree", ("đồng ý",)),
    ("stand", ("đứng dậy", "đứng lên")),
    ("sit", ("ngồi xuống",)),
    ("enter", ("bước vào", "đi vào", "tiến vào")),
    ("leave", ("bước ra", "đi ra", "rời khỏi")),
    ("follow", ("đi theo", "bước theo")),
    ("approach", ("bước tới", "đi tới", "tiến tới", "lại gần")),
    ("turn", ("quay lại", "quay sang")),
    ("open", ("mở",)),
    ("close", ("đóng",)),
    ("hold", ("cầm", "nắm")),
    ("pick_up", ("nhặt",)),
    ("take", ("lấy",)),
    ("put", ("đặt",)),
    ("pull", ("kéo",)),
    ("push", ("đẩy",)),
    ("touch", ("chạm",)),
    ("write", ("viết", "ghi")),
    ("read", ("đọc",)),
    ("look", ("nhìn", "ngước nhìn", "liếc nhìn")),
    ("search", ("tìm", "lục")),
    ("raise", ("giơ", "đưa")),
    ("hug", ("ôm",)),
)

_INTROS = (
    "rồi ",
    "và ",
    "còn ",
    "sau đó ",
    "lúc này ",
    "thế rồi ",
    "ngay lúc đó ",
)
_ADVERBS = (
    "khẽ ",
    "vội ",
    "chậm rãi ",
    "bất ngờ ",
    "đột nhiên ",
    "lặng lẽ ",
    "nhẹ nhàng ",
    "lập tức ",
    "liền ",
    "bỗng ",
)
_NEGATIONS = ("không ", "chưa ", "chẳng ")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


_NORMALIZED_NEGATIONS = tuple(_normalize(value) for value in _NEGATIONS)

_NORMALIZED_RULES = tuple(
    (name, tuple(_normalize(variant) for variant in variants))
    for name, variants in _RULES
)


def _contains_phrase(value: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", value) is not None


def _authorized_rules(action_text: str) -> set[str]:
    action_segments = [
        _normalize(segment.get("text", ""))
        for segment in parse_player_input(action_text)
        if segment.get("kind") == "action" and segment.get("text", "").strip()
    ]
    authorized: set[str] = set()
    for name, variants in _NORMALIZED_RULES:
        if any(_contains_phrase(action, variant) for action in action_segments for variant in variants):
            authorized.add(name)
    return authorized


def _aliases(persona: Mapping[str, object]) -> list[str]:
    values: list[str] = []
    name = persona.get("name")
    if isinstance(name, str) and name.strip():
        values.append(_normalize(name))
    aliases = persona.get("aliases")
    if isinstance(aliases, Sequence) and not isinstance(aliases, (str, bytes)):
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                values.append(_normalize(alias))
    return sorted(set(values), key=len, reverse=True)


def _subject_remainder(clause: str, aliases: Sequence[str]) -> str | None:
    value = _normalize(clause)
    value = value.lstrip(' "'“”‘’([{—–-')
    for intro in _INTROS:
        normalized = _normalize(intro)
        if value.startswith(normalized):
            value = value[len(normalized):].lstrip()
            break
    for alias in aliases:
        match = re.match(r"^" + re.escape(alias) + r"(?=$|\W)\s*,?\s*(?P<rest>.*)$", value)
        if match is not None:
            rest = match.group("rest").strip()
            changed = True
            while changed:
                changed = False
                for adverb in _ADVERBS:
                    normalized = _normalize(adverb)
                    if rest.startswith(normalized):
                        rest = rest[len(normalized):].lstrip()
                        changed = True
                        break
            return rest
    return None


def validate_player_agency(
    action_text: str,
    segments: Sequence[Mapping[str, object]],
    persona: Mapping[str, object],
) -> None:
    """Reject high-confidence new actions/states authored for the player persona.

    Only structured narration is inspected. Player authorization comes solely
    from explicit action spans parsed from the submitted player text; dialogue
    that merely states an intention does not authorize the narrator to perform it.
    """

    aliases = _aliases(persona)
    if not aliases:
        return
    authorized = _authorized_rules(action_text)
    for segment in segments:
        if not isinstance(segment, Mapping) or segment.get("kind") != "narration":
            continue
        text = segment.get("text")
        if not isinstance(text, str):
            continue
        for clause in re.split(r"[.!?;\n]+", text):
            rest = _subject_remainder(clause, aliases)
            if not rest or any(rest.startswith(prefix) for prefix in _NORMALIZED_NEGATIONS):
                continue
            for name, variants in _NORMALIZED_RULES:
                if name in authorized:
                    continue
                if any(rest == variant or rest.startswith(variant + " ") for variant in variants):
                    raise PlayerAgencyViolation(
                        "Narrator attempted to author a new action, thought, emotion, or decision for the player persona"
                    )
