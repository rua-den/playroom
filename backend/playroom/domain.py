from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PlayroomError(Exception):
    """Base class for expected domain failures."""


class NotFound(PlayroomError):
    pass


class StateConflict(PlayroomError):
    pass


class ValidationError(PlayroomError):
    pass


class Unauthorized(PlayroomError):
    pass


class RateLimited(PlayroomError):
    pass


@dataclass(frozen=True)
class Owner:
    id: str
    email: str
    username: str = ""
    is_admin: bool = False


@dataclass(frozen=True)
class Campaign:
    id: str
    owner_id: str
    title: str
    initial_branch_id: str
    character_ids: tuple[str, ...]
    profile_ids: dict[str, str]


@dataclass(frozen=True)
class BranchHead:
    campaign_id: str
    branch_id: str
    state_version: int
    checkpoint_id: str
    turn_id: str | None = None
    revision_id: str | None = None


@dataclass(frozen=True)
class StateCheckpoint:
    id: str
    campaign_id: str
    branch_id: str
    state_version: int
    parent_checkpoint_id: str | None
    snapshot: dict[str, Any]


@dataclass(frozen=True)
class MemoryVersion:
    memory_id: str
    version_id: str
    version: int
    kind: str
    text: str
    entity_ids: tuple[str, ...]
    origin: str
    status: str
    pinned: bool
    mandatory: bool
    knowledge_scope: str
    known_by: tuple[str, ...]
    source_revision_ids: tuple[str, ...]
    subject_id: str | None
    predicate: str | None
    value: str | None
    object_id: str | None
    supersedes_memory_id: str | None
    state_version: int
    checkpoint_id: str
    read_state_version: int | None = None
    read_checkpoint_id: str | None = None


def require_uuid(value: str, field: str) -> str:
    from uuid import UUID

    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(f"{field} must be a UUID") from exc
