from __future__ import annotations

import os
import stat
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner
from playroom.db import connect, migrate
from playroom.provider import default_provider_factory
from playroom.model_profiles import persist_model_profile
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


def test_live_rejects_symlinked_index_and_asset(tmp_path):
    dist = _dist(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret outside", encoding="utf-8")
    try:
        (dist / "assets" / "leak.txt").symlink_to(outside)
        app = create_live_local_app(tmp_path / "data", frontend_dist=dist)
        response = TestClient(app, base_url="http://127.0.0.1").get("/assets/leak.txt")
        assert response.status_code == 404
        assert "secret outside" not in response.text
        index = dist / "index.html"
        index.unlink()
        index.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="frontend"):
        create_live_local_app(tmp_path / "data", frontend_dist=dist)


def test_live_rejects_index_symlink_created_after_startup(tmp_path):
    dist = _dist(tmp_path)
    app = create_live_local_app(tmp_path / "data", frontend_dist=dist)
    outside = tmp_path / "outside.html"
    outside.write_text("secret outside", encoding="utf-8")
    try:
        (dist / "index.html").unlink()
        (dist / "index.html").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    response = TestClient(app, base_url="http://127.0.0.1").get("/")
    assert response.status_code == 404
    assert "secret outside" not in response.text


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable to Windows")
def test_new_live_data_root_is_private(tmp_path):
    data = tmp_path / "data"
    create_live_local_app(data, frontend_dist=_dist(tmp_path))
    assert stat.S_IMODE(data.stat().st_mode) == 0o700


def test_live_rejects_data_database_or_secret_alias_into_frontend(tmp_path):
    dist = _dist(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    target_db = dist / "aliased.sqlite3"
    target_db.touch()
    try:
        (data / "playroom.sqlite3").symlink_to(target_db)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="outside frontend|inside data"):
        create_live_local_app(data, frontend_dist=dist)
    (data / "playroom.sqlite3").unlink()
    target_secrets = dist / "aliased-secrets"
    target_secrets.mkdir()
    (data / "secrets").symlink_to(target_secrets, target_is_directory=True)
    with pytest.raises(ValueError, match="outside frontend|inside data"):
        create_live_local_app(data, frontend_dist=dist)


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


def test_live_persists_owner_campaign_settings_and_masked_credentials_across_restart(tmp_path):
    data = tmp_path / "data"
    connection = connect(data / "playroom.sqlite3")
    migrate(connection)
    owner = create_owner(connection, "owner@example.test", "a secure owner password")
    profile = persist_model_profile(connection, owner.id, {
        "id": "local-profile", "provider": "openrouter", "endpoint": "https://example.test",
        "model": "author/model", "provider_tag": "exact", "context_limit": 1000,
        "output_limit": 100, "credential_tier": "free", "pricing_verified": True,
    })
    connection.close()
    dist = _dist(tmp_path)
    app = create_live_local_app(data, frontend_dist=dist)
    headers = {"origin": "http://127.0.0.1"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/auth/login", json={"email": owner.email, "password": "a secure owner password"}, headers=headers).status_code == 200
        campaign = client.post("/api/campaigns", json={"title": "Persisted", "world": {"name": "World"}, "persona": {"name": "Owner"}}, headers=headers)
        assert campaign.status_code == 201, campaign.text
        credential = client.post("/api/provider/credentials", json={"secret": "sk-local-secret"}, headers=headers)
        assert credential.status_code == 201, credential.text
        masked = credential.json()
        assert "sk-local-secret" not in credential.text
        assert masked["masked"] != "sk-local-secret"
        settings = client.put("/api/provider/settings", json={"narrator_profile_id": profile["id"]}, headers=headers)
        assert settings.status_code == 200, settings.text
        assert client.get("/api/provider/credentials").json()[0]["masked"] == masked["masked"]

    app2 = create_live_local_app(data, frontend_dist=dist)
    with TestClient(app2, base_url="http://127.0.0.1") as client2:
        assert client2.post("/api/auth/login", json={"email": owner.email, "password": "a secure owner password"}, headers=headers).status_code == 200
        campaigns = client2.get("/api/campaigns")
        assert campaigns.status_code == 200
        assert campaigns.json()[0]["title"] == "Persisted"
        saved = client2.get("/api/provider/settings")
        assert saved.status_code == 200
        assert saved.json()["roles"]["narrator"]["id"] == profile["id"]
        listed = client2.get("/api/provider/credentials")
        assert listed.status_code == 200
        assert listed.json()[0]["masked"] == masked["masked"]
        assert "sk-local-secret" not in listed.text


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


def test_live_cli_forwards_loopback_host_and_port(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *args, **kwargs: calls.append(kwargs)))
    dist = _dist(tmp_path)
    monkeypatch.setattr(sys, "argv", ["playroom-live-local", "--data-dir", str(tmp_path / "data"), "--frontend-dist", str(dist), "--port", "8123"])
    main()
    assert calls == [{"host": "127.0.0.1", "port": 8123}]
    assert capsys.readouterr().out == ""


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


def test_production_factory_keeps_secure_cookie_default(tmp_path):
    app = create_app(database_url=str(tmp_path / "production.sqlite3"))
    assert app.state.secure_cookies is True

