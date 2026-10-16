"""Real Chromium end-to-end smoke for opt-in synthetic Playroom.

Run only via the separate browser CI gate:
    uv run --with playwright==1.56.0 python backend/tests/browser_e2e.py

It serves the *built* React SPA from create_demo_app, uses loopback only,
and cannot invoke real providers. No user data or API credentials are used.
"""
from __future__ import annotations

import json
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import uvicorn
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect, sync_playwright

from playroom.demo import create_demo_app
from playroom.provider import ProviderResult


REPO = Path(__file__).resolve().parents[2]
EMAIL = "synthetic-b3@example.test"
PASSWORD = "synthetic fixture password only"
NARRATION = "Ánh sáng dịu lan qua căn phòng, và câu chuyện tiếp tục mở ra."


def _free_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_demo(data_dir: Path):
    dist = REPO / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("Build frontend first: npm ci && npm run build")
    app, _ = create_demo_app(data_dir, email=EMAIL, password=PASSWORD, frontend_dist=dist)
    port = _free_loopback_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("Demo server exited unexpectedly")
        try:
            with urlopen(f"{origin}/health", timeout=1) as response:
                if response.status == 200:
                    return app, server, thread, origin
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Demo server failed its loopback health check")


def _start_live_local(data_dir: Path):
    """Start the real local assembly with a test-only provider override."""
    dist = REPO / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise RuntimeError("Build frontend first: npm ci && npm run build")

    # Keep this import lazy so importing this legacy browser script does not
    # require the new assembly while its backend module is being assembled.
    from playroom.live_local import create_live_local_app
    from playroom.provider import default_provider_factory

    app = create_live_local_app(data_dir, frontend_dist=dist)
    assert app.state.generation_provider is None
    assert app.state.generation_provider_factory is default_provider_factory

    # Install only the synthetic owner/profile used by this browser gate. The
    # real local assembly remains the code under test; the fake is injected
    # before Uvicorn enters the app lifespan and never reaches production code.
    from playroom.demo import DemoFakeProvider, _ensure_install

    _ensure_install(data_dir, EMAIL, PASSWORD)
    campaign_provider = DemoFakeProvider()
    app.state.generation_provider = campaign_provider
    app.state.generation_provider_factory = None

    port = _free_loopback_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("Live local server exited unexpectedly")
        try:
            with urlopen(f"{origin}/health", timeout=1) as response:
                if response.status == 200:
                    return app, campaign_provider, server, thread, origin
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Live local server failed its loopback health check")


def _send_and_wait(page, action: str, expected_turns: int) -> None:
    compose = page.get_by_role("textbox", name="Hành động tiếp theo")
    compose.fill(action)
    page.get_by_role("button", name="Gửi", exact=True).click()
    expect(page.locator(".story-turn")).to_have_count(expected_turns, timeout=25000)
    expect(compose).to_have_value("", timeout=12000)


def _project(page, origin: str, campaign_id: str, branch_id: str) -> dict:
    response = page.context.request.get(
        f"{origin}/api/campaigns/{campaign_id}/projection",
        params={"branch_id": branch_id},
    )
    assert response.ok, f"Projection HTTP {response.status}"
    return response.json()


def _print_generation_diagnostics(page, origin: str, campaign_id: str, branch_id: str, campaign_calls: list[dict]) -> None:
    """Print redacted state only when a browser gate assertion fails."""
    try:
        projection = _project(page, origin, campaign_id, branch_id)
        jobs = [{"id": job.get("id"), "status": job.get("status"), "attempt_counts_by_stage": job.get("attempt_counts_by_stage")} for job in projection.get("jobs", [])]
    except Exception as cause:
        jobs = [{"diagnostic_error": type(cause).__name__}]
    alerts = page.locator("[role=alert]").all_text_contents()
    compose = page.locator("#generation-action")
    send = page.locator(".generation-composer button[type=submit]")
    print(json.dumps({"jobs": jobs, "alerts": alerts, "composer": {"visible": compose.is_visible(), "value_length": len(compose.input_value())}, "send_disabled": send.is_disabled(), "provider_call_count": len(campaign_calls)}, ensure_ascii=False))


def _assert_mobile(page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    page.get_by_role("button", name="Gửi", exact=True).scroll_into_view_if_needed()
    expect(page.get_by_role("button", name="Gửi", exact=True)).to_be_visible()
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"Horizontal overflow at {width}px: {overflow}px"
    # The current responsive UI uses the topbar campaign select; the
    # legacy mobile-campaign drawer button is intentionally hidden in CSS.
    expect(page.get_by_role("combobox", name="Chiến dịch hiện tại")).to_be_visible()
    if width == 390:
        page.get_by_role("button", name="AI đang nhớ gì").click()
        details = page.get_by_role("dialog", name="Hồ sơ và ký ức")
        expect(details).to_be_visible()
        page.get_by_role("button", name="Đóng hồ sơ và ký ức").click()
        expect(details).not_to_be_visible()


def browser_synthetic_chat() -> None:
    with tempfile.TemporaryDirectory(prefix="playroom-b3-") as tmp:
        app, server, thread, origin = _start_demo(Path(tmp))
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(
                    viewport={"width": 390, "height": 780},
                    reduced_motion="reduce",
                    locale="vi-VN",
                )
                page = context.new_page()
                outbound = []
                page.on("request", lambda r: outbound.append(r.url) if not r.url.startswith(origin) else None)
                page.goto(origin, wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name="Đăng nhập Playroom")).to_be_visible()
                page.get_by_label("Email").fill(EMAIL)
                page.get_by_label("Mật khẩu").fill(PASSWORD)
                page.get_by_role("button", name="Đăng nhập").click()
                page.get_by_role("button", name="Tạo chiến dịch đầu tiên").click()
                page.get_by_label("Tên chiến dịch").fill("Thử nghiệm sân bóng")
                page.get_by_label("Tên thế giới").fill("Trường Bangtan")
                page.get_by_label("Tên persona").fill("Henn")
                page.get_by_role("button", name="Thêm nhân vật").click()
                page.get_by_label("Tên nhân vật 1").fill("Yuna")
                page.get_by_role("button", name="Lưu chiến dịch").click()

                expect(page.get_by_role("heading", name="Thử nghiệm sân bóng")).to_be_visible(timeout=15000)
                expect(page.get_by_role("button", name="Gửi", exact=True)).to_have_count(1)
                expect(page.get_by_text("Chế độ demo tổng hợp")).to_be_visible()
                expect(page.get_by_text("Dùng **...** cho hành động hoặc suy nghĩ;", exact=False)).to_be_visible()
                campaign = app.state.generation_provider
                assert campaign.stage_counts == {}
                camp_list = page.context.request.get(f"{origin}/api/campaigns").json()
                assert len(camp_list) == 1
                campaign_id = camp_list[0]["id"]
                detail = page.context.request.get(f"{origin}/api/campaigns/{campaign_id}").json()
                branch_id = detail["branch_id"]

                # IME composition must never submit early. Shift+Enter is
                # reserved for inserting an in-field newline, not Send.
                compose = page.get_by_role("textbox", name="Hành động tiếp theo")
                compose.fill("Đang nhập tiếng Việt")
                compose.evaluate(
                    "(el) => el.dispatchEvent(new KeyboardEvent('keydown', "
                    "{key: 'Enter', bubbles: true, cancelable: true, isComposing: true}))"
                )
                assert not app.state.generation_provider.calls
                compose.fill("Mở dòng mới")
                compose.press("Shift+Enter")
                assert compose.input_value().endswith("\n")
                assert not app.state.generation_provider.calls

                # Real DOM->POST->queue->fake worker->commit->projection cycle.
                first = "Yuna, sẵn sàng chưa?\n**Henn chỉnh băng đô 💙**"
                _send_and_wait(page, first, 1)
                transcript = _project(page, origin, campaign_id, branch_id)["transcript"]
                assert len(transcript) == 1
                assert transcript[0]["input_segments"] == [
                    {"kind": "dialogue", "text": "Yuna, sẵn sàng chưa?\n"},
                    {"kind": "action", "text": "Henn chỉnh băng đô 💙"},
                ]
                assert transcript[0]["narrative_text"] == NARRATION
                assert len(campaign.calls) == 1
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(1)
                assert len(campaign.calls) == 1

                _send_and_wait(page, "Tớ đợi cậu ở vạch sân.", 2)
                assert len(campaign.calls) == 2

                # A POST can reach the server before the browser loses its
                # response. The client must recover the *same* durable job.
                intercepted = {"count": 0}
                def drop_post(route):
                    intercepted["count"] += 1
                    response = route.fetch()
                    assert response.status == 201
                    route.abort("failed")
                page.route("**/api/campaigns/*/generate", drop_post, times=1)
                _send_and_wait(page, "**Henn gật đầu**", 3)
                assert intercepted["count"] == 1
                assert len(campaign.calls) == 3

                # Definite rejection has no reserved job and must not block
                # the next *explicit* Send; no automatic paid retry.
                def reject_once(route):
                    route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "Rejected before reservation"}))
                page.route("**/api/campaigns/*/generate", reject_once, times=1)
                draft = "Chúng ta cùng bắt đầu."
                page.get_by_role("textbox", name="Hành động tiếp theo").fill(draft)
                page.get_by_role("button", name="Gửi", exact=True).click()
                expect(page.get_by_role("alert")).to_be_visible(timeout=10000)
                expect(page.get_by_role("textbox", name="Hành động tiếp theo")).to_have_value(draft)
                assert len(campaign.calls) == 3
                _send_and_wait(page, draft, 4)
                assert len(campaign.calls) == 4

                # A rejected stale checkpoint (409) followed by by-key 404
                # is a definite pre-reservation conflict: reload authority,
                # retain player input, await a *new explicit* Send.
                def stale_once(route):
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Generation checkpoint is stale"}))
                page.route("**/api/campaigns/*/generate", stale_once, times=1)
                fifth = "Cậu thấy lượt bóng vừa rồi chứ?"
                compose.fill(fifth)
                page.get_by_role("button", name="Gửi", exact=True).click()
                try:
                    expect(page.get_by_text("Tác vụ đã thay đổi.", exact=False)).to_be_visible(timeout=12000)
                except (PlaywrightTimeoutError, AssertionError):
                    _print_generation_diagnostics(page, origin, campaign_id, branch_id, campaign.calls)
                    raise
                expect(compose).to_have_value(fifth)
                assert len(campaign.calls) == 4
                _send_and_wait(page, fifth, 5)
                assert len(campaign.calls) == 5

                # The candidate may be committed but the parent projection
                # refresh can fail. The same job must be retried for commit,
                # never paid/reserved as another generation.
                def fail_projection_once(route):
                    route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "Synthetic refresh outage"}))
                page.route("**/api/campaigns/*/projection*", fail_projection_once, times=1)
                sixth = "Cứ tiếp tục thôi, Yuna."
                compose.fill(sixth)
                page.get_by_role("button", name="Gửi", exact=True).click()
                expect(page.get_by_text("Không thể lưu lượt kể hoàn chỉnh", exact=False)).to_be_visible(timeout=20000)
                expect(compose).to_have_value(sixth)
                assert len(campaign.calls) == 6
                # A retried commit of the same candidate only refreshes UI.
                page.get_by_role("button", name="Gửi", exact=True).click()
                expect(page.locator(".story-turn")).to_have_count(6, timeout=25000)
                assert len(campaign.calls) == 6

                final = _project(page, origin, campaign_id, branch_id)
                assert len(final["transcript"]) == 6
                assert all(t["narrative_text"] == NARRATION for t in final["transcript"])
                assert len({t["revision_id"] for t in final["transcript"]}) == 6
                assert not outbound, f"Demo browser attempted non-loopback requests: {outbound}"
                for width in (360, 390, 430):
                    _assert_mobile(page, width)

                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(6)
                assert len(campaign.calls) == 6
                default_generate_text = campaign.generate_text
                assert not any(k.startswith("playroom:generation:") for k in page.evaluate("Object.keys(localStorage)"))
                # The live frontend should also render *attributed* NPC
                # dialogue. Seed a scene through the authenticated fake-only
                # API, then use a deterministic structured fake narrator with
                # exactly the selected character/profile version from context.
                yuna_key = next(key for key in final["profiles"] if key.startswith("character:"))
                yuna_id = yuna_key.partition(":")[2]
                scene_id = str(uuid4())
                scene_update = page.context.request.put(
                    f"{origin}/api/campaigns/{campaign_id}/scene",
                    headers={"origin": origin, "content-type": "application/json"},
                    data=json.dumps({
                        "branch_id": branch_id,
                        "expected_state_version": final["branch"]["state_version"],
                        "scene_state": {
                            "focus_scene_id": scene_id,
                            "scenes": [{"id": scene_id, "present_ids": [yuna_id]}],
                        },
                    }),
                )
                assert scene_update.ok, f"Seed scene HTTP {scene_update.status}: {scene_update.text()}"
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(6)
                chosen_versions = []

                def attributed_fake_narrator(request):
                    content = json.loads(request["messages"][1]["content"])
                    selected = [actor for actor in content["selected_characters"] if actor["character_id"] == yuna_id]
                    assert len(selected) == 1 and selected[0]["present"] is True, content["selected_characters"]
                    version_id = selected[0]["profile_version_id"]
                    chosen_versions.append(version_id)
                    narrative = json.dumps({"segments": [
                        {"kind": "narration", "text": "Yuna chờ bên lưới."},
                        {"kind": "dialogue", "text": "Tớ ở đây.", "character_id": yuna_id, "profile_version_id": version_id},
                    ]}, ensure_ascii=False)
                    campaign.calls.append({key: value for key, value in request.items() if key != "cancel_event"})
                    campaign.stage_counts["narration"] = campaign.stage_counts.get("narration", 0) + 1
                    yield narrative
                    yield ProviderResult(
                        text=narrative,
                        usage={"input_tokens": 24, "output_tokens": 16, "total_tokens": 40},
                        finish_reason="stop",
                    )

                campaign.generate_text = attributed_fake_narrator
                _send_and_wait(page, "Yuna, cậu ở đâu?", 7)
                expect(page.locator(".story-turn").last.locator(".roleplay-segment.dialogue strong")).to_have_text("Yuna: ", timeout=12000)
                npc_transcript = _project(page, origin, campaign_id, branch_id)["transcript"]
                assert len(npc_transcript) == 7
                assert npc_transcript[-1]["output_segments"] == [
                    {"kind": "narration", "text": "Yuna chờ bên lưới."},
                    {"kind": "dialogue", "text": "Tớ ở đây.", "character_id": yuna_id, "profile_version_id": chosen_versions[0]},
                ]
                assert len(campaign.calls) == 7 and len(chosen_versions) == 1
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(7)
                assert len(campaign.calls) == 7

                # The imported Lan/Vy campaign has a different cast. Restore
                # the generic synthetic narrator before exercising its Send;
                # the Yuna-specific fixture above must not leak across campaigns.
                campaign.generate_text = default_generate_text

                # Task 7A: import ONLY a chosen synthetic ChatGPT thread,
                # with an alternate assistant branch excluded from the active path.
                sample = {
                    "id": "chatgpt-fixture-1", "title": "Nhập thử từ ChatGPT",
                    "mapping": {
                        "root": {"parent": None, "message": None},
                        "u1": {"parent": "root", "message": {"id": "u1", "author": {"role": "user"}, "recipient": "all", "content": {"content_type": "text", "parts": ["*Lan mở hộp.*"]}}},
                        "alt": {"parent": "u1", "message": {"id": "alt", "author": {"role": "assistant"}, "recipient": "all", "content": {"content_type": "text", "parts": ["ALT NOT SELECTED"]}}},
                        "a1": {"parent": "u1", "message": {"id": "a1", "author": {"role": "assistant"}, "recipient": "all", "content": {"content_type": "text", "parts": ["Vy đứng cạnh quầy."]}}},
                        "u2": {"parent": "a1", "message": {"id": "u2", "author": {"role": "user"}, "recipient": "all", "content": {"content_type": "text", "parts": ['"Vy, cậu đã thấy chưa?"']}}},
                        "a2": {"parent": "u2", "message": {"id": "a2", "author": {"role": "assistant"}, "recipient": "all", "content": {"content_type": "text", "parts": ["Vy gật đầu. 💙"]}}},
                    }, "current_node": "a2",
                }
                page.get_by_role("button", name="Nhập ChatGPT").click()
                page.get_by_label("Tệp xuất từ ChatGPT").set_input_files({
                    "name": "conversations.json", "mimeType": "application/json",
                    "buffer": json.dumps([sample], ensure_ascii=False).encode("utf-8"),
                })
                expect(page.get_by_text("Đã đọc 1 cuộc hội thoại", exact=False)).to_be_visible()
                page.get_by_role("button", name="Xem trước thread này").click()
                expect(page.get_by_text("Tìm thấy", exact=False)).to_be_visible()
                page.get_by_label("Tôi đã xem đúng thread", exact=False).check()
                page.get_by_role("button", name="Nhập và mở chiến dịch").click()
                expect(page.get_by_role("heading", name="Nhập thử từ ChatGPT")).to_be_visible(timeout=12000)
                expect(page.locator(".story-turn")).to_have_count(2, timeout=12000)
                # Imported history remains locked until the separate review checkpoint.
                expect(page.locator(".generation-composer")).to_have_count(0)
                campaigns_after_import = page.context.request.get(f"{origin}/api/campaigns").json()
                imported = next(c for c in campaigns_after_import if c["title"] == "Nhập thử từ ChatGPT")
                detail_imported = page.context.request.get(f"{origin}/api/campaigns/{imported['id']}").json()
                imported_text = _project(page, origin, imported["id"], detail_imported["branch_id"])["transcript"]
                assert len(imported_text) == 2
                assert imported_text[0]["action_text"] == "*Lan mở hộp.*"
                assert imported_text[-1]["narrative_text"] == "Vy gật đầu. 💙"
                assert all("ALT NOT SELECTED" not in t["narrative_text"] for t in imported_text)
                assert len(campaign.calls) == 7, "Import must never call the model"
                locked_projection = _project(page, origin, imported["id"], detail_imported["branch_id"])
                crafted = page.context.request.post(f"{origin}/api/campaigns/{imported['id']}/generate", data=json.dumps({
                    "branch_id": detail_imported["branch_id"], "action": "*Lan quan sát.*",
                    "idempotency_key": str(uuid4()), "checkpoint_id": locked_projection["branch"]["checkpoint_id"],
                }), headers={"content-type": "application/json", "origin": origin})
                assert crafted.status == 409
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".generation-composer")).to_have_count(0)
                checks = page.locator(".create-card input[type=checkbox]")
                expect(checks).to_have_count(4)
                for index in range(4):
                    checks.nth(index).check()
                page.get_by_role("button", name=re.compile("Duy.*Send")).click()
                expect(page.locator(".generation-composer")).to_be_visible(timeout=12000)
                _send_and_wait(page, "*Lan mỉm cười.*", 3)
                expect(page.locator(".story-turn")).to_have_count(3, timeout=12000)
                assert len(campaign.calls) == 8
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".generation-composer")).to_be_visible(timeout=12000)
                _assert_mobile(page, 360)
                browser.close()
                print("B3 Chromium synthetic: seven committed turns, attributed NPC/version, reload/reconnect, 409/422/refresh recovery, IME and 360/390/430 mobile PASS; selected ChatGPT JSON import PASS")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Demo server failed to shut down")


def browser_live_local_chat() -> None:
    """Exercise the real local assembly through a built React frontend."""
    with tempfile.TemporaryDirectory(prefix="playroom-live-local-") as tmp:
        app, campaign, server, thread, origin = _start_live_local(Path(tmp))
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    reduced_motion="reduce",
                    locale="vi-VN",
                )
                page = context.new_page()
                page.goto(origin, wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name="Đăng nhập Playroom")).to_be_visible()
                page.get_by_label("Email").fill(EMAIL)
                page.get_by_label("Mật khẩu").fill(PASSWORD)
                page.get_by_role("button", name="Đăng nhập").click()
                page.get_by_role("button", name="Tạo chiến dịch đầu tiên").click()
                page.get_by_label("Tên chiến dịch").fill("Lan Vy Binh local")
                page.get_by_label("Tên thế giới").fill("Thế giới tổng hợp")
                page.get_by_label("Tên persona").fill("Bình")
                page.get_by_role("button", name="Thêm nhân vật").click()
                page.get_by_label("Tên nhân vật 1").fill("Lan")
                page.get_by_role("button", name="Lưu chiến dịch").click()

                expect(page.get_by_role("heading", name="Lan Vy Binh local")).to_be_visible(timeout=15000)
                send = page.locator(".generation-composer button[type=submit]")
                expect(send).to_have_count(1)
                campaigns = page.context.request.get(f"{origin}/api/campaigns")
                assert campaigns.ok
                campaign_id = campaigns.json()[0]["id"]
                detail = page.context.request.get(f"{origin}/api/campaigns/{campaign_id}").json()
                branch_id = detail["branch_id"]

                compose = page.locator("#generation-action")
                compose.fill("Lan, Vy v\u00e0 B\u00ecnh c\u00f9ng quan s\u00e1t.")
                send.click()
                expect(page.locator(".story-turn")).to_have_count(1, timeout=25000)
                expect(compose).to_have_value("", timeout=12000)
                projection = _project(page, origin, campaign_id, branch_id)
                assert len(projection["transcript"]) == 1
                assert projection["transcript"][0]["narrative_text"] == NARRATION
                assert len(campaign.calls) == 1

                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(1)
                assert len(campaign.calls) == 1
                assert _project(page, origin, campaign_id, branch_id)["transcript"]
                browser.close()
                print("Live local Chromium: real assembly, one manual fake Send, committed projection and reload persistence PASS")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Live local server failed to shut down")


if __name__ == "__main__":
    browser_synthetic_chat()
    browser_live_local_chat()
