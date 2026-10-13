# Prompt mở thread tiếp theo

Làm việc trên nhánh `feat/playroom-mvp`. Trên máy hiện tại, dùng worktree `D:\stu\worktrees\playroom-mvp`; không reset/clean hoặc checkout nhánh này trong checkout khác đang dùng.

Copy phần bên dưới:

```text
Tiếp tục Playroom tại repo rua-den/playroom, nhánh feat/playroom-mvp.
Dùng worktree D:\stu\worktrees\playroom-mvp nếu còn tồn tại; kiểm tra Git status trước, giữ mọi thay đổi sẵn có.

Đọc AGENTS.md và C:\Users\huy.nguyen\.codex\RTK.md, rồi:
1. docs/handoff/2026-10-13-state.md
2. Global Constraints + task B1 trong docs/superpowers/plans/2026-10-13-playroom-resume-plan.md
3. Chỉ phần runtime spec liên quan epoch/cancel/result/cost.

Tuân thủ routing: Sol điều phối/review; gpt-5.6-luna medium viết code. Nếu Luna không khả dụng, dừng code và báo; không tự thay model.
CHỈ làm B1: bảo vệ mọi usage/result write sau director bằng transaction và current epoch/status/cancel CAS.
Không làm frontend, nhiệm vụ B2 trở đi, đổi kiến trúc lớn, gọi model thật hoặc deploy VPS.

Viết regression RED trước: đặt barrier SAU valid director result đã qua _require_active, tại post-result packing; connection khác cancel/recovery rồi thả writer. Một barrier trước provider return không chứng minh lỗi này.
Giữ ca hợp lệ: packing lỗi vẫn lưu đúng usage/output director, không treo dispatched hoặc guard; writer stale/cancelled không ghi result/billing/context/success mới.
Chỉ sửa generation.py và test_generation_fix4.py trừ khi test chứng minh phụ thuộc bắt buộc.

Chạy covering tests ghi trong B1, review diff, kiểm chứng độc lập và exact rtk proxy git diff --check BASE HEAD.
Không suy ra hoàn tất Task3 từ 135 test cũ; ba test quality SSE cũ có setup chưa hợp lệ, sẽ xử lý ở B2.
Commit phần B1 đã kiểm chứng; báo SHA, RED/GREEN thật, phạm vi review, lỗi còn mở. Sau B1 dừng coding batch để review, không tự nhảy task.
Báo cáo scratch phải ignored, không force-add .superpowers; cập nhật handoff sau khi gate B1 thực sự qua.
Không yêu cầu gửi API key/SSH/password vào chat.
```
