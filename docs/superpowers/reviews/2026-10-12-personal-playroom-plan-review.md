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

## Review vòng hai trước code

Nguồn thay đổi: người dùng ưu tiên model mạnh khi có thể, cần tiếp tục chơi bằng free models, và muốn học cơ chế Whif/giọng kể playrooom. Repo trước vòng này chưa mô tả các lựa chọn đó đủ để coding agent hiện thực đúng.

| ID | Mức | Vấn đề tìm thấy | Sửa và nhiệm vụ kiểm chứng |
|---|---|---|---|
| R9 | P1 | Keyword-only plan chưa thể hiện context director mạnh vừa được bàn | Thêm runtime policy, SelectionPlan được validate, hai mode; Task 2/3 kiểm tra ID/nguồn/mandatory và đúng stage counts. |
| R10 | P1 | Free fallback chưa có quyền chi phí hoặc xử lý quota/model unavailable | Free-only/capped-paid độc lập mode, kiểm tra credential tier và pricing, không silent paid/provider fallback; Task 3/4/8 có quota/billing regressions. |
| R11 | P1 | Đổi model có thể bị lẫn với đổi story state, ảnh hưởng memory/candidate | Tách settings_revision khỏi checkpoint truyện, job ghi role/profile snapshot; Task 3/6 kiểm tra switch không đổi canon/style/history. |
| R12 | P1 | Output 4.000 dễ bị hiểu là 4.000 token truyện, không có quy tắc terminal refusal/max-token | Total-output accounting theo adapter; incomplete/refusal giữ draft; Task 3/4 test finish reasons/schema/hidden reasoning. |
| R13 | P2 | Một cảnh phẳng và memory chung không phân biệt góc cảnh/kiến thức NPC | Focus/parallel scene và knowledge_scope/known_by có nguồn; Task 1/2/5/6 và model trial kiểm tra không teleport/biết chuyện chưa nghe. |
| R14 | P2 | Event memory Whif và style playrooom còn ở chat, thiếu trong repo | Bổ sung reference và StyleProfile, pins/edit/tombstone/retrieval modes, dedup không làm mất pinned promise; task coverage matrix cụ thể. |
| R15 | P2 | Phone trial, import và nghiệm thu model lẫn mức độ hoàn thành | Chỉnh README đúng task, giữ import đầy đủ ở Task 7; ghi số lượt thử thật, quality/economy cần benchmark riêng; chưa claim app/model pass. |
| R16 | P2 | Logout bị diễn đạt “ngay” trong khi stream chỉ kiểm tra theo chu kỳ | Ghi đúng bound 15 giây cho stream, request mới chặn ngay; không hứa thu hồi bytes đã gửi. |
| R17 | P1 | Quality/batch nhiều stage có thể nhân cost cap; đổi secret mutable có thể đổi billing tier của job cũ | Cap tổng parent/batch, preflight aggregate/remaining và credential version snapshot; Task 3 có pricing/tier/key/cost regressions. |
| R18 | P1 | “Import atomic” có thể bị hiểu là giữ transaction SQLite xuyên nhiều AI calls | Tách raw import transaction ngắn và campaign importing, job chunk sau đó; checkpoint thủ công được, chuyển playable sau approve; Task 7 kiểm tra quota failure/progress. |
| R19 | P1 | Restore một backup có job queued có thể dispatch lại việc đã chạy sau backup, gây gọi API trùng | Execution epoch mới và restored jobs không dispatchable kể cả queued; Task 7 kiểm tra tình huống backup-before-dispatch/restore. |
| R20 | P1 | Ghim/approved scene cũ dễ bị xem là hiện tại tuyệt đối, đóng băng diễn biến mới đã chốt | Dynamic blocks có as-of cursor, pin không đóng băng giá trị; raw committed updates khác canon invariants; Task 2 test promise thay đổi và invariant không bị retcon. |

Đã thêm [runtime AI contract](../specs/2026-10-12-runtime-ai-context-policy.md) và [style/evaluation reference](../../references/playrooom-style-and-evaluation.md), nối vào spec, plan, README và AGENTS. Mô tả kỹ thuật đã đối chiếu với tài liệu provider về schema, quota và output-token accounting; chưa có paid API trial.

Model cụ thể vẫn là candidate, availability/cost phải xác minh khi cấu hình. Required coding model gpt-5.6-luna vẫn không được tool list hiện tại công bố; review không tự cho phép đổi model hay bắt đầu code với orchestrator.

## Kết quả review

Các lỗi thiết kế xác định ở R1–R20 đã được sửa trong tài liệu. Có coverage matrix cho từng yêu cầu và mốc dựng/test lõi, thử điện thoại rồi chơi dài. Chưa phát hiện thêm mâu thuẫn tài liệu trong lượt rà này; đây không phải bằng chứng app giữ context tốt. Vẫn cần deterministic tests, thử model thật, nghiệm thu người chơi và gate routing trước code.

Đã kiểm tra cấu trúc task, liên kết spec, thuật ngữ/checkpoint/budget/Caddy và các regression scenario trong hai tài liệu. Không có test app, build, paid AI call hoặc production deploy nào được chạy trong lượt review tài liệu này.
