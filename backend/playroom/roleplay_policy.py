"""Provider-independent roleplay safety checks for player agency."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Sequence

from .domain import ValidationError
from .roleplay_segments import parse_player_input


class PlayerAgencyViolation(ValidationError):
    """Narrator authored a new action/state for the player-controlled persona."""


class NpcKnowledgeViolation(ValidationError):
    """NPC dialogue used a context fact outside that NPC knowledge scope."""


class GroundingViolation(ValidationError):
    """Narrator introduced unsupported precise state not present in context."""


_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("nod", ("gật đầu",)),
    ("shake_head", ("lắc đầu",)),
    ("smile", ("mỉm cười", "nở nụ cười", "cười")),
    ("sigh", ("thở dài",)),
    ("feel", ("cảm thấy",)),
    ("emotion_state", ("lo lắng", "bối rối", "ngạc nhiên", "sợ hãi", "tức giận", "vui mừng", "buồn bã", "căng thẳng", "hồi hộp", "xấu hổ", "ngượng ngùng", "hoảng hốt", "bất an")),
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

_EMOTION_STATE_VARIANTS = tuple(
    _normalize(value)
    for value in ("lo lắng", "bối rối", "ngạc nhiên", "sợ hãi", "tức giận", "vui mừng", "buồn bã", "căng thẳng", "hồi hộp", "xấu hổ", "ngượng ngùng", "hoảng hốt", "bất an")
)

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
    value = value.lstrip(" \"'“”‘’([{—–-")
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


def _contains_player_emotion_claim(clause: str, aliases: Sequence[str]) -> bool:
    value = _normalize(clause)
    state = "(?:" + "|".join(re.escape(item) for item in _EMOTION_STATE_VARIANTS) + ")"
    feature = r"(?:khuon mat|ve mat|net mat|anh mat|giong noi)"
    for alias in aliases:
        patterns = (
            rf"{feature}.{{0,48}}\b{state}\b.{{0,24}}\bcua\s+{re.escape(alias)}\b",
            rf"{feature}\s+{re.escape(alias)}\b.{{0,48}}\b{state}\b",
            rf"\b{re.escape(alias)}\b.{{0,24}}\b(?:co ve|trong|to ra|day)\s+{state}\b",
        )
        if any(re.search(pattern, value) is not None for pattern in patterns):
            return True
    return False


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
            if "emotion_state" not in authorized and _contains_player_emotion_claim(clause, aliases):
                raise PlayerAgencyViolation(
                    "Narrator attempted to author a new observable emotion for the player persona"
                )
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


_KNOWLEDGE_STOPWORDS = {
    "la", "va", "cua", "mot", "nhung", "voi", "cho", "o", "tai", "trong",
    "tren", "duoi", "da", "se", "dang", "nay", "kia", "do", "thi", "co",
    "khong", "chua", "roi", "sau", "truoc", "neu", "khi", "len", "xuong",
    "rat", "qua", "lai",
}


def _knowledge_tokens(value: str) -> list[str]:
    normalized = _normalize(value)
    normalized = re.sub(r"(?<=\w)[_-](?=\w)", "", normalized)
    return [
        token
        for token in re.findall(r"[a-z0-9]+", normalized)
        if (len(token) >= 3 or any(char.isdigit() for char in token))
        and token not in _KNOWLEDGE_STOPWORDS
    ]


def _fact_matches(candidate: str, fact: str) -> bool:
    candidate_tokens = set(_knowledge_tokens(candidate))
    fact_tokens = set(_knowledge_tokens(fact))
    if not candidate_tokens or not fact_tokens:
        return False
    shared = candidate_tokens & fact_tokens
    if any(any(char.isdigit() for char in token) for token in shared):
        return True
    if len(shared) >= 3:
        return True
    if len(fact_tokens) <= 3 and len(shared) >= 2 and len(shared) / len(fact_tokens) >= 2 / 3:
        return True
    return False


def _player_dialogue(action_text: str) -> str:
    return " ".join(
        segment.get("text", "")
        for segment in parse_player_input(action_text)
        if segment.get("kind") == "dialogue"
    )


def _speaker_heard_current_disclosure(
    speaker_id: str,
    fact_text: str,
    preview: Mapping[str, object],
) -> bool:
    action_text = preview.get("action")
    if not isinstance(action_text, str):
        return False
    dialogue = _player_dialogue(action_text)
    if not _fact_matches(dialogue, fact_text):
        return False
    selected = preview.get("selected_characters")
    if not isinstance(selected, Sequence) or isinstance(selected, (str, bytes)):
        return False
    for item in selected:
        if not isinstance(item, Mapping) or item.get("character_id") != speaker_id:
            continue
        if item.get("present") is True:
            return True
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            if _contains_phrase(_normalize(dialogue), _normalize(name)):
                return True
    return False


def validate_npc_knowledge(
    segments: Sequence[Mapping[str, object]],
    preview: Mapping[str, object],
) -> None:
    """Fail closed when attributed NPC dialogue leaks restricted context."""

    blocks = preview.get("blocks")
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)):
        return
    restricted = []
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "memory":
            continue
        scope = block.get("knowledge_scope")
        if scope not in {"narrator_only", "known_by"}:
            continue
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        known_by = block.get("known_by")
        known_ids = (
            {value for value in known_by if isinstance(value, str)}
            if isinstance(known_by, Sequence) and not isinstance(known_by, (str, bytes))
            else set()
        )
        restricted.append((scope, known_ids, text))

    for segment in segments:
        if not isinstance(segment, Mapping) or segment.get("kind") != "dialogue":
            continue
        speaker_id = segment.get("character_id")
        text = segment.get("text")
        if not isinstance(speaker_id, str) or not isinstance(text, str):
            continue
        for scope, known_ids, fact_text in restricted:
            if scope == "known_by" and speaker_id in known_ids:
                continue
            if _speaker_heard_current_disclosure(speaker_id, fact_text, preview):
                continue
            if _fact_matches(text, fact_text):
                raise NpcKnowledgeViolation(
                    "NPC dialogue attempted to use a fact outside the speaker approved knowledge scope"
                )



_CLOCK_RE = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)")


def _clock_values(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value)
    return set(_CLOCK_RE.findall(normalized))


def validate_grounded_precision(
    segments: Sequence[Mapping[str, object]],
    preview: Mapping[str, object],
) -> None:
    """Reject new exact clock times that have no source in player/context text."""

    source_parts: list[str] = []
    action = preview.get("action")
    if isinstance(action, str):
        source_parts.append(action)
    blocks = preview.get("blocks")
    if isinstance(blocks, Sequence) and not isinstance(blocks, (str, bytes)):
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            text = block.get("text")
            if isinstance(text, str):
                source_parts.append(text)
    grounded = _clock_values("\n".join(source_parts))
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        text = segment.get("text")
        if not isinstance(text, str):
            continue
        invented = _clock_values(text) - grounded
        if invented:
            raise GroundingViolation(
                "Narrator introduced an exact clock time that is absent from the approved context"
            )
