from fastapi.testclient import TestClient

from playroom.demo import DemoFakeProvider, create_demo_app, main
from playroom.app import create_app
from playroom.provider import default_provider_factory
import time
import json
from pathlib import Path


def test_demo_fake_provider_is_repeatable_for_multiple_plays():
    provider = DemoFakeProvider()
    first = list(provider.generate_text({"stage": "narration", "action": "Mở cửa"}))
    second = list(provider.generate_text({"stage": "narration", "action": "Mở cửa"}))
    assert first[-1].text == second[-1].text
    assert provider.stage_counts["narration"] == 2


def test_demo_fake_provider_reads_action_from_narration_request_messages():
    provider = DemoFakeProvider()
    request = {
        "stage": "narration",
        "messages": [
            {"role": "system", "content": "Continue the story."},
            {"role": "user", "content": json.dumps({"action": "Mở cánh cửa bí mật"}, ensure_ascii=False)},
        ],
    }

    result = list(provider.generate_text(request))[-1]

    assert "Mở cánh cửa bí mật" in result.text


def test_demo_fake_provider_preserves_free_form_action_sentence_formatting():
    provider = DemoFakeProvider()
    request = {
        "stage": "narration",
        "messages": [
            {"role": "system", "content": "Continue the story."},
            {"role": "user", "content": json.dumps({"action": "Mina hums the melody."})},
        ],
    }

    result = list(provider.generate_text(request))[-1]

    assert result.text.startswith("Mina hums the melody. ")
    assert "Mina hums the melody.." not in result.text
    assert "Bạn " not in result.text


def test_demo_rejects_non_loopback_bind_host(tmp_path, monkeypatch):
    import sys
    import types

    monkeypatch.setattr(sys, "argv", ["playroom-demo", "--data-dir", str(tmp_path), "--host", "0.0.0.0", "--password", "a secure demo password"])
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *args, **kwargs: None))

    import pytest

    with pytest.raises(ValueError, match="loopback"):
        main()


def test_pwa_manifest_declares_installable_icon_sizes():
    manifest = json.loads((Path(__file__).parents[2] / "frontend" / "public" / "manifest.webmanifest").read_text(encoding="utf-8"))
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"}.issubset(sizes)


def test_demo_first_install_creates_owner_and_survives_restart(tmp_path):
    app, install = create_demo_app(tmp_path, email="demo@example.test", password="a secure demo password")
    assert install.created is True
    client = TestClient(app, base_url="http://127.0.0.1")
    login = client.post("/api/auth/login", json={"email": install.email, "password": "a secure demo password"}, headers={"origin": "http://127.0.0.1"})
    assert login.status_code == 200
    assert client.get("/api/demo/info").json()["mode"] == "synthetic"
    app2, install2 = create_demo_app(tmp_path, email="demo@example.test", password="a secure demo password")
    assert install2.created is False
    client2 = TestClient(app2, base_url="http://127.0.0.1")
    assert client2.post("/api/auth/login", json={"email": install2.email, "password": "a secure demo password"}, headers={"origin": "http://127.0.0.1"}).status_code == 200


def test_demo_generated_first_password_is_random_and_login_capable(tmp_path):
    first_app, first = create_demo_app(tmp_path / "first", email="one@example.test")
    second_app, second = create_demo_app(tmp_path / "second", email="two@example.test")
    assert first.created and second.created
    assert first.password and len(first.password) >= 12
    assert second.password and len(second.password) >= 12
    assert first.password != second.password
    for app, install in ((first_app, first), (second_app, second)):
        response = TestClient(app, base_url="http://127.0.0.1").post("/api/auth/login", json={"email": install.email, "password": install.password}, headers={"origin": "http://127.0.0.1"})
        assert response.status_code == 200


def test_demo_serves_built_spa_and_manifest_same_origin(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "icons").mkdir()
    (dist / "index.html").write_text("<html>demo</html>", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name":"demo"}', encoding="utf-8")
    (dist / "icons" / "playroom.svg").write_text("<svg/>", encoding="utf-8")
    app, _ = create_demo_app(tmp_path / "data", frontend_dist=dist)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/").text == "<html>demo</html>"
    assert client.get("/manifest.webmanifest").json()["name"] == "demo"
    assert client.get("/icons/playroom.svg").status_code == 200


def test_demo_missing_frontend_is_an_explicit_setup_error(tmp_path):
    app, _ = create_demo_app(tmp_path, email="demo@example.test", password="a secure demo password", frontend_dist=tmp_path / "missing")
    response = TestClient(app, base_url="http://127.0.0.1").get("/")
    assert response.status_code == 503
    assert "frontend" in response.json()["detail"].lower()


def test_production_factory_remains_real_provider_default(tmp_path):
    app = create_app(database_url=str(tmp_path / "production.sqlite3"), allowed_hosts={"testserver"})
    assert app.state.generation_provider is None
    assert app.state.generation_provider_factory is default_provider_factory
    assert app.state.secure_cookies is True


def test_demo_play_loop_uses_one_fake_dispatch_and_persists_transcript(tmp_path):
    app, install = create_demo_app(tmp_path, email="demo@example.test", password="a secure demo password")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"origin": "http://127.0.0.1"}
        assert client.post("/api/auth/login", json={"email": install.email, "password": "a secure demo password"}, headers=headers).status_code == 200
        campaign = client.post("/api/campaigns", json={"title": "Demo", "world": {"name": "Thế giới"}, "persona": {"name": "Tôi"}}, headers=headers).json()
        detail = client.get(f"/api/campaigns/{campaign['id']}").json()
        preview = client.post(f"/api/campaigns/{campaign['id']}/context/previews", json={"branch_id": campaign["branch_id"], "action": "Mở cửa", "profile_id": "demo-narrator"}, headers=headers)
        assert preview.status_code == 201, preview.text
        key = "demo-play-once"
        response = client.post(f"/api/campaigns/{campaign['id']}/generate", json={"branch_id": campaign["branch_id"], "action": "Mở cửa", "idempotency_key": key, "checkpoint_id": detail["checkpoint_id"], "preview_id": preview.json()["id"], "mode": "economy", "policy": "free_only"}, headers=headers)
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        for _ in range(40):
            job = client.get(f"/api/generation/jobs/{job_id}").json()
            if job["status"] in {"candidate", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert job["status"] == "candidate", job
        assert job["draft"]
        committed = client.post(f"/api/generation/jobs/{job_id}/commit", headers=headers)
        assert committed.status_code == 200, committed.text
        assert app.state.generation_provider.stage_counts == {"narration": 1}
        assert len(app.state.generation_provider.calls) == 1
        projection = client.get(f"/api/campaigns/{campaign['id']}/projection?branch_id={campaign['branch_id']}").json()
        assert projection["transcript"][-1]["narrative_text"] == job["draft"]
        assert len(projection["transcript"]) == 1
    app2, install2 = create_demo_app(tmp_path, email="demo@example.test", password="a secure demo password")
    with TestClient(app2, base_url="http://127.0.0.1") as client2:
        headers = {"origin": "http://127.0.0.1"}
        assert client2.post("/api/auth/login", json={"email": install2.email, "password": "a secure demo password"}, headers=headers).status_code == 200
        campaigns = client2.get("/api/campaigns").json()
        assert len(campaigns) == 1 and campaigns[0]["id"] == campaign["id"]
        restored = client2.get(f"/api/campaigns/{campaign['id']}/projection?branch_id={campaign['branch_id']}").json()
        assert restored["transcript"][-1]["narrative_text"] == job["draft"]
