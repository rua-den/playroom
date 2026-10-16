"""Owner-only ChatGPT selected-conversation JSON preview and import API.

The whole account export remains on the owner's browser. Only the chosen
conversation object crosses the authenticated same-origin connection.
No language-model provider is invoked by these endpoints.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..chatgpt_import import MAX_SOURCE_BYTES, approve_import_review, import_conversation, import_review, preview_conversation
from ..db import request_connection
from ..domain import Owner, ValidationError
from .auth import require_owner

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


class ImportReviewPayload(BaseModel):
    branch_id: str
    checkpoint_id: str
    review: dict[str, bool]
MAX_REQUEST_BYTES = MAX_SOURCE_BYTES + 128 * 1024


async def _payload(request: Request) -> dict:
    raw = bytearray()
    async for piece in request.stream():
        raw.extend(piece)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValidationError("Selected conversation exceeds the 20 MiB import limit")
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("Import JSON cannot be decoded") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("conversation"), dict):
        raise ValidationError("Choose exactly one ChatGPT conversation")
    return parsed


@router.post("/chatgpt/preview")
async def preview(request: Request, owner: Owner = Depends(require_owner)):
    payload = await _payload(request)
    parsed = preview_conversation(payload["conversation"])
    turns = parsed.pop("turns")
    parsed["sample_first"] = turns[0]
    parsed["sample_last"] = turns[-1]
    return parsed


@router.post("/chatgpt/import", status_code=201)
async def import_chatgpt(
    request: Request,
    connection: sqlite3.Connection = Depends(request_connection),
    owner: Owner = Depends(require_owner),
):
    payload = await _payload(request)
    result = import_conversation(
        connection, owner.id, payload["conversation"],
        payload.get("config"), payload.get("import_key"),
    )
    result["review_required"] = import_review(connection, owner.id, result["campaign_id"])["required"]
    result["checkpoint_id"] = connection.execute("SELECT head_checkpoint_id FROM branches WHERE id=?", (result["branch_id"],)).fetchone()[0]
    return result


@router.post("/chatgpt/{campaign_id}/review")
async def review_chatgpt(campaign_id: str, payload: ImportReviewPayload, connection: sqlite3.Connection = Depends(request_connection), owner: Owner = Depends(require_owner)):
    return approve_import_review(connection, owner.id, campaign_id, payload.branch_id, payload.checkpoint_id, payload.review)
