from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..auth import SESSION_COOKIE, create_account, delete_account, update_account
from ..db import request_connection, transaction
from ..domain import Owner, require_uuid
from .auth import require_admin

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=12, max_length=1024)


class AccountUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str | None = Field(default=None, max_length=1024)


def _account(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"]), "created_at": row["created_at"]}


@router.get("")
def list_accounts(connection: sqlite3.Connection = Depends(request_connection), _: Owner = Depends(require_admin)):
    rows = connection.execute("SELECT id,username,is_admin,created_at FROM owners ORDER BY username COLLATE NOCASE,id").fetchall()
    return [_account(row) for row in rows]


@router.post("", status_code=201)
def create(payload: AccountCreate, connection: sqlite3.Connection = Depends(request_connection), _: Owner = Depends(require_admin)):
    with transaction(connection):
        owner = create_account(connection, payload.username, payload.password)
        row = connection.execute("SELECT id,username,is_admin,created_at FROM owners WHERE id=?", (owner.id,)).fetchone()
    return _account(row)


@router.patch("/{account_id}")
def update(account_id: str, payload: AccountUpdate, request: Request, connection: sqlite3.Connection = Depends(request_connection), actor: Owner = Depends(require_admin)):
    owner_id = require_uuid(account_id, "account_id")
    token = request.cookies.get(SESSION_COOKIE, "")
    with transaction(connection):
        owner = update_account(connection, owner_id, payload.username, payload.password, actor_id=actor.id, session_token=token)
        row = connection.execute("SELECT id,username,is_admin,created_at FROM owners WHERE id=?", (owner.id,)).fetchone()
    return _account(row)


@router.delete("/{account_id}", status_code=204)
def remove(account_id: str, request: Request, connection: sqlite3.Connection = Depends(request_connection), actor: Owner = Depends(require_admin)):
    owner_id = require_uuid(account_id, "account_id")
    with transaction(connection):
        delete_account(connection, owner_id, actor_id=actor.id)
    request.app.state.credential_store.delete_owner(owner_id)
    return Response(status_code=204)
