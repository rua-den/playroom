from __future__ import annotations

import os
import socket
import stat
import sys
import threading
import time
import types
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from playroom.app import create_app
from playroom.auth import create_owner
from playroom.db import connect, migrate
from playroom.provider import default_provider_factory
from playroom.model_profiles import persist_model_profile
from playroom.live_local import create_live_local_app, main, serve_with_browser, setup_owner_if_needed, setup_test_account_if_needed


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


def test_test_account_is_explicit_loopback_setup_only(tmp_path):
    data = tmp_path / "data"
    app = create_live_local_app(data, frontend_dist=_dist(tmp_path))
    connection = connect(data / "playroom.sqlite3")
    try:
        assert connection.execute("SELECT 1 FROM owners").fetchone() is None
    finally:
        connection.close()

    assert setup_test_account_if_needed(data) is True
    assert setup_test_account_if_needed(data) is False
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login = client.post("/api/auth/login", json={"email": "admin", "password": "admin"}, headers={"origin": "http://127.0.0.1"})
        assert login.status_code == 200 and login.json()["owner"]["is_admin"] is True
        assert client.get("/api/accounts").status_code == 200


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


def test_live_setup_prompts_once_and_creates_first_owner(tmp_path, monkeypatch):
    prompts = iter(["owner@example.test"])
    passwords = iter(["a secure owner password", "a secure owner password"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(prompts))
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(passwords))

    assert setup_owner_if_needed(tmp_path / "data") is True
    connection = connect(tmp_path / "data" / "playroom.sqlite3")
    try:
        assert connection.execute("SELECT email FROM owners").fetchone()["email"] == "owner@example.test"
    finally:
        connection.close()


def test_live_setup_existing_owner_does_not_prompt_or_reset(tmp_path, monkeypatch):
    connection = connect(tmp_path / "data" / "playroom.sqlite3")
    migrate(connection)
    create_owner(connection, "owner@example.test", "a secure owner password")
    connection.close()
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("email prompt must not run"))
    monkeypatch.setattr("getpass.getpass", lambda prompt: pytest.fail("password prompt must not run"))

    assert setup_owner_if_needed(tmp_path / "data") is False
    connection = connect(tmp_path / "data" / "playroom.sqlite3")
    try:
        from playroom.auth import verify_owner_password
        assert verify_owner_password(connection, "owner@example.test", "a secure owner password").email == "owner@example.test"
    finally:
        connection.close()


@pytest.mark.parametrize("values", [("owner@example.test", "short", "short"), ("owner@example.test", "a secure owner password", "different password")])
def test_live_setup_invalid_or_mismatched_password_creates_no_owner(tmp_path, monkeypatch, values):
    prompts = iter([values[0]])
    passwords = iter(values[1:])
    monkeypatch.setattr("builtins.input", lambda prompt: next(prompts))
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(passwords))

    with pytest.raises(ValueError):
        setup_owner_if_needed(tmp_path / "data")
    connection = connect(tmp_path / "data" / "playroom.sqlite3")
    try:
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 0
    finally:
        connection.close()


def test_live_cli_dispatches_open_browser_mode(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *args, **kwargs: pytest.fail("run shortcut must not be used")))
    monkeypatch.setattr("playroom.live_local.serve_with_browser", lambda app, host, port: calls.append((app, host, port)))
    monkeypatch.setattr(sys, "argv", ["playroom-live-local", "--data-dir", str(tmp_path / "data"), "--frontend-dist", str(_dist(tmp_path)), "--port", "8123", "--open-browser"])

    main()

    assert calls and calls[0][1:] == ("127.0.0.1", 8123)


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _health_app():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def test_serve_with_browser_opens_only_after_real_health_and_stops_cleanly(monkeypatch):
    app = _health_app()
    opened = []
    opened_event = threading.Event()

    def open_browser(url):
        opened.append(url)
        opened_event.set()
        return True

    monkeypatch.setattr("webbrowser.open", open_browser)
    thread = threading.Thread(target=serve_with_browser, args=(app, "127.0.0.1", _free_port()), daemon=True)
    thread.start()
    assert opened_event.wait(timeout=5)
    time.sleep(6)
    assert thread.is_alive()
    app.state.local_server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert len(opened) == 1
    assert opened[0].endswith("/")


def test_serve_with_browser_rejects_occupied_port_without_opening(monkeypatch):
    import uvicorn

    port = _free_port()
    holder = uvicorn.Server(uvicorn.Config(_health_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=holder.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not holder.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert holder.started
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    try:
        with pytest.raises(RuntimeError, match="failed to start|did not become ready"):
            serve_with_browser(_health_app(), "127.0.0.1", port)
    finally:
        holder.should_exit = True
        thread.join(timeout=5)
    assert opened == []


def test_serve_with_browser_startup_failure_exits_without_waiting_full_timeout(monkeypatch):
    @asynccontextmanager
    async def failing_lifespan(app):
        raise RuntimeError("synthetic startup failure")
        yield

    app = FastAPI(lifespan=failing_lifespan)
    app.add_api_route("/health", lambda: {"status": "ok"}, methods=["GET"])
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="failed to start|did not become ready"):
        serve_with_browser(app, "127.0.0.1", _free_port())
    assert time.monotonic() - started < 5
    assert opened == []


def test_serve_with_browser_handles_keyboard_interrupt_during_join(monkeypatch):
    class FakeThread:
        def __init__(self, target, **kwargs):
            self.alive = True
            self.join_calls = 0

        def start(self):
            return None

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            self.join_calls += 1
            if self.join_calls == 1:
                raise KeyboardInterrupt
            self.alive = False

    class FakeServer:
        def __init__(self, config):
            self.started = True
            self.should_exit = False

        def run(self):
            return None

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("playroom.live_local.threading.Thread", FakeThread)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(Server=FakeServer, Config=lambda *args, **kwargs: object()))
    monkeypatch.setattr("playroom.live_local.urllib.request.urlopen", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr("webbrowser.open", lambda url: (_ for _ in ()).throw(KeyboardInterrupt))

    app = _health_app()
    serve_with_browser(app, "127.0.0.1", _free_port())
    assert app.state.local_server.should_exit is True


def test_serve_with_browser_cleans_server_when_browser_open_fails(monkeypatch):
    app = _health_app()
    opened = threading.Event()

    def fail_open(url):
        opened.set()
        raise RuntimeError("synthetic browser failure")

    monkeypatch.setattr("webbrowser.open", fail_open)
    errors = []

    def run():
        try:
            serve_with_browser(app, "127.0.0.1", _free_port())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert opened.wait(timeout=5)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert app.state.local_server.should_exit is True


def test_two_first_live_setup_attempts_leave_only_one_owner(tmp_path):
    barrier = threading.Barrier(2)
    outcomes = []

    def setup():
        def email(_):
            barrier.wait(timeout=5)
            return f"owner-{threading.current_thread().name}@example.test"

        try:
            outcomes.append(setup_owner_if_needed(tmp_path / "data", input_fn=email, password_fn=lambda _: "a secure owner password"))
        except BaseException as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=setup) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert len(outcomes) == 2
    assert all(isinstance(outcome, bool) for outcome in outcomes), outcomes
    assert sorted(outcomes, key=str) == [False, True]
    connection = connect(tmp_path / "data" / "playroom.sqlite3")
    try:
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 1
    finally:
        connection.close()


def test_concurrent_live_setup_tolerates_duplicate_column_migration(tmp_path, monkeypatch):
    migration_barrier = threading.Barrier(2)
    original_connect = connect

    class _ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection
            self._synchronized = False

        def execute(self, sql, parameters=()):
            if sql == "PRAGMA table_info(provider_attempts)" and not self._synchronized:
                rows = self._connection.execute(sql, parameters).fetchall()
                self._synchronized = True
                migration_barrier.wait(timeout=5)
                return rows
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def synchronized_connect(path):
        return _ConnectionProxy(original_connect(path))

    monkeypatch.setattr("playroom.live_local.connect", synchronized_connect)
    outcomes = []

    def setup():
        try:
            outcomes.append(
                setup_owner_if_needed(
                    tmp_path / "data",
                    input_fn=lambda _: f"owner-{threading.current_thread().name}@example.test",
                    password_fn=lambda _: "a secure owner password",
                )
            )
        except BaseException as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=setup) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(outcomes, key=str) == [False, True]


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
