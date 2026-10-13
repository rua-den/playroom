# Playroom

App roleplay cá nhân bằng tiếng Việt, ưu tiên điện thoại và mở qua một link web riêng. Người chơi điều khiển nhân vật của mình; AI dẫn truyện và đóng vai các nhân vật còn lại.

Trọng tâm là quản lý context qua nhiều chương: lưu hồ sơ, cảnh, sự kiện, quan hệ, tóm tắt và transcript riêng; xem được AI đang dùng dữ kiện nào, sửa được khi nhớ sai, và giữ bộ nhớ đúng theo nhánh truyện.

## Trạng thái

Backend có storage/auth/checkpoint/memory, context deterministic, OpenRouter adapter và pipeline quality/economy. U1–U7 đã qua kiểm chứng local synthetic, gồm browser smoke và layout 360/390/430px cùng desktop. Snapshot bàn giao 13/10/2026 có **135 test backend qua** là số liệu lịch sử, không phải bằng chứng nghiệm thu Task3. Chưa gọi model thật hay deploy VPS; chất lượng model thật và thử cài trên điện thoại vẫn mở.

**Source hiện tại (14/10/2026):** MVP và phần chat/Ollama đã merge vào `main` (code HEAD được review: `8833051`); [PR #1](https://github.com/rua-den/playroom/pull/1) đã merge. Đọc [review và stabilization gate 14/10](docs/reviews/2026-10-14-main-stabilization-review.md) trước khi triển khai tiếp. [Handoff 13/10](docs/handoff/2026-10-13-state.md) và [plan Luna trước đó](docs/superpowers/plans/2026-10-13-playroom-resume-plan.md) là bằng chứng/kế hoạch lịch sử, không phải trạng thái nhánh hiện tại. Vẫn ưu tiên test local; SSH/domain/Caddy để sau.

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
