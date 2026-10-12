from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
import sqlite3
from pydantic import BaseModel, EmailStr, Field

from ..auth import SESSION_COOKIE, SESSION_TTL_SECONDS, create_session, revoke_session, session_valid, verify_owner_password
from ..db import request_connection
from ..domain import Owner, RateLimited, Unauthorized

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


def require_owner(request: Request, connection: sqlite3.Connection = Depends(request_connection)) -> Owner:
    token = request.cookies.get(SESSION_COOKIE)
    owner = session_valid(connection, token)
    if owner is None:
        raise Unauthorized("Owner session is required")
    return owner


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, connection: sqlite3.Connection = Depends(request_connection)):
    owner = verify_owner_password(
        connection,
        payload.email,
        payload.password,
        failure_limit=request.app.state.login_failure_limit,
        window_seconds=request.app.state.login_failure_window_seconds,
    )
    token = create_session(connection, owner.id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.app.state.secure_cookies,
        samesite="strict",
        path="/",
    )
    return {"owner": {"id": owner.id, "email": owner.email}}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, connection: sqlite3.Connection = Depends(request_connection)):
    revoke_session(connection, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=request.app.state.secure_cookies, samesite="strict")
    response.status_code = 204
    return response


@router.get("/me")
def me(owner: Owner = Depends(require_owner)):
    return {"id": owner.id, "email": owner.email}
