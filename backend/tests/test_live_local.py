from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner
from playroom.db import connect, migrate
from playroom.provider import default_provider_factory
from playroom.live_local import create_live_local_app, main


def _dist(tmp_path, *, index="<html>live</html>"):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (dist / "index.html").write_text(index, encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name":"live"}', encoding="utf-8")
    return dist


def test_missing_frontend_fails_before_creating_data(tmp_path):
    with pytest.raises(ValueError, match="frontend"):
        create_live_local_app(tmp_path / "data", frontend_dist=tmp_path / "missing")
    assert not (tmp_path / "data").exists()


def test_data_directory_cannot_be_inside_frontend_build(tmp_path):
    dist = _dist(tmp_path)
    with pytest.raises(ValueError, match="outside frontend"):
        create_live_local_app(dist / "data", frontend_dist=dist)
    assert not (dist / "data").exists()


def test_live_factory_uses_real_provider_factory_and_persistent_layout(tmp_path):
    app = create_live_local_app(tmp_path / "data", frontend_dist=_dist(tmp_path))
    assert app.state.generation_provider is None
    assert app.state.generation_provider_factory is default_provider_factory
    assert app.state.secure_cookies is False
    assert app.state.allowed_hosts == {"127.0.0.1", "localhost"}
    assert (tmp_path / "data" / "playroom.sqlite3").is_file()
    assert (tmp_path / "data" / "secrets").is_dir()


def test_live_serves_spa_and_rejects_api_unknown_and_traversal(tmp_path):
    dist = _dist(tmp_path)
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    app = create_live_local_app(tmp_path / "data", frontend_dist=dist)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/").text == "<html>live</html>"
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/campaigns/new").text == "<html>live</html>"
        assert client.get("/api/unknown").status_code == 404
        for path in ("/%2e%2e/outside.txt", "/..\\outside.txt", "/%2e%2e%5coutside.txt"):
            response = client.get(path)
            assert response.status_code in {404, 400}
            assert "outside" not in response.text


def test_live_auth_cookie_and_host_origin_protection(tmp_path):
    data = tmp_path / "data"
    connection = connect(data / "playroom.sqlite3")
    migrate(connection)
    create_owner(connection, "owner@example.test", "a secure owner password")
    connection.close()
    app = create_live_local_app(data, frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login = client.post("/api/auth/login", json={"email": "owner@example.test", "password": "a secure owner password"}, headers={"origin": "http://127.0.0.1"})
        assert login.status_code == 200
        assert "secure" not in login.headers["set-cookie"].lower()
        assert client.post("/api/auth/login", json={}, headers={"origin": "http://evil.test"}).status_code == 403
        assert client.get("/health", headers={"host": "evil.test"}).status_code == 400


def test_live_cli_rejects_public_host_and_invalid_port_before_uvicorn(tmp_path, monkeypatch):
    called = []
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *args, **kwargs: called.append((args, kwargs))))
    monkeypatch.setattr(sys, "argv", ["playroom-live-local", "--data-dir", str(tmp_path / "data"), "--frontend-dist", str(_dist(tmp_path)), "--host", "0.0.0.0"])
    with pytest.raises(ValueError, match="127.0.0.1"):
        main()
    assert not (tmp_path / "data").exists()
    monkeypatch.setattr(sys, "argv", ["playroom-live-local", "--data-dir", str(tmp_path / "data2"), "--frontend-dist", str(_dist(tmp_path)), "--port", "0"])
    with pytest.raises(ValueError, match="port"):
        main()
    assert not (tmp_path / "data2").exists()
    assert called == []


def test_live_cli_forwards_loopback_host_and_port(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *args, **kwargs: calls.append(kwargs)))
    dist = _dist(tmp_path)
    monkeypatch.setattr(sys, "argv", ["playroom-live-local", "--data-dir", str(tmp_path / "data"), "--frontend-dist", str(dist), "--port", "8123"])
    main()
    assert calls == [{"host": "127.0.0.1", "port": 8123}]


def test_fresh_live_start_does_not_invoke_provider_factory(tmp_path, monkeypatch):
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        raise AssertionError("provider factory must wait for an authorized generation")

    monkeypatch.setattr("playroom.app.default_provider_factory", factory)
    app = create_live_local_app(tmp_path / "data", frontend_dist=_dist(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1"):
        pass
    assert calls == []

