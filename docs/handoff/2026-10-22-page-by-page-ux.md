# Playroom — rà từng màn hình và luồng UI/UX, 22/10/2026

Base: `5fcfb3a` trên GitHub `main`. Owner yêu cầu tự kiểm tra từng trang và cải thiện bằng skill `ui-ux-pro-max`. Dùng React hiện có, giữ bảng màu/typography; không thêm thư viện hay thiết kế lại backend.

## Phạm vi đã đi qua

Kiểm tra trực tiếp bằng Chromium với tài khoản/SQLite demo riêng và dữ liệu Lan/Vy tự tạo. Mobile 375×812 là lượt đi đầy đủ; desktop 1440×1000 và landscape 812×375 dùng cho kiểm tra thích ứng và các panel liên quan. Không suy ra nghiệm thu điện thoại thật từ viewport mô phỏng.

| Màn hình / luồng | Điều đã kiểm tra | Kết quả và thay đổi |
| --- | --- | --- |
| Đăng nhập | Nhãn, autocomplete, mật khẩu sai, sửa và đăng nhập lại | Hoạt động; không đổi xác thực |
| Thư viện | Trống/có truyện, đọc tiếp, tạo mới, nhập nguồn | Không tràn ngang; giữ các hành động hiện có |
| Tạo truyện | Trường bắt buộc, thêm NPC, lưu và mở truyện | Giữ validation và phản hồi sau server acknowledgement |
| Xóa / Thùng rác | Xác nhận, xóa mềm, tải danh sách, khôi phục | Khôi phục trực tiếp qua Thùng rác; Undo còn có regression browser riêng |
| Trang kể | Trạng thái trống, composer, mở model và tác vụ | Giữ khung nhập gọn từ PR #83 và bản nháp có scope |
| Menu truyện | Chọn truyện, tạo và nhập hai loại nguồn | Thoát/quay lại có đường rõ ràng |
| Hồ sơ | Sửa NPC, đổi tab rồi quay lại | Sửa lỗi mất bản nháp do unmount editor |
| Ký ức | Bản nháp, loại/phạm vi, nguồn summary, metadata | Thu trường nguồn/quan hệ nâng cao; giữ provenance và payload |
| Cảnh | Trống, thêm, tên, hiện diện, chọn cảnh hiện tại, lưu | Hướng dẫn trống; label radio từ 19px thành vùng chạm 44px |
| Model kể chuyện | Chưa có model khả dụng, đi tới Cài đặt | Giữ ngữ nghĩa chỉ áp dụng cho lượt mới |
| Cài đặt kết nối | OpenRouter/Ollama/Custom, demo notice, trường key | Trợ giúp đúng provider; thu nội dung phụ; chặn thao tác lặp khi đang lưu |
| Cài đặt model/chi phí | Điều hướng mục, cap, token nâng cao, consent | Cap bắt buộc luôn hiện; token tùy chọn thu gọn; không đổi spending gates |
| Nhập ChatGPT | Chọn JSON, đọc local, chọn thread, preview, nhập | Dùng nguồn synthetic; giữ xác nhận riêng và Send khóa sau import |
| Duyệt checkpoint | Hồ sơ/cảnh/nguồn và các checkbox | Không tự duyệt canon hoặc mở Send |
| Nhập Legacy | Chọn bundle, preview khoảng trống, consent | Chuẩn hóa xưng hô; bỏ số chương của một nguồn riêng khỏi UI chung |
| Modal / thông báo | Focus, Escape, scrolled body, stacked toast, portrait/landscape | Vùng thông báo riêng theo modal đang trên cùng, không che tiêu đề/Đóng |

## Các lỗi đã tái hiện

- Trên base, gõ ký ức rồi chuyển sang Cảnh và quay lại làm nội dung rỗng. Các editor nay giữ mount sau lần mở đầu tiên, ẩn tab không hoạt động và reset theo campaign/branch. Bản nháp không tự trở thành dữ liệu đã duyệt và không hứa sống qua reload.
- Toast thành công che tiêu đề/nút Đóng modal 375px. Toast nay theo stack modal thực tế, có vùng riêng giữa header và nội dung cuộn; stack dài có giới hạn chiều cao.
- Form Ký ức đưa nhiều trường UUID/quan hệ lên trước dữ liệu đã lưu. Metadata nâng cao nay mở khi cần; khoảng revision bắt buộc của summary vẫn hiện.
- Radio chọn cảnh có input 18×18px và label cao 19px. Nhãn bọc control nay có vùng chạm cao 44px.
- Cài đặt OpenRouter hiện hướng dẫn Free dành riêng cho Ollama; cap USD bắt buộc nằm trong mục thu gọn. Sửa điều kiện hiển thị và thứ tự thông tin, giữ nguyên chính sách server.
- Chữ phụ sáng `#6e6255` trên nền raised `#e9dfcd` đo được 4,49:1. Chỉnh token thành `#6d6154` ở cả theme sáng rõ ràng và chế độ theo thiết bị.

## Kiểm chứng và giới hạn

Các lỗi tìm thấy ở bản sửa trung gian (metadata trùng ID, portal toast làm assertion nhận node đã tháo) được giữ như bằng chứng cần sửa trước bàn giao. Một test chạy riêng xanh không thay thế bộ frontend đầy đủ.

Local cuối: **222 frontend passed, 3 skipped**, TypeScript/production build PASS; full Chromium synthetic/import/Legacy/Library Trash/live-local fake-provider PASS. Một lượt browser trước đó thất bại ở font italic fallback: fixture đã chờ `document.fonts.ready` trước khi browser bắt đầu tải đủ biến thể. Sửa đồng bộ bằng `document.fonts.load` từng style/weight và render frame; giữ nguyên assertion CDP cấm fallback. Không dùng `force=True` để vượt kiểm tra click.

Đã kiểm tra trực tiếp bản nháp hồ sơ/ký ức/cảnh còn nguyên khi đổi tab và đóng/mở panel; form không trùng ID; toast thực sự nằm trong modal, ngoài `inert`, và nút Đóng thao tác bình thường. Tương phản chữ phụ/nền raised sáng sau sửa **4,56:1** (trước 4,49:1); theme tối giữ 5,74:1. Scene radio có label cao 44px.

Kết quả cuối và CI đúng PR/merged-main SHA được ghi trong PR. Không có thay đổi production backend, inference thật, cấp ngân sách thật hoặc VPS/Caddy. Chưa nghiệm thu Safari, điện thoại/bàn phím ảo thật, screen reader thật, zoom/chữ hệ thống lớn nhất và sample export chính thức đã sanitize (#27).

Điều hướng URL/back và header mobile còn có thể cải thiện ở đợt riêng; lần này không thêm router hoặc đổi cách chọn truyện. Không đánh dấu toàn bộ accessibility PASS.
