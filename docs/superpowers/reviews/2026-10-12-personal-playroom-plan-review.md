# Review plan Playroom — 12/10/2026

Phạm vi: review thiết kế và implementation plan; không review code app vì chưa có project implementation. Các sửa đổi dưới đây đã được đưa vào cả spec và plan, với test scenario cho lúc triển khai.

## Những vấn đề tìm thấy và đã sửa

| ID | Mức | Vấn đề trong bản trước | Sửa trong bản hiện tại |
|---|---|---|---|
| R1 | P1 | Dùng Nginx/Certbot từ tài liệu wedding làm cấu hình deploy hiện tại, trái thông tin mới nhất của người dùng | Chốt Caddy hiện có; kiểm tra config/version/storage; thêm site block, validate/reload và health các site hiện có. Không cài proxy thứ hai. |
| R2 | P1 | Fork theo turn/source cutoff chưa phân biệt các lần sửa memory/profile ở cùng lượt; memory duyệt về sau từ source cũ có thể lọt vào quá khứ | StateCursor và checkpoint bất biến chứa version IDs; fork theo checkpoint, có test same-turn mutation và old-source/new-approval. Reroll lượt đã chốt luôn tạo branch. |
| R3 | P1 | Gợi ý tóm tắt sau năm lượt và coi mọi lượt chưa nén là bắt buộc có thể làm phiên chơi chương dài hết budget trước khi được nhắc | Gợi ý ở 75% budget hoặc cuối cảnh; summary coverage đã duyệt thay phần cũ, giữ cặp lượt gần nhất. Fixture 120 lượt có coverage thực, không giả định toàn bộ raw vừa context. |
| R4 | P1 | Reconnect theo job ID chưa xử lý mất response trước khi UI biết ID, và chưa quy định implicit retries/queued-vs-dispatched | Lưu key phía UI trước send; reserve job atomically; lookup theo key; payload mismatch 409; offsets chống lặp; tắt implicit retries và không replay attempt không chắc đã gọi provider. Có quota/timeout. |
| R5 | P1 | Import lịch sử dài và full-summary thiếu giới hạn input; không thể suy ra trạng thái đầy đủ để fork từng lượt của một chat cũ | Chia đoạn theo budget, lưu coverage/progress, duyệt checkpoint tiếp tục chơi. Raw cũ là archive trước checkpoint; export chính app giữ checkpoint. Export/import có limit tương ứng và remap references. |
| R6 | P2 | Vòng chơi bắt người dùng thao tác preview/quản lý nhiều, và phải chờ hết tám task mới có link thử trên điện thoại | Preview-then-send tự động; bảng context tùy chọn; duyệt memory theo lô. Tách ba mốc: context test, phone trial sau Task 4, MVP chơi dài. |
| R7 | P2 | Yêu cầu phát hiện mâu thuẫn canon chưa định nghĩa thế nào là conflict, dễ hứa quá mức cho văn bản tự do | Slot subject/predicate/value và supersession cho conflict rõ ràng; free-text detection chỉ là gợi ý. Source hợp lệ không chứng minh diễn giải đúng. Alias trùng không gộp NPC. |
| R8 | P2 | Logout mới chặn request sau nhưng chưa quy định stream đã mở; commit/edit từ hai tab thiếu guard nhất quán | Session-check 15 giây cho stream; expected state version cho mutations; khóa effective memory edits khi generation chạy, giữ draft; candidate stale không commit vào state khác. |

## Hướng sau review

Giữ React/TypeScript/Vite + FastAPI/Uvicorn + SQLite. Triển khai qua Caddy trên VPS sẵn; Uvicorn/service, shared data và subdomain của Playroom tách riêng. Caddy có cơ chế flush SSE theo Content-Type; kiểm tra trên version cài thực tế trước nghiệm thu. Tham khảo [Caddy streaming](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) và [validate/reload](https://caddyserver.com/docs/command-line).

Chưa có lý do để thêm vector DB, Redis, nhiều AI agent/NPC hoặc native APK trước khi kiểm chứng truyện thật. Bộ nhớ có nguồn và cơ chế sửa quan trọng hơn số lượng subsystem.

## Các quyết định/gate còn mở

- Chọn endpoint/model thực, giới hạn context/output, tokenizer và ngân sách thử ở Task 3. Không coi account ChatGPT hiện có là API key.
- Domain/subdomain, live OS/architecture/RAM/disk, Python/systemd, Caddy config và SSH access được xác minh ở bước deployment. Chưa audit hoặc sửa VPS trong lượt review này.
- Chỉ năm lượt gần nhất của playrooom đã được đọc. Nhập phiên thật cần raw nội dung và người chơi duyệt hồ sơ/cảnh; không tự dựng toàn bộ quá khứ.
- Routing code bắt buộc theo AGENTS: `gpt-5.6-luna`, medium, orchestrator review/verify. Model này không xuất hiện trong danh sách spawn đang công bố; phải xác nhận dispatch khi được yêu cầu triển khai, dừng nếu không khả dụng. Không đổi model ngầm.

## Kết quả review

Các lỗi thiết kế xác định ở R1–R8 đã được sửa trong tài liệu. Plan có mốc để dựng/test lõi và thử trên điện thoại sớm. Đây chưa phải bằng chứng app giữ context tốt: cần test deterministic, thử model thật và nghiệm thu người chơi như plan quy định.

Đã kiểm tra cấu trúc task, liên kết spec, thuật ngữ/checkpoint/budget/Caddy và các regression scenario trong hai tài liệu. Không có test app, build, paid AI call hoặc production deploy nào được chạy trong lượt review tài liệu này.
