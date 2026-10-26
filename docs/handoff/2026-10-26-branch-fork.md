# Playroom — nhánh truyện (fork) từ checkpoint, 26/10/2026

Base: `c03dde5` trên GitHub `main`. Checkpoint này gồm backend/API và UI chọn nhánh; **không** gọi provider, không deploy, không đọc/ghi secret. Toàn bộ fixture trong test và dữ liệu demo là dữ liệu tự tạo.

## Vì sao chọn checkpoint này

- [Thiết kế](../../superpowers/specs/2026-10-12-personal-playroom-design.md) yêu cầu "tạo lại câu trả lời, chọn phiên bản, tạo nhánh tại một lượt cũ" và "fork kế thừa đúng transcript, hồ sơ, memory và tóm tắt tại checkpoint đã chọn".
- [Plan triển khai Task 6](../../superpowers/plans/2026-10-12-personal-playroom-implementation-plan.md) (`test_branch_isolation.py`, `fork_branch(...)`, reroll, UI "Tạo nhánh từ đây") **chưa có mục nào được đánh dấu hoàn thành**; [handoff 13/10](2026-10-13-state.md) ghi "Chưa triển khai; timeline hiện có một số nền tảng"; [handoff import](2026-10-16-import-review-gate.md) ghi "No public fork operation exists yet".
- Hai issue mở còn lại (#27 official export thật, #9 điện thoại vật lý/VPS) cần dữ liệu và quyền của owner, không thể làm trong repo. Vì vậy đây là hạng mục sản phẩm lớn nhất còn thiếu và implementable.

## Thay đổi

1. **`timeline.fork_branch`**: tạo branch mới từ một checkpoint của branch nguồn, copy nguyên snapshot (profile/memory/scene/retrieval/turn+revision đang chọn). Mutation sau đó trên branch nguồn không đi vào nhánh mới. Branch mới giữ `parent_branch_id`, `fork_checkpoint_id`, cursor `head_turn_id/head_revision_id` = lượt dùng chung cuối, và `state_version` tiếp nối đúng checkpoint nguồn.
2. **Review gate import không bị bỏ qua**: checkpoint đầu của nhánh mới có `parent_checkpoint_id` = checkpoint nguồn, nên chuỗi duyệt canonical của import vẫn quyết định Send. Fork một checkpoint chưa nằm dưới checkpoint đã duyệt vẫn bị chặn.
3. **Khóa và tính nhất quán**: từ chối khi branch nguồn đang có generation (branch guard), khi `expected_state_version` cũ, khi checkpoint thuộc campaign/branch khác hoặc owner khác, và khi tên nhánh trùng.
4. **Đánh số lượt**: `_next_turn_sequence` nối tiếp sau transcript kế thừa. Trước đây lượt mới trên nhánh fork sẽ bắt đầu lại từ sequence 1 và bị xếp sai thứ tự context.
5. **Lịch sử ký ức theo nhánh**: `branch_checkpoint_bounds` giới hạn row của từng branch tổ tiên đúng tới điểm fork, nên bản sửa memory mà branch nguồn ghi vào "tương lai bị bỏ" không hiện trong lịch sử nhánh mới.
6. **API owner-scoped**: `GET /api/campaigns/{campaign_id}/branches` (kèm `is_root`) và `POST /api/campaigns/{campaign_id}/branches` với `source_branch_id`, `checkpoint_id`, `expected_state_version`, `name` tùy chọn. Chưa đăng nhập trả 401; owner khác nhận 404.
7. **Reroll**: hành vi cũ (gửi lại trên cùng branch khi candidate chưa chốt) nay có regression riêng; chỉ candidate được chọn mới thành lượt đã chốt.
8. **Projection cho UI**: mỗi lượt trả `turn_branch_id` và `turn_checkpoint_id` (checkpoint ngay sau lượt đó, lấy theo branch sở hữu để không nhầm với checkpoint của nhánh fork), và payload có `branches` kèm `fork_turn_sequence`. Nhờ vậy UI fork đúng cả với lượt kế thừa từ nhánh trước mà không cần request phụ khi mở truyện.
9. **UI "Tạo nhánh từ đây"**: mỗi lượt có nút fork; thanh **Nhánh truyện** để chuyển nhánh, hiện "Nhánh 2 · từ lượt 1". Sau khi tạo nhánh, UI tự chuyển sang nhánh mới và nạp projection của nhánh đó. Lượt mới chỉ ghi vào nhánh đang đọc; `refreshProjection` giữ nguyên nhánh đang đọc thay vì quay về nhánh gốc. Lỗi 409 hiện thông báo rõ và giữ nguyên nhánh hiện tại. Nhánh đang đọc được ghi nhớ theo từng truyện trong phiên (không đưa vào URL/router).

## Bằng chứng

- RED trước sửa: test rò rỉ lịch sử ký ức thất bại khi tạm khôi phục filter cũ (row version 2 của branch nguồn lọt vào nhánh fork), rồi xanh sau `branch_checkpoint_bounds`. `fork_branch` trước checkpoint này chưa tồn tại nên toàn bộ nhóm fork là RED theo nghĩa thiếu API.
- `backend/tests/test_branch_isolation.py`: **11 passed** — checkpoint kế thừa đúng, loại trừ mutation sau checkpoint, hai nhánh giữ kết cục riêng, cutoff chung không có kết cục nào, lịch sử ký ức không rò tương lai bị bỏ, nhánh fork sinh truyện từ context kế thừa và commit cục bộ, từ chối stale/locked/foreign/unowned, chuỗi duyệt import, reroll candidate, projection trả đúng nguồn fork cho lượt hiện tại và lượt kế thừa, HTTP auth/owner-scope.
- Frontend: **241 passed, 3 skipped** (20 file). Ba test AppShell mới: tạo nhánh từ lượt cũ rồi tự chuyển nhánh; chuyển nhánh không gọi lại `getCampaign`; lỗi 409 giữ nguyên nhánh và hiện đúng thông báo. `tsc --noEmit` và `npm run build` PASS.
- Full backend: **592 passed**. `compileall` và `git diff --check` sạch.
- Kiểm chứng bằng API thật trên demo loopback (fake provider, SQLite riêng trong `.playroom-demo/`, đã ignore): tạo campaign, hai lượt commit, fork "Nhánh 2" từ lượt 1, projection của nhánh mới chỉ còn lượt dùng chung và danh sách nhánh hiện `fork_turn_sequence = 1`.
- Một lượt full suite có 1 failure ở `test_generation_durable::test_restart_during_partial_narration_preserves_partial_and_blocks_late_candidate` (race thời điểm giữa delta draft và restart). Test đó không đi qua code của checkpoint này; chạy lại toàn file 5 lần liên tiếp đều pass và full suite các lượt sau cũng pass. Ghi nhận là flake timing có sẵn, chưa sửa trong checkpoint này.

## Còn lại

- **Reroll một lượt đã chốt** vẫn là hai bước: tạo nhánh tại checkpoint của lượt trước rồi gửi lại action; chưa có nút/endpoint "Tạo lại" tự động.
- Chưa có đổi tên/xóa nhánh; chưa cập nhật `campaigns.updated_at` khi tạo nhánh.
- Nhánh đang đọc chỉ thuộc phiên UI (Map theo truyện), **không** nằm trong URL nên Back/Forward và tải lại trang sẽ mở lại nhánh gốc; muốn giữ thì cần thêm tham số URL và cập nhật history.
- Chưa kiểm tra bằng trình duyệt thật trong checkpoint này: UI mới được phủ bằng Vitest/jsdom và kiểm tra API trên demo loopback; chưa chụp màn hình, chưa thử Safari, bàn phím ảo hay điện thoại thật.
- Không gọi AI thật, không deploy VPS/Caddy, không dùng export ChatGPT thật hay dữ liệu truyện riêng.
