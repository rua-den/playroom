from __future__ import annotations

import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import auth, campaigns, memory
from .db import connect, migrate
from .domain import NotFound, PlayroomError, RateLimited, StateConflict, Unauthorized, ValidationError


def _allowed_hosts(value: set[str] | None) -> set[str]:
    if value is not None:
        return {host.strip().casefold() for host in value if host.strip()}
    configured = os.getenv("PLAYROOM_ALLOWED_HOSTS", "localhost,127.0.0.1")
    return {host.strip().casefold() for host in configured.split(",") if host.strip()}


def _origin_tuple(value: str):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    port = port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme.casefold(), parsed.hostname.casefold(), port


def _request_origin(request: Request):
    host_header = request.headers.get("host", "")
    try:
        parsed_host = urlsplit(f"//{host_header}")
        port = parsed_host.port
    except ValueError:
        return None
    if not parsed_host.hostname:
        return None
    scheme = request.url.scheme.casefold()
    port = port or (443 if scheme == "https" else 80)
    return scheme, parsed_host.hostname.casefold(), port


def create_app(
    database_url: str | None = None,
    *,
    allowed_hosts: set[str] | None = None,
    secure_cookies: bool = True,
    login_failure_limit: int = 5,
    login_failure_window_seconds: int = 900,
) -> FastAPI:
    configured_url = database_url or os.getenv("PLAYROOM_DATABASE_URL", "./data/playroom.sqlite3")
    is_memory_database = configured_url in {":memory:", "sqlite:///:memory:"}
    effective_url = f"file:playroom-{uuid4()}?mode=memory&cache=shared" if is_memory_database else configured_url
    keeper = connect(effective_url) if is_memory_database else None
    migration_connection = keeper or connect(effective_url)
    migrate(migration_connection)
    if not is_memory_database:
        migration_connection.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if app.state.memory_keeper is not None:
            app.state.memory_keeper.close()

    app = FastAPI(title="Playroom", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.database_url = effective_url
    app.state.memory_keeper = keeper
    app.state.allowed_hosts = _allowed_hosts(allowed_hosts)
    app.state.secure_cookies = secure_cookies
    app.state.login_failure_limit = login_failure_limit
    app.state.login_failure_window_seconds = login_failure_window_seconds

    @app.middleware("http")
    async def protect_host_and_origin(request: Request, call_next):
        host_header = request.headers.get("host", "")
        try:
            host = urlsplit(f"//{host_header}").hostname
        except ValueError:
            host = None
        if not host or host.casefold() not in request.app.state.allowed_hosts:
            return JSONResponse(status_code=400, content={"detail": "Unrecognized Host header"})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if not origin or _origin_tuple(origin) != _request_origin(request):
                return JSONResponse(status_code=403, content={"detail": "Same-origin request required"})
        return await call_next(request)

    @app.exception_handler(PlayroomError)
    async def playroom_error_handler(request: Request, exc: PlayroomError):
        if isinstance(exc, NotFound):
            status = 404
        elif isinstance(exc, StateConflict):
            status = 409
        elif isinstance(exc, ValidationError):
            status = 422
        elif isinstance(exc, RateLimited):
            status = 429
        elif isinstance(exc, Unauthorized):
            status = 401
        else:
            status = 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(campaigns.router)
    app.include_router(memory.router)
    return app


