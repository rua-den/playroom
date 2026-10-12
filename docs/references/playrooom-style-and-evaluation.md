# Playrooom — mẫu kể chuyện và bài kiểm tra

Nguồn: [chat playrooom do người dùng chỉ định](https://chatgpt.com/c/6ac937ef-4aec-83ec-8752-5a365da5ed30). Ngày đọc: 12/10/2026. Công cụ trả về năm cặp lượt chương 25–29, không có trang lịch sử cũ hơn. Đây là mẫu cấu trúc/giọng kể và tiêu chí đánh giá; không phải toàn bộ canon của thế giới.

## Những điểm quan sát được

- Người chơi nhập hành động và lời thoại của Henn; AI mở rộng thành chương có thời gian, địa điểm, đối thoại và cao trào.
- Câu chuyện cắt qua lại giữa sân và khán đài; nhiều NPC phản ứng riêng theo vai trò, không chỉ lặp một lời khen chung.
- Đan xen căng thẳng, hài hước và cảm xúc. Một vật nhỏ như sữa dâu trở thành chi tiết liên kết giữa các cảnh.
- Lời hứa của Linh Chi thay đổi theo diễn biến: một tuần rồi một tháng. Đây là thay đổi có nguồn cần giữ lịch sử, không tự coi hai giá trị là lỗi hay âm thầm giữ bản đầu.
- Có bảng trạng thái/tỉ số, nhân vật bị mệt và vị trí đang đứng; câu trả lời dừng ở một điểm để người chơi tiếp tục. Không phải lượt nào cũng ghi literal “Đến lượt Henn”.

## StyleProfile cho app

Profile gồm ngôn ngữ, độ dài, mức emoji/heading, mức mô tả hành động, đối thoại, chuyển góc cảnh và quy tắc quyền điều khiển persona. Preset đầu: tiếng Việt, chương nhiều cảnh, đối thoại phân biệt NPC, cao trào xen hài/cảm xúc, dừng ở điểm người chơi có thể hành động. Có preset cảnh ngắn do người chơi chọn cho lúc hạn chế quota/output; không tự đổi style chỉ vì model free.

StyleProfile version đi theo checkpoint truyện. Nó không lưu model/credential; đổi model không bỏ style. Few-shot nếu cần phải là ví dụ tổng hợp hoặc đã bỏ canon/tên/sự kiện riêng, tránh làm một chiến dịch mới nhận cả kết quả trận đấu từ mẫu. Không commit raw transcript hoặc dữ liệu import cá nhân làm fixture public.

## Scene và ai biết gì

State cần phân biệt focus scene và cảnh phụ đang hoạt động: mỗi scene có location/time/present entity IDs. Nhân vật chỉ được nhắc đến không thành người có mặt. Chuyển góc nhìn sang khán đài không tự di chuyển cầu thủ lên đó.

Memory có `knowledge_scope` (`public`, `known_by`, `narrator_only`) và `known_by_entity_ids` khi được xác định. “Sự thật của thế giới” khác điều từng NPC biết; có mặt không bảo đảm nghe được một lời nói nhỏ. Nếu chưa biết ai chứng kiến, dùng narrator_only và known_by rỗng, không tự suy ra người biết; “unknown” là cách diễn đạt tình trạng này, không là enum thứ tư. AI chỉ đề xuất cập nhật kiến thức có nguồn. Prompt có chú thích kiến thức theo nhân vật; đây là quy tắc cần test với narrator thật, không là bảo đảm LLM luôn tuân thủ.

## Bộ kiểm chứng tổng hợp

1. Lời hứa xa: nhắc gián tiếp bằng đại từ, phải gọi đúng sự kiện/đối tượng từ nguồn cũ.
2. Supersession: lời hứa đổi thời lượng, giữ cả lịch sử và bản hiệu lực đúng checkpoint.
3. Cảnh song song: sân và khán đài, giữ vị trí, có phản ứng từ hai nhóm mà không teleport hoặc lẫn người đang có mặt.
4. Kiến thức: một NPC chưa nghe lời hứa riêng không được nói như đã biết; director/narrator phân biệt fact chung và known_by.
5. Quyền persona: không tạo lựa chọn/lời thoại mới cho người chơi; dừng để người chơi hành động.
6. Style transfer: đổi model/free mode, vẫn giữ tiếng Việt và giọng kể đã chọn; không kéo canon mẫu sang campaign mới.
7. Giới hạn output: response bị cắt giữa chương không được chốt thành một lượt hoàn chỉnh; draft còn nguyên.

Deterministic tests kiểm tra provenance, scene/knowledge annotations và budget. Chất lượng đối thoại, cảm xúc, nhịp cảnh và hàm ý chấm qua model trial/người chơi: persona agency và sai state là lỗi phải sửa; các mục giọng kể/NPC/nhịp cảnh đánh giá 1–5, nhắm ít nhất 4/5 theo người chơi. Không dùng một LLM tự chấm làm bằng chứng duy nhất.
