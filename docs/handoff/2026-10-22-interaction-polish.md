# Playroom — UI và tương tác ngày 22/10/2026

Base: `9feb15c` trên `origin/main`, đã gồm các chốt server về quyền điều khiển người chơi, phạm vi biết của NPC và thời gian có nguồn. Owner yêu cầu tiếp tục cải thiện UI/UX và chất lượng tương tác.

## Phạm vi

- Khung nhập giữ nhãn và vùng gõ rõ ràng, đưa gợi ý cách nhập cùng giải thích demo vào mục mở khi cần. Các điều khiển vẫn dùng bàn phím và có vùng chạm tối thiểu 44px.
- Hiện trạng thái lượt kể thay vì chỉ có nút Gửi bị vô hiệu hóa. Nút **Dừng lượt kể** dùng API cancel hiện có, giữ lời đang gõ và danh tính job để khôi phục; không tự tạo request sinh truyện mới.
- Màn duyệt import chia hồ sơ/NPC/cảnh/ký ức/đề xuất/nguồn thành các mục mở đọc. Bỏ khung cuộn lồng 240px. Cảnh báo nguồn và trạng thái import chưa hoàn tất phải hiện rõ; các xác nhận, consent và khóa Send phía server không đổi.
- Hướng dẫn narrator phản ứng sát lượt người chơi, giữ giọng đã thiết lập của từng NPC, tránh lặp mở đầu/mô tả không khí và dừng ở nhịp cảnh để người chơi tiếp tục. Không thêm regex cấm văn phong, luật chơi, chốt canon hay lượt gọi model.

## Chất lượng lời kể

Lý do sửa prompt đến từ [scorecard synthetic 21/10](../acceptance/2026-10-21-synthetic-story-quality-scorecard.md), không phải một benchmark mới. Regression kiểm tra request thật gửi tới fake provider vẫn có lời vừa nhập, lượt đã chốt trước đó, StyleProfile và hồ sơ NPC trong cả đường structured và legacy plain.

Hướng dẫn tốt hơn không chứng minh model đã kể hay hơn. Đợt này không gọi model thật, không dùng transcript riêng hay tự đổi model/mode/budget. Các chốt player agency, NPC knowledge, exact-time, wire budget và dữ liệu đã duyệt vẫn được kiểm tra như trước.

## Kiểm chứng và bước tiếp

Local: backend **501 passed, 1 skipped**; frontend **214 passed, 3 skipped**; production build/TypeScript và Python compileall PASS. Khung nhập idle trên Chromium 375px giảm từ **308px xuống 233px**, giữ summary có vùng chạm 44px; đã xem sáng/tối, mở mục bằng bàn phím và kiểm tra không tràn ngang ở 375/768px. Regression chiều cao đã thất bại ở bản 308px trước khi sửa CSS.

Full Chromium synthetic PASS: kể chuyện/reconnect, ChatGPT JSON/ZIP review, Legacy import/consent/fake Send, Library Trash desktop/mobile và live-local assembly với fake provider. Lượt chạy cuối giữ kiểm tra nội dung lịch sử thực sự hiển thị sau khi mở nhóm.

Test Dừng phủ thành công, lỗi, nhấn lặp, đổi owner/campaign khi request đang chạy, và kết quả cancel đến sau terminal poll. Luồng browser phải mở nhóm lịch sử trước khi kiểm tra nội dung thực sự hiển thị; không bỏ kiểm tra consent hay khóa Send để thích nghi với các mục thu gọn.

Kết quả local, ảnh trình duyệt, regression và CI trên đúng PR SHA/merged-main SHA được ghi trong PR bàn giao. Không chuyển kết quả của commit trước sang phiên bản mới. Chỉ coi thao tác Dừng thành công khi server xác nhận; phản hồi cancel đến muộn không được hồi sinh job đã kết thúc hoặc sửa chiến dịch khác.

Chưa nghiệm thu điện thoại vật lý/bàn phím ảo/Safari, official ChatGPT export đã sanitize (#27), hay deployment VPS/Caddy (#9). Không triển khai trong đợt này; dữ liệu và credentials local tiếp tục nằm ngoài Git.
