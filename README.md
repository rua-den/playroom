# Playroom

App roleplay cá nhân bằng tiếng Việt, ưu tiên điện thoại và mở qua một link web riêng. Người chơi điều khiển nhân vật của mình; AI dẫn truyện và đóng vai các nhân vật còn lại.

Trọng tâm là quản lý context qua nhiều chương: lưu hồ sơ, cảnh, sự kiện, quan hệ, tóm tắt và transcript riêng; xem được AI đang dùng dữ kiện nào, sửa được khi nhớ sai, và giữ bộ nhớ đúng theo nhánh truyện.

## Trạng thái

Repo hiện chứa tài liệu thiết kế, kế hoạch triển khai và review ngày 12/10/2026. Chưa có code ứng dụng, lệnh chạy app, kết quả test ứng dụng hoặc production deployment.

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
- AI: endpoint/model qua API được chọn khi triển khai; tài khoản ChatGPT hiện tại không được giả định là API access.
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
