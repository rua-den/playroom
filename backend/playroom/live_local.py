"""Local runner for the real Playroom application and built frontend."""

from __future__ import annotations

import argparse
import getpass
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

from .app import create_app
from .auth import create_owner
from .db import connect, migrate
from .domain import ValidationError


def _frontend_root(frontend_dist: str | Path | None) -> Path:
    root = Path(frontend_dist) if frontend_dist is not None else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    root = root.expanduser()
    index = root / "index.html"
    if not root.is_dir() or not index.is_file() or index.is_symlink():
        raise ValueError(f"Built frontend is missing: {root} (run npm run build first)")
    return root.resolve()


def _safe_file(root: Path, request_path: str) -> Path | None:
    # Backslashes are separators on Windows and must never be accepted as URL data.
    if "\\" in request_path or "\x00" in request_path:
        return None
    relative = request_path.lstrip("/")
    untrusted = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            return None
    candidate = untrusted.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def create_live_local_app(data_dir: str | Path, *, frontend_dist: str | Path | None = None):
    dist = _frontend_root(frontend_dist)
    root = Path(data_dir).expanduser()
    resolved_root = root.resolve()
    try:
        resolved_root.relative_to(dist)
    except ValueError:
        pass
    else:
        raise ValueError("data directory must be outside frontend directory")
    database_path = (root / "playroom.sqlite3").resolve()
    secrets_path = (root / "secrets").resolve()
    for path in (database_path, secrets_path):
        try:
            path.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("live local data paths must remain inside data directory") from exc
        try:
            path.relative_to(dist)
        except ValueError:
            continue
        raise ValueError("live local data paths must be outside frontend directory")
    root_preexisted = root.exists()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Do not alter permissions on an explicitly reused data directory.
    # A newly created root is private by default on POSIX filesystems.
    if not root_preexisted:
        try:
            root.chmod(0o700)
        except OSError:
            pass
    secrets_path.mkdir(parents=True, exist_ok=True)

    app = create_app(
        database_url=str(database_path),
        credential_root=str(secrets_path),
        allowed_hosts={"127.0.0.1", "localhost"},
        secure_cookies=False,
    )
    app.state.live_local_root = str(root)
    app.state.live_local_frontend = str(dist)

    @app.get("/{path:path}", include_in_schema=False)
    async def live_frontend(request: Request, path: str):
        if request.url.path.startswith("/api/") or request.url.path == "/api":
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        raw_path = request.scope.get("raw_path", b"")
        raw_text = raw_path.decode("utf-8", errors="replace") if isinstance(raw_path, bytes) else str(raw_path)
        decoded_raw = unquote(unquote(raw_text))
        if "\\" in decoded_raw or any(part == ".." for part in decoded_raw.split("/")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = _safe_file(dist, request.url.path)
        if candidate is not None:
            return FileResponse(candidate)
        if Path(request.url.path).suffix:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        fallback = _safe_file(dist, "/index.html")
        if fallback is None:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(fallback)

    return app


def _validate_cli(args: argparse.Namespace) -> None:
    if args.host != "127.0.0.1":
        raise ValueError("playroom-live-local only accepts host 127.0.0.1")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")


def setup_owner_if_needed(data_dir: str | Path) -> bool:
    """Create the first owner interactively, without changing an existing owner."""
    root = Path(data_dir).expanduser()
    connection = connect(root / "playroom.sqlite3")
    try:
        migrate(connection)
        if connection.execute("SELECT 1 FROM owners LIMIT 1").fetchone() is not None:
            return False
        email = input("Owner email: ").strip()
        password = getpass.getpass("Owner password (minimum 12 characters): ")
        confirmation = getpass.getpass("Confirm owner password: ")
        if password != confirmation:
            raise ValueError("Passwords do not match")
        try:
            owner = create_owner(connection, email, password)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        print(f"Created owner {owner.email}", flush=True)
        return True
    finally:
        connection.close()


def serve_with_browser(app, host: str, port: int) -> None:
    """Run uvicorn in the foreground and open the UI only after /health responds."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    thread = threading.Thread(target=server.run, name="playroom-local-server", daemon=True)
    thread.start()
    url = f"http://{host}:{port}/"
    deadline = time.monotonic() + 30
    try:
        while thread.is_alive() and time.monotonic() < deadline:
            if getattr(server, "started", False):
                try:
                    with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1) as response:
                        if 200 <= response.status < 300:
                            webbrowser.open(url)
                            break
                except (OSError, urllib.error.URLError):
                    pass
            time.sleep(0.1)
        else:
            server.should_exit = True
            thread.join(timeout=5)
            raise RuntimeError(f"Playroom server did not become ready at {url}")
        thread.join()
    except BaseException:
        server.should_exit = True
        thread.join(timeout=5)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real Playroom application locally")
    parser.add_argument("--data-dir", default=".playroom-live")
    parser.add_argument("--frontend-dist")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--setup-owner", action="store_true", help="Prompt for the first owner when no owner exists")
    parser.add_argument("--open-browser", action="store_true", help="Open the loopback UI after the server is ready")
    args = parser.parse_args()
    _validate_cli(args)
    app = create_live_local_app(args.data_dir, frontend_dist=args.frontend_dist)
    if args.setup_owner:
        setup_owner_if_needed(args.data_dir)
    if args.open_browser:
        serve_with_browser(app, "127.0.0.1", args.port)
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
