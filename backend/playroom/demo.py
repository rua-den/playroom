"""Explicit, local-only synthetic Playroom demo.

This module is intentionally opt-in.  Production ``create_app`` keeps its
OpenRouter factory and secure cookie defaults; the demo factory is assembled
only by ``playroom-demo``/``create_demo_app``.
"""

from __future__ import annotations

import argparse
import ipaddress
import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .app import create_app
from .auth import create_owner
from .db import connect, migrate
from .model_profiles import persist_model_profile
from .provider import FakeProvider, ProviderResult
from .settings import save_owner_settings


@dataclass(frozen=True)
class DemoInstall:
    email: str
    password: str | None
    created: bool


class DemoFakeProvider(FakeProvider):
    """Repeatable narrative fixture; it never consumes a finite output list."""

    def __init__(self):
        super().__init__([], capabilities=None)

    def generate_text(self, request: dict):
        self.calls.append({key: value for key, value in request.items() if key != "cancel_event"})
        stage = str(request.get("stage", "narration"))
        self.stage_counts[stage] = self.stage_counts.get(stage, 0) + 1
        text = "Ánh sáng dịu lan qua căn phòng, và câu chuyện tiếp tục mở ra."
        yield text
        yield ProviderResult(text=text, usage={"input_tokens": 24, "output_tokens": len(text.split()), "total_tokens": 24 + len(text.split())}, finish_reason="stop")


def _validate_loopback_host(host: str) -> None:
    if host.casefold() == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("playroom-demo only accepts a loopback bind host") from exc
    if not address.is_loopback:
        raise ValueError("playroom-demo only accepts a loopback bind host")


def _profile() -> dict:
    return {
        "id": "demo-narrator",
        "provider": "fake",
        "endpoint": "fake://local",
        "model": "synthetic-fixture",
        "provider_tag": "synthetic-demo",
        "context_limit": 12000,
        "output_limit": 4000,
        "credential_tier": "free",
        "pricing_verified": True,
        "pricing": {"prompt": "0", "completion": "0", "currency": "USD", "unit": "USD/token"},
        "secret_version": "synthetic-demo",
        "is_test_profile": True,
        "capabilities_verified": True,
        "structured_output": True,
        "native_structured_output": True,
        "structured_schema_parameter": "response_format",
        "supported_parameters": ["response_format", "max_tokens"],
    }


def _ensure_install(root: Path, email: str, password: str | None) -> DemoInstall:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "playroom.sqlite3"
    connection = connect(database)
    try:
        migrate(connection)
        normalized = email.strip().casefold()
        row = connection.execute("SELECT id FROM owners WHERE email=?", (normalized,)).fetchone()
        if row:
            profile_row = connection.execute("SELECT 1 FROM model_profile_versions WHERE owner_id=? LIMIT 1", (row["id"],)).fetchone()
            if profile_row is None:
                profile = persist_model_profile(connection, row["id"], _profile())
                save_owner_settings(connection, row["id"], {"roles": {"narrator": {"id": profile["id"], "version": profile["version"]}}, "mode": "economy", "policy": "free_only", "budgets": {}})
            return DemoInstall(normalized, None, False)
        generated = password or secrets.token_urlsafe(18)
        owner = create_owner(connection, normalized, generated)
        profile = persist_model_profile(connection, owner.id, _profile())
        save_owner_settings(connection, owner.id, {"roles": {"narrator": {"id": profile["id"], "version": profile["version"]}}, "mode": "economy", "policy": "free_only", "budgets": {}})
        return DemoInstall(owner.email, generated, True)
    finally:
        connection.close()


def create_demo_app(root: str | Path, *, email: str = "demo@localhost", password: str | None = None, frontend_dist: str | Path | None = None):
    root = Path(root)
    install = _ensure_install(root, email, password)
    app = create_app(database_url=str(root / "playroom.sqlite3"), credential_root=str(root / "secrets"), secure_cookies=False, generation_provider=DemoFakeProvider())
    app.state.demo_mode = True
    app.state.demo_root = str(root)
    app.get("/api/demo/info")(lambda: {"mode": "synthetic", "label": "Chế độ demo tổng hợp", "provider": "synthetic-fixture"})

    dist = Path(frontend_dist) if frontend_dist is not None else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir() and (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="demo-assets") if (dist / "assets").is_dir() else None

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = dist / path
            if path and candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def missing_frontend():
            return JSONResponse(status_code=503, content={"detail": "Demo frontend build is missing; run npm run build first."})

    return app, install


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the explicit local Playroom synthetic demo")
    parser.add_argument("--data-dir", default=".playroom-demo", help="Dedicated persistent demo directory")
    parser.add_argument("--email", default="demo@localhost")
    parser.add_argument("--password", help="Owner password (minimum 12 characters); generated and shown once when omitted")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback by default")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--frontend-dist")
    args = parser.parse_args()
    _validate_loopback_host(args.host)
    install = _ensure_install(Path(args.data_dir), args.email, args.password)
    if install.created:
        print(f"Demo owner: {install.email}", flush=True)
        print(f"Demo password (show once): {install.password}", flush=True)
    app, _ = create_demo_app(Path(args.data_dir), email=args.email, password=args.password, frontend_dist=args.frontend_dist)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
