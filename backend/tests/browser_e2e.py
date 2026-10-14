"""Real Chromium end-to-end smoke for opt-in synthetic Playroom.

Run only via the separate browser CI gate:
    uv run --with playwright==1.56.0 python backend/tests/browser_e2e.py

It serves the *built* React SPA from create_demo_app, uses loopback only,
and cannot invoke real providers. No user data or API credentials are used.
"""
from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

import uvicorn
from playwright.sync_api import expect, sync_playwright

from playroom.demo import create_demo_app


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


def _assert_mobile(page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    page.get_by_role("button", name="Gửi", exact=True).scroll_into_view_if_needed()
    expect(page.get_by_role("button", name="Gửi", exact=True)).to_be_visible()
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"Horizontal overflow at {width}px: {overflow}px"
    if width == 390:
        page.get_by_role("button", name="Chiến dịch", exact=True).click()
        dialog = page.get_by_role("dialog", name="Danh sách chiến dịch")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
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
                page.get_by_role("button", name="Gửi", exact=True).click()
                expect(page.locator(".story-turn")).to_have_count(4, timeout=25000)
                assert len(campaign.calls) == 4

                final = _project(page, origin, campaign_id, branch_id)
                assert len(final["transcript"]) == 4
                assert all(t["narrative_text"] == NARRATION for t in final["transcript"])
                assert len({t["revision_id"] for t in final["transcript"]}) == 4
                assert not outbound, f"Demo browser attempted non-loopback requests: {outbound}"
                for width in (360, 390, 430):
                    _assert_mobile(page, width)

                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(4)
                assert len(campaign.calls) == 4
                assert not any(k.startswith("playroom:generation:") for k in page.evaluate("Object.keys(localStorage)"))
                browser.close()
                print("B3 Chromium synthetic: four committed turns, reload/reconnect, 422 recovery, 360/390/430 mobile PASS")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Demo server failed to shut down")


if __name__ == "__main__":
    browser_synthetic_chat()
