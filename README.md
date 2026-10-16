# Playroom

App roleplay cá nhân bằng tiếng Việt, ưu tiên điện thoại và mở qua một link web riêng. Người chơi điều khiển nhân vật của mình; AI dẫn truyện và đóng vai các nhân vật còn lại.

Trọng tâm là quản lý context qua nhiều chương: lưu hồ sơ, cảnh, sự kiện, quan hệ, tóm tắt và transcript riêng; xem được AI đang dùng dữ kiện nào, sửa được khi nhớ sai, và giữ bộ nhớ đúng theo nhánh truyện.

## Trạng thái — 16/10/2026

**Chuyển giao hiện hành:** Chủ dự án chọn **Codex Astra** làm coding agent. Đọc [handoff mới nhất](docs/handoff/2026-10-16-codex-astra-transfer.md) và [AGENTS.md](AGENTS.md) trước khi code. `main` của GitHub là source of truth. Bài viết/các SHAs bên dưới là bằng chứng tại từng mốc, không thay cho CI của commit tương lai.

- **B1–B3**: Send/reconnect, narrator JSON/cast/version và Chromium synthetic gameplay PASS ([PR #3](https://github.com/rua-den/playroom/pull/3), [#5](https://github.com/rua-den/playroom/pull/5), [#7](https://github.com/rua-den/playroom/pull/7), [#8](https://github.com/rua-den/playroom/pull/8)).
- **Ngân sách**: opt-in cumulative/per-send spending grants qua [PR #11](https://github.com/rua-den/playroom/pull/11), Free-first UI qua [PR #13](https://github.com/rua-den/playroom/pull/13), Gemma4 Cloud starter `gemma4:31b` qua [PR #16](https://github.com/rua-den/playroom/pull/16), cơ chế chặn rủi ro trừ credits mua thêm qua [PR #18](https://github.com/rua-den/playroom/pull/18). Giá/giới hạn nội bộ là dự toán, không phải bảo đảm hóa đơn provider.
- **Model thật đã gọi và PASS**: [Gemma4 synthetic 3-turn Action #38721810244](https://github.com/rua-den/playroom/actions/runs/38721810244), 3/3 lượt chuẩn JSON, Vy đúng ID/version; tổng **2.042 input + 513 output tokens**, chi phí tính toán **USD 0.00049108** (không phải hóa đơn). [CI tại cùng SHA #38721810166](https://github.com/rua-den/playroom/actions/runs/38721810166) PASS backend/frontend/Chromium. Thử nghiệm chỉ dùng Lan/Vy/Bình giả lập, **không** gửi BANGTAN/Henn riêng tư.
- **Đang triển khai import**: [Issue #27](https://github.com/rua-den/playroom/issues/27), [PR #28](https://github.com/rua-den/playroom/pull/28) là slice đầu tiên cho JSON export ChatGPT chọn đúng một thread, có bước duyệt checkpoint riêng trước khi Send. Xem kiểm chứng mới bên dưới và CI đúng SHA trong PR. ZIP/lịch sử dài chưa được triển khai đầy đủ. [Issue #29](https://github.com/rua-den/playroom/issues/29) là **đường import riêng** cho `playroom_legacy_story_bundle` không phải transcript ChatGPT nguyên bản, không được bịa nội dung còn thiếu.
- **Chưa PASS**: [B4 app thật/điện thoại/VPS Issue #9](https://github.com/rua-den/playroom/issues/9) và [Chromium reconnect flake #20](https://github.com/rua-den/playroom/issues/20). Bản demo local dùng fake provider theo hướng dẫn bên dưới; **chưa có URL production/điện thoại được nghiệm thu**.
- **Phê duyệt chi phí:** Owner đã cho tối đa **USD 5** để kiểm chứng API với tình huống giả lập; đây là **trần rủi ro**, không phải mục tiêu tiêu hết hay cho phép gửi dữ liệu riêng, bỏ qua grant, hoặc tự đổi Caddy/VPS. Lần gọi thêm cần tuân thủ per-send/total grant và kiểm soát provider.

**Cập nhật review gate:** [PR #28](https://github.com/rua-den/playroom/pull/28) đã có bước duyệt checkpoint riêng, khóa Send bền trong SQLite và kiểm tra lại ngay trước provider dispatch, kể cả job cũ sau restart. Giao diện hiển thị hồ sơ/cảnh/ký ức, phạm vi biết và phần nguồn bị bỏ qua trước khi duyệt. Kiểm chứng độc lập local: **320 backend, 94 frontend PASS / 3 skipped, typecheck/build/Chromium PASS**; chỉ merge khi CI đúng SHA của PR và main xanh. [Handoff kiểm chứng mới](docs/handoff/2026-10-16-import-review-gate.md) ghi RED/GREEN, commit và giới hạn của slice JSON.

**Ưu tiên tiếp theo:** hoàn thiện import ZIP/lịch sử dài của #27 và legacy bundle #29 → xử lý #20 và #9 → phê duyệt riêng cho triển khai điện thoại. [Handoff 16/10](docs/handoff/2026-10-16-codex-astra-transfer.md) giữ các giới hạn dữ liệu, chi phí và VPS; không coi slice JSON là hoàn thành toàn bộ import.

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
