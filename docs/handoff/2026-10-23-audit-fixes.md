# Playroom — sửa lỗi và UX sau audit 23/10/2026

Owner yêu cầu lấy latest, rà toàn bộ rồi “xử lý đi / continue”. Base GitHub main: `83b29b595bbe93bda843eed165e1c7f4a77e3c3f`. Implementation do các agent Astra theo AGENTS hiện hành; orchestrator review diff và chạy xác minh độc lập. Không dùng private story/key trong fixture, không gọi inference thật, không đổi VPS/Caddy.

## Thay đổi

1. **Custom credential:** origin gắn với credential được nhớ ngay khi key lưu thành công, kể cả profile POST thất bại. Đổi origin xóa liên kết key; retry cùng endpoint vẫn giữ key. Không truyền key thật trong test.
2. **Cảnh:** khóa chỉnh sửa/Lưu cho tới khi GET đầu tiên thành công, có trạng thái tải và thử lại khi lỗi, bỏ qua response của branch cũ; khóa thao tác trong lúc lưu.
3. **Player agency:** chỉ nhận ủy quyền từ action span có chủ thể người chơi/ẩn danh người chơi; câu ghép không kế thừa quyền từ NPC. Cho phép lặp lại đúng cảm xúc đã viết, chặn đổi cảm xúc và tránh nhầm câu tả NPC có tên người chơi ở vị trí tân ngữ. Đây vẫn là heuristic có độ tin cậy giới hạn, không phải bộ hiểu toàn bộ ngữ nghĩa.
4. **Hồ sơ:** chỉnh giọng, tính cách, kiến thức và hướng dẫn style riêng. Giữ kiểu text/list và metadata khác; dữ liệu object nhập vào được giữ nguyên, có giải thích nhưng chưa có editor object tổng quát.
5. **Ký ức:** chọn người biết theo tên, giữ ID trong payload và provenance, hiển thị ID chưa có hồ sơ để người dùng chủ động xử lý. Nguồn tóm tắt hiện số lượt và đoạn trích; Map tra nhãn tránh tìm tuyến tính cho từng option trong lịch sử dài.
6. **Kết nối:** trạng thái “Bước tiếp theo” dựa trên cấu hình đã lưu, không hứa đã kết nối/chơi được chỉ vì Save thành công. Hạn trial chọn bằng giờ thiết bị, kiểm tra tương lai và chuyển UTC; không thay spending/consent gates.
7. **History:** Back/Forward theo truyện và các panel, query story chỉ được mở nếu thuộc catalog của owner. Giữ editor/composer đang mount và bỏ state của phiên owner cũ. Sau create/import thành công, form tạm được thay bằng truyện mới để Back không dựng lại form rỗng. Không thêm router hoặc thay header mobile.
8. **Backup:** module [playroom.backup](../../backend/playroom/backup.py) dùng SQLite backup API và kiểm tra integrity/foreign keys; output mới và restore directory mới, không ghi đè. Restore đổi epoch, revoke session và paid grant, ngắt mọi job chưa hoàn thành kể cả candidate, giữ draft/cost evidence và không replay. Secrets không nằm trong backup; phải nhập key và chọn model lại. Xem [hướng dẫn](../backup-restore.md).
9. **Continuity 21 lượt:** authenticated TestClient → queued generation → polling by-key → candidate → commit, cùng request replay mỗi lượt. Lượt 11 thêm approved summary cho tám revision đầu và đổi cảnh; các context sau giữ summary/cảnh, đúng 21 provider calls và 21 revision. Chỉ dùng fake provider, không chấm chất lượng văn thật.

## Regression và kiểm chứng

- RED trước sửa: custom/cảnh 4 failures, onboarding 5 failures; agency 8 failures, hồ sơ 2 failures. Bổ sung các ca câu ghép sau review cũng RED trước khi sửa. Backup ban đầu chưa có module nên collection RED.
- Full backend: **542 passed, 1 skipped**; backup riêng **9 passed**. Root chạy thêm policy/generation/durable **97 passed** và frontend trọng điểm **49 passed**.
- Full frontend cuối: **238 passed, 3 skipped**, 20 files. TypeScript/production build, compileall và `git diff --check` PASS.
- Full Chromium synthetic/import/Legacy/Library Trash/live-local fake provider PASS trước thay đổi cuối chỉ xử lý consumed-form history; thay đổi cuối có AppShell **42 passed** và full frontend/build chạy lại. Kết quả real-browser ở exact PR SHA và main SHA phải đọc trong GitHub Actions/PR, không suy từ lượt local trước đó.
- Kiểm tra UI trực tiếp với demo/database riêng: Back đóng hồ sơ, Forward mở lại giữ draft; sau tạo truyện Back về thư viện không dựng lại form. Viewport 375×812: named audience hiển thị Vy, document width 375px, dialog 359px, không tràn ngang.

Một agent chạm usage limit giữa lượt; sau owner “continue”, các agent hoàn tất backup và regression consumed-form. Không coi lượt bị cắt là kết quả test thành công. Mã nguồn được review và commit theo từng nhóm; kết quả CI đúng PR/main SHA nằm trong PR release của checkpoint này.

## Còn lại

- [#27](https://github.com/rua-den/playroom/issues/27): official ChatGPT export thật đã sanitize; không dùng Legacy làm bằng chứng thay.
- [#9](https://github.com/rua-den/playroom/issues/9): điện thoại vật lý, bàn phím/lock/background reconnect; VPS/domain/Caddy cần đúng quyền triển khai riêng.
- Trial model thật 20–50 lượt và người đọc chấm giọng/logic/canon chưa chạy trong checkpoint này. Test 21 lượt fake chỉ chứng minh state continuity và idempotency.
- Safari, screen reader thật, tốc độ trên điện thoại và custom/OpenRouter endpoint thật chưa được nghiệm thu. Cấu trúc quan hệ nâng cao vẫn có ID; object-shaped profile guidance chưa chỉnh trực tiếp. Backup chưa mã hóa/lập lịch; Windows phải dùng thư mục riêng có ACL phù hợp, filesystem cần hard-link support.
