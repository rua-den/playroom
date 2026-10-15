# Playroom

App roleplay cá nhân bằng tiếng Việt, ưu tiên điện thoại và mở qua một link web riêng. Người chơi điều khiển nhân vật của mình; AI dẫn truyện và đóng vai các nhân vật còn lại.

Trọng tâm là quản lý context qua nhiều chương: lưu hồ sơ, cảnh, sự kiện, quan hệ, tóm tắt và transcript riêng; xem được AI đang dùng dữ kiện nào, sửa được khi nhớ sai, và giữ bộ nhớ đúng theo nhánh truyện.

## Trạng thái

**Codex / Astra handoff (15/10/2026):** Chủ dự án đã giao **Astra trong Codex** tiếp tục implement, bắt đầu từ [Issue #14](https://github.com/rua-den/playroom/issues/14) (Ollama Free starter Gemma4), sau đó là [Issue #9](https://github.com/rua-den/playroom/issues/9) B4. Đọc [handoff thực thi mới nhất](docs/handoff/2026-10-15-codex-astra.md) và `AGENTS.md` trước khi code. Repo `main` là source of truth. Chưa có gọi AI trả phí/đăng truyện riêng/deploy VPS được phê duyệt bởi riêng lệnh chuyển giao này.

Backend có storage/auth/checkpoint/memory, context deterministic, OpenRouter adapter và pipeline quality/economy. U1–U7 đã qua kiểm chứng local synthetic, gồm browser smoke và layout 360/390/430px cùng desktop. Snapshot bàn giao 13/10/2026 có **135 test backend qua** là số liệu lịch sử, không phải bằng chứng nghiệm thu Task3. Chưa gọi model thật hay deploy VPS; chất lượng model thật và thử cài trên điện thoại vẫn mở.

**Source hiện tại (14/10/2026):** B1 Send/recovery [PR #3](https://github.com/rua-den/playroom/pull/3), B2 Ollama narrator contract giả lập [PR #5](https://github.com/rua-den/playroom/pull/5), và B3 gameplay bằng Chromium thực [PR #7](https://github.com/rua-den/playroom/pull/7) + [PR #8](https://github.com/rua-den/playroom/pull/8) đều đã merge vào `main`. CI tại code commit `2652a45` [PASS](https://github.com/rua-den/playroom/actions/runs/38514327407): backend 279 tests; frontend 79 tests PASS, 3 skipped; build/typecheck/compile PASS; browser synthetic chơi 7 lượt, reconnect, kiểm tra viewport 360/390/430px và NPC attribution. Xem [handoff nghiệm thu hiện hành](docs/handoff/2026-10-14-next-execution.md). Các tài liệu 13/10 và review ban đầu là lịch sử; chưa gọi model thật, chưa test điện thoại vật lý, chưa thay đổi VPS/Caddy. [B4 live trial](https://github.com/rua-den/playroom/issues/9) cần phê duyệt riêng về API trả phí và triển khai; xem [bộ preflight B4 không tốn phí](docs/acceptance/2026-10-14-b4-live-trial-readiness.md). **B4 budget guard đã triển khai** qua [PR #11](https://github.com/rua-den/playroom/pull/11): ngân sách toàn phiên, hạn mức mỗi lượt và số lượt tối đa đều yêu cầu owner xác nhận riêng, được lưu bền bằng SQLite và kiểm tra phía server trước khi gọi provider. [CI code HEAD `01548fb` PASS](https://github.com/rua-den/playroom/actions/runs/38538132285): backend 293 PASS, frontend 80 PASS/3 skipped, Chromium PASS. Đây là giới hạn dự toán nội bộ, **không bảo đảm hóa đơn thực tế**. B4 model thật/điện thoại thật vẫn chưa được nghiệm thu.


**Free-first UI (14/10/2026):** [PR #13](https://github.com/rua-den/playroom/pull/13) merged ở code SHA `2220a63`; [merge-head CI PASS](https://github.com/rua-den/playroom/actions/runs/38556240140): **backend 293 PASS**, **frontend 83 PASS/3 skipped**, typecheck/build và Chromium E2E PASS. Settings hiển thị gói **Free** trước, không tự điền số lượt Send/giới hạn USD của Ollama, giấu biểu mẫu ngân sách toàn phiên trong lựa chọn Capped paid, và cảnh báo narrator profile có `credential_tier != free` dù tài khoản Ollama đang dùng Free. **Free không đồng nghĩa mọi model đều không tốn credits**: Ollama cấp credits starter hằng tháng cho tập con model starter; usage tính theo token, không có số lượt Send cố định. [Ollama pricing](https://ollama.com/pricing).

**Kiểm tra repository secret:** workflow [Ollama read-only preflight](https://github.com/rua-den/playroom/actions/runs/38556240502) dùng `OLLAMA_API_KEY` trên GitHub Actions `main` đã gọi thành công `GET https://ollama.com/v1/models` và nhận model `gpt-oss:120b` trong catalog. **Không gọi completions, không gửi dữ liệu truyện, không xác định được account credit balance hay model free-tier eligibility từ endpoint này.** Muốn nghiệm thu live model/điện thoại vẫn cần B4 ([Issue #9](https://github.com/rua-den/playroom/issues/9)).


**Ollama Free starter đã implement (15/10/2026):** [PR #16](https://github.com/rua-den/playroom/pull/16) merge code SHA `e81533f4597f2c35d46f28d0a7b026a9d9679439`: `gemma4:31b-cloud` được xác minh bằng exact model ID `gemma4:31b` từ catalog đã xác thực (Astra/PR #15), bên cạnh `gpt-oss:120b` vẫn giữ nhãn paid. UI có dropdown chọn Free starter/Paid, không tự nâng cấp, không đưa ra Send quota tự chế. [CI trên chính main merge SHA #38678014735](https://github.com/rua-den/playroom/actions/runs/38678014735): backend **303 PASS**, frontend **84 PASS/3 skipped**, build/typecheck/compile/Chromium E2E **PASS**. **Lưu ý:** model starter đủ điều kiện Free không chứng minh tài khoản còn credits hoặc sẽ không bị trừ credits mua thêm; chưa có live completion/phone/VPS test ([B4 Issue #9](https://github.com/rua-den/playroom/issues/9)).

Kiểm tra backend tại root repo:

```powershell
rtk proxy uv sync --locked --extra test
rtk proxy uv run --locked --extra test pytest backend/tests -q
rtk proxy uv run --locked python -m compileall -q backend/playroom
```

Mỗi mốc cần dùng đúng focused tests và verification commands trong handoff hiện tại. U7 local browser flow đã qua; không dùng số test lịch sử làm bằng chứng thay thế cho các gate của Task3 hoặc chất lượng model thật.

## Đọc theo thứ tự

1. [Thiết kế sản phẩm và context](docs/superpowers/specs/2026-10-12-personal-playroom-design.md).
2. [Runtime AI: quality, economy và free](docs/superpowers/specs/2026-10-12-runtime-ai-context-policy.md).
3. [Plan triển khai và các mốc nghiệm thu](docs/superpowers/plans/2026-10-12-personal-playroom-implementation-plan.md).
4. [Review plan và các vấn đề đã sửa](docs/superpowers/reviews/2026-10-12-personal-playroom-plan-review.md).
5. [Phân tích Whif APK](docs/references/whif-apk-analysis.md) và [mẫu kể chuyện playrooom](docs/references/playrooom-style-and-evaluation.md).

Agent đọc [AGENTS.md](AGENTS.md) trước khi thay đổi repo.

## Hướng kỹ thuật

- Giao diện: React + TypeScript + Vite, responsive ưu tiên điện thoại; PWA manifest để thêm vào màn hình chính trên trình duyệt hỗ trợ.
- Backend: Python + FastAPI + Uvicorn; bộ chọn context, phiên bản truyện và AI provider adapter tách riêng.
- Dữ liệu: SQLite trên thư mục lưu trữ bền, có nguồn dữ kiện và checkpoint của từng trạng thái.
- Deploy: VPS hiện có của người dùng, qua **Caddy đang hoạt động**; Playroom có service, thư mục, database và subdomain riêng.
- AI: OpenRouter là integration đầu tiên do người dùng chọn; model/role được cấu hình riêng. API key nhập ở máy/server, không dùng session ChatGPT làm API access.
- Domain dự kiến: https://play.nhkhuy.run.place; DNS/SSH/Caddy thực tế chưa được audit hay thay đổi.
- Quality có AI hỗ trợ chọn context; economy giảm số call. Cả hai giữ nguyên dữ liệu/style, có free-only policy và không tự chuyển paid khi hết quota.

## Các mốc

| Mốc | Kết quả cần có |
|---|---|
| Kiểm chứng context | Fixture 120 cặp lượt có summary coverage; chọn đúng nguồn, đúng nhánh và đúng budget |
| Bản chơi thử trên điện thoại | Đăng nhập, tạo/chơi chiến dịch, cấu hình AI/mode, sửa hồ sơ/bộ nhớ, khôi phục sau mất mạng; import lịch sử đầy đủ ở mốc sau |
| MVP chơi dài | Duyệt tóm tắt, tạo lại/rẽ nhánh, nhập phiên cũ, sao lưu/khôi phục và nghiệm thu model thật |

## Quyết định đã chốt

Canon do người chơi chốt không bị AI âm thầm ghi đè. Transcript gốc được giữ lại. Context theo budget thay vì gửi toàn bộ lịch sử. Fork dùng checkpoint gồm cả phiên bản hồ sơ/bộ nhớ; reconnect lấy request cũ thay vì tự gọi AI lại.

Caddy là thông tin mới nhất do người dùng xác nhận. Tài liệu Nginx/Certbot cũ của `wedding-online` chỉ dùng tham khảo lịch sử; không copy làm cấu hình Playroom.

Domain, model/API, tài nguyên và cấu hình VPS thực tế cần xác minh trước khi nối/deploy. Chất lượng kể chuyện và giữ mạch phải được kiểm chứng bằng phiên chơi thật, ngoài các test dữ liệu.

## Chạy demo cục bộ

Demo tổng hợp là chế độ opt-in riêng, chỉ bind loopback và không gọi model thật.

```powershell
rtk proxy uv sync --locked --extra test
rtk cmd /c "cd frontend && npm ci && npm run build"
rtk proxy uv run playroom-demo --data-dir .playroom-demo
```

Mở `http://127.0.0.1:8000`. Lần chạy đầu tạo owner password ngẫu nhiên an toàn và in password đúng một lần. Có thể tự đặt password tối thiểu 12 ký tự bằng `--password`; thư mục `.playroom-demo/` giữ SQLite và secrets để dữ liệu còn sau khi khởi động lại. Giao diện hiển thị nhãn synthetic/demo và narrative xác định để thử nhiều lượt.

Thêm `--email demo@example.test` nếu cần email khác. Không dùng thư mục demo hoặc `secure_cookies=False` cho production; production factory vẫn yêu cầu cấu hình provider/credential thật và cookie bảo mật.
