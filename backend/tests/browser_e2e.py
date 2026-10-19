"""Real Chromium end-to-end smoke for opt-in synthetic Playroom.

Run only via the separate browser CI gate:
    uv run --with playwright==1.56.0 python backend/tests/browser_e2e.py

It serves the *built* React SPA from create_demo_app, uses loopback only,
and cannot invoke real providers. No user data or API credentials are used.
"""
from __future__ import annotations

import json
import io
import re
import socket
import tempfile
import threading
import time
import zipfile
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


class _BoundedASGIObserver:
    """Test-only ASGI boundary trace that delegates the app unchanged."""

    def __init__(self, app, limit: int = 100):
        self.app = app
        self.limit = limit
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._started = time.monotonic()

    def _record(self, kind: str, scope, **fields: object) -> None:
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/"):
            return
        event = {"ms": round((time.monotonic() - self._started) * 1000),
                 "kind": kind, "method": scope.get("method"),
                 "path": scope.get("path"), **fields}
        with self._lock:
            if len(self.events) >= self.limit:
                self.events.pop(0)
            self.events.append(event)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    async def __call__(self, scope, receive, send):
        self._record("request_enter", scope)

        async def observed_send(message):
            message_type = message.get("type")
            if message_type == "http.response.start":
                self._record("response_start", scope, status=message.get("status"))
            elif message_type == "http.response.body" and not message.get("more_body", False):
                self._record("response_body_final", scope)
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except Exception as cause:
            self._record("exception", scope, exception_type=type(cause).__name__)
            raise
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
    observer = _BoundedASGIObserver(app)
    app.state.browser_asgi_observer = observer
    port = _free_loopback_port()
    server = uvicorn.Server(uvicorn.Config(observer, host="127.0.0.1", port=port, log_level="error"))
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


def _redact_browser_url(url: str) -> str:
    return re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,36}", "<uuid>", url)


def _print_generation_diagnostics(page, origin: str, campaign_id: str, branch_id: str, campaign_calls: list[dict], trace_events: list[dict], stale_route_hits: int, server_events=None) -> None:
    """Print redacted state only when a browser gate assertion fails."""
    direct_probe = None
    try:
        receipts_for_probe = page.evaluate("""() => Object.keys(localStorage).filter((key) => key.startsWith('playroom:generation:')).map((key) => {
          try { const value = JSON.parse(localStorage.getItem(key) || '{}'); return { branchId: key.split(':').at(-1), idempotencyKey: value.idempotencyKey }; } catch { return null; }
        }).filter(Boolean)""")
        probe_receipt = next((receipt for receipt in receipts_for_probe if receipt.get("branchId") == branch_id and receipt.get("idempotencyKey")), None)
        if probe_receipt:
            response = page.context.request.get(
                f"{origin}/api/generation/jobs/by-key",
                params={"branch_id": branch_id, "idempotency_key": probe_receipt["idempotencyKey"]},
            )
            direct_probe = {"status": response.status, "ok": response.ok}
        else:
            direct_probe = {"status": None, "ok": None, "error": "no_receipt"}
    except Exception as cause:
        direct_probe = {"error": type(cause).__name__}
    try:
        projection = _project(page, origin, campaign_id, branch_id)
        jobs = []
        for job in projection.get("jobs", []):
            detail = page.context.request.get(f"{origin}/api/generation/jobs/{job.get('id')}")
            detail_json = detail.json() if detail.ok else {}
            jobs.append({"id": job.get("id"), "status": job.get("status"),
                         "attempt_counts_by_stage": job.get("attempt_counts_by_stage"),
                         "failure": detail_json.get("failure")})
    except Exception as cause:
        jobs = [{"diagnostic_error": type(cause).__name__}]
    alerts = page.locator("[role=alert]").all_text_contents()
    compose = page.locator("#generation-action")
    send = page.locator(".generation-composer button[type=submit]")
    receipts = page.evaluate("""() => Object.keys(localStorage).filter((key) => key.startsWith('playroom:generation:')).map((key) => {
      try {
        const value = JSON.parse(localStorage.getItem(key) || '{}');
        const match = key.match(/^playroom:generation:[^:]+:([^:]+):([^:]+)$/);
        return { key: key.replace(/playroom:generation:[^:]+:/, 'playroom:generation:<owner>:'), campaignId: match?.[1], branchId: match?.[2], checkpointId: value.checkpointId, previewId: value.previewId, jobId: value.jobId, actionLength: typeof value.action === 'string' ? value.action.length : null };
      } catch { return { key: '<unparseable>' }; }
    })""")
    preview_budget = None
    campaign_receipts = [receipt for receipt in receipts if receipt.get("campaignId") == campaign_id and receipt.get("branchId") == branch_id]
    for receipt in campaign_receipts:
        preview_id = receipt.get("previewId")
        if not preview_id:
            continue
        preview_response = page.context.request.get(f"{origin}/api/context/previews/{preview_id}")
        if preview_response.ok:
            preview = preview_response.json()
            budget = preview.get("budget") or {}
            preview_budget = {"status": preview.get("status"), "failure": preview.get("failure"),
                              "input_tokens": budget.get("input_tokens"), "input_cap": budget.get("input_cap"),
                              "context_window": budget.get("context_window"), "output_reserve": budget.get("output_reserve")}
            break
    details = page.locator(".generation-details")
    server_trace = server_events.snapshot() if hasattr(server_events, "snapshot") else (server_events or [])
    print(json.dumps({"jobs": jobs, "preview_budget": preview_budget, "alerts": alerts, "composer": {"visible": compose.is_visible(), "value_length": len(compose.input_value())}, "send": {"disabled": send.is_disabled(), "text": send.inner_text()}, "generation_details": details.all_text_contents(), "receipts": receipts, "provider_call_count": len(campaign_calls), "stale_route_hits": stale_route_hits, "browser_trace": trace_events, "server_trace": server_trace, "direct_by_key_probe": direct_probe}, ensure_ascii=True))


def _assert_mobile(page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 780})
    page.get_by_role("button", name="Gửi", exact=True).scroll_into_view_if_needed()
    expect(page.get_by_role("button", name="Gửi", exact=True)).to_be_visible()
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"Horizontal overflow at {width}px: {overflow}px"
    # The current responsive UI uses the topbar campaign select; the
    # legacy mobile-campaign drawer button is intentionally hidden in CSS.
    expect(page.get_by_role("combobox", name="Truyện hiện tại")).to_be_visible()
    if width == 390:
        page.get_by_role("button", name="AI đang nhớ gì").click()
        details = page.get_by_role("dialog", name="Hồ sơ và ký ức")
        expect(details).to_be_visible()
        page.get_by_role("button", name="Đóng hồ sơ và ký ức").click()
        expect(details).not_to_be_visible()


def _browser_zip_conversations() -> bytes:
    def message(message_id: str, role: str, text: str) -> dict:
        return {"id": message_id, "author": {"role": role}, "recipient": "all",
                "content": {"content_type": "text", "parts": [text]}}

    mapping = {"root": {"id": "root", "parent": None, "message": None}}
    parent = "root"
    for index in range(125):
        user_id = f"zip-user-{index:03d}-é"
        assistant_id = f"zip-assistant-{index:03d}-☃"
        mapping[user_id] = {"id": user_id, "parent": parent, "message": message(
            user_id, "user", f"ZIP người chơi {index:03d}\nDòng phụ {index:03d}")}
        mapping[assistant_id] = {"id": assistant_id, "parent": user_id, "message": message(
            assistant_id, "assistant", f"ZIP AI {index:03d} — 💙")}
        parent = assistant_id
    mapping["zip-alt"] = {"id": "zip-alt", "parent": "zip-user-000-é", "message": message(
        "zip-alt", "assistant", "ALT NOT PLAYABLE")}
    selected = {"id": "zip-selected-125", "title": "ZIP selected 125 — Unicode",
                "mapping": mapping, "current_node": parent}
    unselected = {"id": "zip-unselected", "title": "Do not import this thread",
                  "mapping": {"root": {"id": "root", "parent": None, "message": None},
                              "u": {"id": "u", "parent": "root", "message": message("u", "user", "EXTERNAL UNSELECTED SOURCE")},
                              "a": {"id": "a", "parent": "u", "message": message("a", "assistant", "EXTERNAL UNSELECTED SOURCE")}},
                  "current_node": "a"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested/conversations.json", json.dumps([unselected], ensure_ascii=False))
        archive.writestr("nested/conversations-1.json", json.dumps([selected], ensure_ascii=False))
        archive.writestr("account_metadata.json", json.dumps({"email": "synthetic@example.test"}))
        archive.writestr("attachments/private-note.txt", "ATTACHMENT MUST BE IGNORED")
    return buffer.getvalue()


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
                capture_zip_transfers = False
                zip_transfer_posts: list[dict] = []
                trace_events: list[dict] = []
                trace_started = time.monotonic()

                def trace(kind: str, **fields: object) -> None:
                    if len(trace_events) >= 100:
                        trace_events.pop(0)
                    trace_events.append({"ms": round((time.monotonic() - trace_started) * 1000), "kind": kind, **fields})

                def trace_request(request) -> None:
                    if "/api/" in request.url:
                        trace("request", method=request.method, url=_redact_browser_url(request.url))

                def trace_response(response) -> None:
                    if "/api/" in response.url:
                        trace("response", status=response.status, url=_redact_browser_url(response.url))

                def trace_request_failed(request) -> None:
                    if "/api/" in request.url:
                        trace("requestfailed", method=request.method, url=_redact_browser_url(request.url), failure=request.failure)

                def capture_zip_transfer(request) -> None:
                    if not capture_zip_transfers or request.method != "POST" or "/api/transfers/chatgpt/" not in request.url:
                        return
                    body = request.post_data_json
                    assert isinstance(body, dict)
                    zip_transfer_posts.append({"url": request.url, "body": body})

                page.on("request", trace_request)
                page.on("request", capture_zip_transfer)
                page.on("response", trace_response)
                page.on("requestfailed", trace_request_failed)
                page.on("console", lambda message: trace("console", type=message.type, text=message.text[:300]))
                page.on("pageerror", lambda error: trace("pageerror", text=str(error)[:300]))
                page.on("request", lambda r: outbound.append(r.url) if not r.url.startswith(origin) else None)
                page.goto(origin, wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name="Đăng nhập Playroom")).to_be_visible()
                page.get_by_label("Email").fill(EMAIL)
                page.get_by_label("Mật khẩu").fill(PASSWORD)
                page.get_by_role("button", name="Đăng nhập").click()
                expect(page.get_by_role("heading", name="Thư viện truyện")).to_be_visible(timeout=15000)
                screenshot_dir = Path(tempfile.gettempdir()) / "playroom-story-library-screenshots"
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                page.set_viewport_size({"width": 757, "height": 900})
                page.screenshot(path=str(screenshot_dir / "library-757.png"), full_page=True)
                page.get_by_role("button", name="+ Tạo truyện mới").click()
                page.screenshot(path=str(screenshot_dir / "create-vietnamese-757.png"), full_page=True)
                page.set_viewport_size({"width": 375, "height": 812})
                page.screenshot(path=str(screenshot_dir / "create-vietnamese-375.png"), full_page=True)
                page.get_by_role("button", name="Đóng").click()
                page.screenshot(path=str(screenshot_dir / "library-375.png"), full_page=True)
                page.get_by_role("button", name="+ Tạo truyện mới").click()
                page.get_by_label("Tên truyện").fill("Thử nghiệm sân bóng")
                page.get_by_label("Tên thế giới").fill("Trường Bangtan")
                page.get_by_label("Tên persona").fill("Henn")
                page.get_by_role("button", name="Thêm nhân vật").click()
                page.get_by_label("Tên nhân vật 1").fill("Yuna")
                page.get_by_role("button", name="Lưu truyện").click()

                expect(page.get_by_role("heading", name="Thử nghiệm sân bóng")).to_be_visible(timeout=15000)
                expect(page.get_by_role("button", name="Gửi", exact=True)).to_have_count(1)
                expect(page.locator(".demo-badge")).to_be_visible()
                expect(page.locator(".generation-composer .demo-runtime-notice")).to_be_visible()
                expect(page.get_by_text("Dùng **...** cho hành động hoặc suy nghĩ;", exact=False)).to_be_visible()
                campaign = app.state.generation_provider
                assert campaign.stage_counts == {}
                provider_before_navigation = len(campaign.calls)
                draft = page.locator("#generation-action")
                draft.fill("Ghi chú chưa gửi")
                page.get_by_role("button", name="Thư viện truyện").click()
                expect(page.get_by_role("heading", name="Thư viện truyện")).to_be_visible()
                page.get_by_role("button", name="Đọc tiếp").click()
                expect(draft).to_have_value("Ghi chú chưa gửi")
                assert len(campaign.calls) == provider_before_navigation
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name="Thử nghiệm sân bóng")).to_be_visible(timeout=15000)
                assert len(campaign.calls) == provider_before_navigation
                camp_list = page.context.request.get(f"{origin}/api/campaigns").json()
                assert len(camp_list) == 1
                campaign_id = camp_list[0]["id"]
                first_title = camp_list[0]["title"]
                detail = page.context.request.get(f"{origin}/api/campaigns/{campaign_id}").json()
                branch_id = detail["branch_id"]

                # IME composition must never submit early. Shift+Enter is
                # reserved for inserting an in-field newline, not Send.
                for viewport_width in (757, 375):
                    page.set_viewport_size({"width": viewport_width, "height": 780})
                    composer_box = page.locator(".generation-composer").bounding_box()
                    textarea_box = page.locator(".generation-composer form > textarea").bounding_box()
                    assert composer_box and textarea_box
                    assert textarea_box["width"] >= composer_box["width"] * 0.60, (viewport_width, composer_box, textarea_box)
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
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

                # The library must retain multiple stories and restore each
                # story's own history. Create B through the authenticated API
                # so this check stays independent of the create form.
                first_story_id = campaign_id
                first_branch_id = branch_id
                transcript = _project(page, origin, first_story_id, first_branch_id)["transcript"]
                assert len(transcript) == 2
                first_turn_count = len(transcript)
                second_create = page.context.request.post(
                    f"{origin}/api/campaigns",
                    data=json.dumps({
                        "title": "Synthetic history B",
                        "world": {"name": "Synthetic world B", "description": ""},
                        "persona": {"name": "Synthetic player B", "description": ""},
                        "characters": [],
                    }),
                    headers={
                        "content-type": "application/json",
                        "origin": origin,
                        "x-requested-with": "XMLHttpRequest",
                    },
                )
                assert second_create.status == 201, second_create.text()
                second_story = second_create.json()
                second_story_id = second_story["id"]
                assert second_story_id != first_story_id
                provider_before_library = len(campaign.calls)

                # Reload loads the API-created catalog and restores A from
                # localStorage before opening the library.
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name=first_title)).to_be_visible(timeout=15000)
                page.locator(".library-trigger").click()
                expect(page.locator("#library-title")).to_be_visible(timeout=12000)
                first_card = page.locator("article").filter(has_text=first_title)
                second_card = page.locator("article").filter(has_text="Synthetic history B")
                expect(first_card).to_have_count(1)
                expect(second_card).to_have_count(1)
                for width, filename in ((757, "library-757.png"), (375, "library-375.png")):
                    page.set_viewport_size({"width": width, "height": 900 if width == 757 else 812})
                    expect(page.locator("#library-title")).to_be_visible()
                    expect(first_card.locator("h2")).to_have_text(first_title)
                    expect(second_card.locator("h2")).to_have_text("Synthetic history B")
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path=str(screenshot_dir / filename), full_page=True)
                second_card.locator("button").click()
                expect(page.get_by_role("heading", name="Synthetic history B")).to_be_visible(timeout=12000)
                expect(page.locator(".story-turn")).to_have_count(0)
                assert len(campaign.calls) == provider_before_library
                page.locator(".library-trigger").click()
                expect(page.locator("#library-title")).to_be_visible(timeout=12000)
                first_card = page.locator("article").filter(has_text=first_title)
                first_card.locator("button").click()
                expect(page.get_by_role("heading", name=first_title)).to_be_visible(timeout=12000)
                expect(page.locator(".story-turn")).to_have_count(first_turn_count)
                expect(page.locator(".story-turn").filter(has_text=NARRATION)).to_have_count(first_turn_count)
                assert len(campaign.calls) == provider_before_library
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name=first_title)).to_be_visible(timeout=15000)
                expect(page.locator(".story-turn")).to_have_count(first_turn_count)
                expect(page.locator(".story-turn").filter(has_text=NARRATION)).to_have_count(first_turn_count)
                assert len(campaign.calls) == provider_before_library

                campaign_id = first_story_id
                branch_id = first_branch_id

                # A POST can reach the server before the browser loses its
                # response. The client must recover the *same* durable job.
                intercepted = {"count": 0}
                def drop_post(route):
                    intercepted["count"] += 1
                    if intercepted["count"] > 1:
                        route.continue_()
                        return
                    response = route.fetch()
                    assert response.status == 201
                    route.abort("failed")
                # Keep this route registered after its one synthetic failure.
                # Playwright 1.56 can race auto-removal with a follow-up fetch:
                # https://github.com/microsoft/playwright/issues/41802
                page.route("**/api/campaigns/*/generate", drop_post)
                _send_and_wait(page, "**Henn gật đầu**", 3)
                assert intercepted["count"] == 1
                assert len(campaign.calls) == 3

                # Definite rejection has no reserved job and must not block
                # the next *explicit* Send; no automatic paid retry.
                rejected = {"count": 0}
                def reject_once(route):
                    rejected["count"] += 1
                    if rejected["count"] > 1:
                        route.continue_()
                        return
                    route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "Rejected before reservation"}))
                page.route("**/api/campaigns/*/generate", reject_once)
                draft = "Chúng ta cùng bắt đầu."
                page.get_by_role("textbox", name="Hành động tiếp theo").fill(draft)
                page.get_by_role("button", name="Gửi", exact=True).click()
                expect(page.get_by_role("alert")).to_be_visible(timeout=10000)
                expect(page.get_by_role("textbox", name="Hành động tiếp theo")).to_have_value(draft)
                assert rejected["count"] == 1
                assert len(campaign.calls) == 3
                _send_and_wait(page, draft, 4)
                assert len(campaign.calls) == 4

                # A rejected stale checkpoint (409) followed by by-key 404
                # is a definite pre-reservation conflict: reload authority,
                # retain player input, await a *new explicit* Send.
                stale_route_hits = 0
                def stale_once(route):
                    nonlocal stale_route_hits
                    stale_route_hits += 1
                    if stale_route_hits > 1:
                        route.continue_()
                        return
                    trace("stale_route_hit", count=stale_route_hits)
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Generation checkpoint is stale"}))
                page.route("**/api/campaigns/*/generate", stale_once)
                fifth = "Cậu thấy lượt bóng vừa rồi chứ?"
                compose.fill(fifth)
                trace("stale_click_before")
                page.get_by_role("button", name="Gửi", exact=True).click()
                trace("stale_click_after")
                try:
                    expect(page.get_by_text("Tác vụ đã thay đổi.", exact=False)).to_be_visible(timeout=12000)
                except (PlaywrightTimeoutError, AssertionError):
                    trace("stale_assertion_timeout", button_disabled=page.locator(".generation-composer button[type=submit]").is_disabled(), button_text=page.locator(".generation-composer button[type=submit]").inner_text())
                    _print_generation_diagnostics(page, origin, campaign_id, branch_id, campaign.calls, trace_events, stale_route_hits, app.state.browser_asgi_observer)
                    raise
                assert stale_route_hits == 1
                expect(compose).to_have_value(fifth)
                assert len(campaign.calls) == 4
                _send_and_wait(page, fifth, 5)
                assert len(campaign.calls) == 5

                # The candidate may be committed but the parent projection
                # refresh can fail. The same job must be retried for commit,
                # never paid/reserved as another generation.
                projection_failures = {"count": 0}
                def fail_projection_once(route):
                    projection_failures["count"] += 1
                    if projection_failures["count"] > 1:
                        route.continue_()
                        return
                    route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "Synthetic refresh outage"}))
                page.route("**/api/campaigns/*/projection*", fail_projection_once)
                sixth = "Cứ tiếp tục thôi, Yuna."
                compose.fill(sixth)
                page.get_by_role("button", name="Gửi", exact=True).click()
                expect(page.get_by_text("Không thể lưu lượt kể hoàn chỉnh", exact=False)).to_be_visible(timeout=20000)
                expect(compose).to_have_value(sixth)
                assert projection_failures["count"] == 1
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

                # Issue #27 ZIP slice: the archive is generated in memory and
                # contains nested numbered conversations plus ignored metadata
                # and attachment noise. Only the owner-selected 125-pair
                # thread may cross the preview/import endpoints.
                page.set_viewport_size({"width": 1280, "height": 900})
                before_zip_calls = len(campaign.calls)
                zip_bytes = _browser_zip_conversations()
                capture_zip_transfers = True
                page.get_by_role("button", name="Nhập ChatGPT").click()
                page.get_by_label("Tệp xuất từ ChatGPT").set_input_files({
                    "name": "chatgpt-export.zip", "mimeType": "application/zip", "buffer": zip_bytes,
                })
                expect(page.get_by_text("Đã đọc 2 cuộc hội thoại", exact=False)).to_be_visible(timeout=12000)
                assert zip_transfer_posts == [], "ZIP discovery must not POST transfer data"
                thread_picker = page.get_by_label("Chọn chính xác cuộc hội thoại cần nhập")
                selected_option = page.get_by_role("option", name=re.compile("ZIP selected 125"))
                selected_value = selected_option.get_attribute("value")
                assert selected_value is not None
                thread_picker.select_option(value=selected_value)
                page.get_by_role("button", name="Xem trước thread này").click()
                expect(page.get_by_text("Tìm thấy 125 cặp", exact=False)).to_be_visible(timeout=12000)
                assert len(zip_transfer_posts) == 1
                preview_post = zip_transfer_posts[0]
                assert preview_post["url"].endswith("/api/transfers/chatgpt/preview")
                preview_conversation = preview_post["body"]["conversation"]
                assert preview_conversation["id"] == "zip-selected-125"
                preview_text = json.dumps(preview_conversation, ensure_ascii=False)
                assert "ALT NOT PLAYABLE" in preview_text
                assert "EXTERNAL UNSELECTED SOURCE" not in preview_text
                assert "account_metadata" not in preview_text and "ATTACHMENT MUST BE IGNORED" not in preview_text
                assert len(campaign.calls) == before_zip_calls, "Preview must not call the provider"
                page.get_by_label("Tôi đã xem đúng thread", exact=False).check()
                page.get_by_role("button", name="Nhập và mở chiến dịch").click()
                expect(page.get_by_role("heading", name="ZIP selected 125 — Unicode")).to_be_visible(timeout=12000)
                expect(page.locator(".story-turn")).to_have_count(125, timeout=25000)
                expect(page.locator(".generation-composer")).to_have_count(0)
                zip_campaigns = page.context.request.get(f"{origin}/api/campaigns").json()
                zip_campaign = next(c for c in zip_campaigns if c["title"] == "ZIP selected 125 — Unicode")
                zip_detail = page.context.request.get(f"{origin}/api/campaigns/{zip_campaign['id']}").json()
                zip_projection = _project(page, origin, zip_campaign["id"], zip_detail["branch_id"])
                assert len(zip_projection["transcript"]) == 125
                assert zip_projection["transcript"][0]["action_text"] == "ZIP người chơi 000\nDòng phụ 000"
                assert zip_projection["transcript"][-1]["narrative_text"] == "ZIP AI 124 — 💙"
                assert all("ALT NOT PLAYABLE" not in json.dumps(turn, ensure_ascii=False) for turn in zip_projection["transcript"])
                assert all("EXTERNAL UNSELECTED SOURCE" not in json.dumps(turn, ensure_ascii=False) for turn in zip_projection["transcript"])
                assert len(zip_transfer_posts) == 2
                import_post = zip_transfer_posts[1]
                assert import_post["url"].endswith("/api/transfers/chatgpt/import")
                import_conversation = import_post["body"]["conversation"]
                assert import_conversation == preview_conversation
                assert "ALT NOT PLAYABLE" in json.dumps(import_conversation, ensure_ascii=False)
                assert "EXTERNAL UNSELECTED SOURCE" not in json.dumps(import_conversation, ensure_ascii=False)
                assert "ATTACHMENT MUST BE IGNORED" not in json.dumps(import_conversation, ensure_ascii=False)
                assert len(campaign.calls) == before_zip_calls, "Import must not call the provider"
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".generation-composer")).to_have_count(0)
                expect(page.get_by_text("125 cặp lượt đã nhập", exact=False)).to_be_visible(timeout=12000)
                zip_checks = page.locator(".create-card input[type=checkbox]")
                expect(zip_checks).to_have_count(4)
                for index in range(4):
                    zip_checks.nth(index).check()
                page.get_by_role("button", name=re.compile("Duy.*Send")).click()
                expect(page.locator(".generation-composer")).to_be_visible(timeout=12000)
                try:
                    zip_action = "ZIP lượt tiếp theo"
                    compose = page.get_by_role("textbox", name="Hành động tiếp theo")
                    compose.fill(zip_action)
                    page.get_by_role("button", name="Gửi", exact=True).click()
                    expect(page.locator(".generation-details")).to_contain_text("Giai đoạn: failed", timeout=25000)
                    failed_projection = _project(page, origin, zip_campaign["id"], zip_detail["branch_id"])
                    failed_jobs = [job for job in failed_projection["jobs"] if job.get("status") == "failed"]
                    assert len(failed_jobs) == 1, failed_projection["jobs"]
                    failed_job = page.context.request.get(f"{origin}/api/generation/jobs/{failed_jobs[0]['id']}")
                    assert failed_job.ok
                    failure = failed_job.json()["failure"]
                    assert failure == {"code": "STATE_CONFLICT", "message": "Required narrator context exceeds the configured input budget"}
                    expect(page.locator(".story-turn")).to_have_count(125, timeout=1000)
                    expect(compose).to_have_value(zip_action)
                    assert len(campaign.calls) == before_zip_calls
                except AssertionError:
                    _print_generation_diagnostics(
                        page, origin, zip_campaign["id"], zip_detail["branch_id"],
                        campaign.calls, trace_events, stale_route_hits,
                    )
                    raise

                # The imported transcript remains intact while the owner adds
                # a concise, source-linked summary for the earlier 117 turns.
                # This is the existing Memory UI approval path, followed by a
                # new explicit Send of the same action after the checkpoint
                # refresh.
                page.get_by_role("button", name="Mở hồ sơ và ký ức").click()
                dialog = page.get_by_role("dialog", name="Hồ sơ và ký ức")
                dialog.get_by_role("button", name="Ký ức", exact=True).click()
                expect(dialog.get_by_label("Loại")).to_be_visible(timeout=12000)
                summary_text = "Các lượt 000–116 gồm lời người chơi và phản hồi AI theo thứ tự nguồn; nội dung này chỉ là tóm tắt truy hồi."
                revision_ids = [turn["revision_id"] for turn in zip_projection["transcript"]]
                dialog.get_by_label("Loại").select_option("summary")
                dialog.get_by_role("textbox", name="Nội dung", exact=True).fill(summary_text)
                dialog.get_by_label("Revision bắt đầu").select_option(revision_ids[0])
                dialog.get_by_label("Revision kết thúc").select_option(revision_ids[116])
                dialog.get_by_label("Phạm vi kiến thức").select_option("narrator_only")
                dialog.get_by_role("button", name="Thêm ký ức").click()
                expect(dialog.get_by_text(summary_text, exact=True)).to_be_visible(timeout=12000)
                summary_source = dialog.get_by_text(re.compile("Khoảng nguồn:"), exact=False)
                expect(summary_source).to_be_visible()
                memory_response = page.context.request.get(f"{origin}/api/campaigns/{zip_campaign['id']}/memory?branch_id={zip_detail['branch_id']}")
                assert memory_response.ok
                summaries = [item for item in memory_response.json() if item.get("text") == summary_text]
                assert len(summaries) == 1
                assert summaries[0]["origin"] == "user"
                assert summaries[0]["status"] == "approved"
                assert summaries[0]["knowledge_scope"] == "narrator_only"
                assert summaries[0]["source_revision_ids"] == revision_ids[:117]
                dialog.get_by_role("button", name="Đóng hồ sơ và ký ức").click()
                expect(page.get_by_role("button", name="Gửi", exact=True)).to_be_visible(timeout=12000)
                summary_projection = _project(page, origin, zip_campaign["id"], zip_detail["branch_id"])
                assert [turn["revision_id"] for turn in summary_projection["transcript"]] == revision_ids
                assert len(summary_projection["transcript"]) == 125
                assert len(campaign.calls) == before_zip_calls
                _send_and_wait(page, "ZIP lượt tiếp theo", 126)
                assert len(campaign.calls) == before_zip_calls + 1
                zip_projection = _project(page, origin, zip_campaign["id"], zip_detail["branch_id"])
                assert zip_projection["transcript"][-1]["action_text"] == "ZIP lượt tiếp theo"
                assert zip_projection["transcript"][-1]["narrative_text"] == NARRATION
                capture_zip_transfers = False
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(126, timeout=12000)

                # Issue #29: owner-selected synthetic structured legacy source.
                # No private material, no historical turn fabrication, no model call on import.
                from test_legacy_import import synthetic_bundle
                source = synthetic_bundle()
                page.get_by_role("button", name="Nhập Legacy").click()
                page.get_by_label("Bundle JSON (tối đa 20 MiB)").set_input_files({
                    "name": "legacy-synthetic.json", "mimeType": "application/json",
                    "buffer": json.dumps(source, ensure_ascii=False).encode("utf-8"),
                })
                page.get_by_role("button", name="Xem cấu trúc và khoảng trống").click()
                expect(page.get_by_text("Chương hoàn thành", exact=False)).to_be_visible(timeout=12000)
                page.get_by_label("Tôi hiểu đây không phải toàn bộ lịch sử", exact=False).check()
                page.get_by_role("button", name="Tạo chiến dịch nháp để duyệt").click()
                expect(page.get_by_role("heading", name="Lanterns")).to_be_visible(timeout=12000)
                expect(page.locator(".story-turn")).to_have_count(0)
                expect(page.locator(".generation-composer")).to_have_count(0)
                imported_campaigns = page.context.request.get(f"{origin}/api/campaigns").json()
                imported_legacy = next(c for c in imported_campaigns if c["title"] == "Lanterns")
                legacy_detail = page.context.request.get(f"{origin}/api/campaigns/{imported_legacy['id']}").json()
                legacy_projection = _project(page, origin, imported_legacy["id"], legacy_detail["branch_id"])
                assert legacy_projection["transcript"] == []
                assert legacy_projection["import_review"]["required"] is True
                assert legacy_projection["import_review"]["source_kind"] == "legacy_bundle"
                assert len(campaign.calls) == 9
                blocked = page.context.request.post(f"{origin}/api/campaigns/{imported_legacy['id']}/generate", data=json.dumps({
                    "branch_id": legacy_detail["branch_id"], "action": "*Lan chờ.*",
                    "idempotency_key": str(uuid4()), "checkpoint_id": legacy_projection["branch"]["checkpoint_id"],
                }), headers={"content-type": "application/json", "origin": origin})
                assert blocked.status == 409
                page.reload(wait_until="domcontentloaded")
                expect(page.get_by_text("3 mục nguồn đang chờ duyệt", exact=False)).to_be_visible(timeout=12000)
                checks = page.locator(".import-review-panel input[type=checkbox]")
                expect(checks).to_have_count(5)
                for viewport_width in (757, 375):
                    page.set_viewport_size({"width": viewport_width, "height": 780})
                    for index in range(checks.count()):
                        box = checks.nth(index).bounding_box()
                        label_box = checks.nth(index).locator("xpath=..").bounding_box()
                        assert box and box["width"] <= 24 and box["height"] <= 24
                        assert label_box and label_box["height"] >= 44
                for index in range(5):
                    checks.nth(index).check()
                page.get_by_role("button", name=re.compile("Duy.*Send")).click()
                expect(page.locator(".generation-composer")).to_be_visible(timeout=12000)
                _send_and_wait(page, "*Lan hỏi Vy về tờ giấy.*", 1)
                assert len(campaign.calls) == 10
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".story-turn")).to_have_count(1)

                # Saving unchanged provider budget settings must surface a
                # body-level toast above the scrolled settings sheet at both
                # supported narrow widths. The save itself never calls the
                # generation provider.
                toast_screenshot_dir = Path(tempfile.gettempdir()) / "playroom-save-toast-screenshots"
                toast_screenshot_dir.mkdir(parents=True, exist_ok=True)
                for viewport_width in (757, 375):
                    page.set_viewport_size({"width": viewport_width, "height": 780})
                    page.get_by_role("button", name="Cài đặt").click()
                    settings_dialog = page.get_by_role("dialog", name="Cài đặt")
                    expect(settings_dialog).to_be_visible(timeout=12000)
                    expect(settings_dialog.get_by_role("region", name="Cài đặt provider")).to_be_visible(timeout=12000)
                    save_budget = settings_dialog.get_by_role("button", name="Lưu ngân sách")
                    save_budget.scroll_into_view_if_needed()
                    provider_calls_before_settings_save = len(campaign.calls)
                    save_budget.click()
                    expect(save_budget).to_be_focused()
                    toast_region = page.get_by_role("region", name="Thông báo")
                    success_toast = toast_region.get_by_role("status")
                    expect(success_toast).to_be_visible(timeout=12000)
                    assert len(campaign.calls) == provider_calls_before_settings_save

                    toast_box = success_toast.bounding_box()
                    viewport = page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
                    assert toast_box
                    assert 0 <= toast_box["x"] and 0 <= toast_box["y"]
                    assert toast_box["x"] + toast_box["width"] <= viewport["width"]
                    assert toast_box["y"] + toast_box["height"] <= viewport["height"]
                    toast_z_index = toast_region.evaluate("(el) => Number.parseInt(getComputedStyle(el).zIndex, 10) || 0")
                    overlay_z_index = page.locator(".mobile-overlay").evaluate("(el) => Number.parseInt(getComputedStyle(el).zIndex, 10) || 0")
                    toast_center_is_topmost = success_toast.evaluate(
                        """(el) => {
                          const box = el.getBoundingClientRect();
                          const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
                          return hit === el || el.contains(hit);
                        }"""
                    )
                    assert toast_z_index > overlay_z_index or toast_center_is_topmost
                    page.screenshot(path=str(toast_screenshot_dir / f"save-toast-{viewport_width}.png"), full_page=True)
                    success_toast.get_by_role("button", name="Đóng thông báo").click()
                    expect(success_toast).not_to_be_visible()
                    page.get_by_role("button", name="Đóng cài đặt").click()
                    expect(settings_dialog).not_to_be_visible()

                browser.close()
                print("B3 Chromium synthetic + ChatGPT JSON review and Legacy bundle import/review/fake Send + save toast PASS")
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
                page.get_by_role("button", name="+ Tạo truyện mới").click()
                page.get_by_label("Tên truyện").fill("Lan Vy Binh local")
                page.get_by_label("Tên thế giới").fill("Thế giới tổng hợp")
                page.get_by_label("Tên persona").fill("Bình")
                page.get_by_role("button", name="Thêm nhân vật").click()
                page.get_by_label("Tên nhân vật 1").fill("Lan")
                page.get_by_role("button", name="Lưu truyện").click()

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
