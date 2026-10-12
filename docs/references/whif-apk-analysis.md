# Whif APK và hướng làm app roleplay cá nhân

Ngày phân tích: 12/10/2026. Đây là báo cáo tham khảo được chuyển từ workspace phân tích APK; các file APK và JavaScript trích xuất không được đưa vào repo Playroom.

## Kết luận

Có thể xây một app riêng với các luồng chơi tương tự Whif. APK cho phép đọc nhiều phần của giao diện và giao tiếp với máy chủ, nhưng không cung cấp trọn bộ hệ thống AI ở phía máy chủ. Chưa thể hứa tái tạo chính xác chất lượng trả lời, prompt nội bộ hoặc cơ chế bộ nhớ của Whif chỉ từ APK.

Đối với kiểu chơi trong chat `playrooom`, hướng phù hợp là một phòng truyện nhiều nhân vật: người chơi nhập hành động và lời thoại của Henn, AI kể diễn biến và đóng vai các nhân vật còn lại. Chất lượng giữ mạch truyện qua nhiều chương là yêu cầu chính.

## Đầu vào và phạm vi đã đọc

- File: `whif.xapk`, 45.450.060 byte.
- SHA-256: `2bf3bd9c363d57c9af4ec6066f3154c7ed575d6cd440a0b18f209099656e2cbb`.
- Manifest XAPK: package `io.whif`, phiên bản `1.3.54`, version code `148`, Android tối thiểu SDK 24.
- Base APK bên trong: `io.whif.apk`, kèm các APK cấu hình ngôn ngữ, mật độ màn hình và kiến trúc.
- Đã trích 393 file JavaScript, CSS, HTML và JSON vào `analysis/` trong folder `whif`, để đọc tĩnh. APK gốc không bị chỉnh sửa.
- Đã đọc 5 lượt chơi gần nhất mà công cụ trả về từ chat `playrooom`, tương ứng chương 25–29. Đây không phải toàn bộ lịch sử hoặc hồ sơ nhân vật của phiên chơi.
- Chưa chạy giao diện Whif, chưa đăng nhập hay gọi API của Whif, chưa xây app mới.

## Những gì xác nhận được từ client

| Phần | Bằng chứng trong APK | Ý nghĩa |
|---|---|---|
| Đóng gói Android | `assets/capacitor.config.json`, `assets/public/index.html` | App dùng Capacitor và chứa giao diện web đã build. |
| Playroom | Route `/playroom/create`, `/playroom/:id`, `/playroom/:id/edit` trong `index-D0BwWbx2.js` | Playroom là một luồng riêng trong client. |
| Nhân vật | `character-form-CvHy1Nt9.js` | Có trường nhân vật, tính cách, lời mở đầu, lorebook; lời mở đầu có prompt và điều kiện. |
| Người chơi và dàn nhân vật | `persona-edit-page-BCHXUuJ_.js`, `chat-v2-create-group-page-C0UJ0E-P.js`, `chat-v2-room-page-B6f0nsh9.js` | Có persona người chơi và phòng nhiều nhân vật. |
| Ghi nhớ | `memory-page-esvFZI0a.js` | Có sửa `summary_text`, yêu cầu AI tóm tắt, lựa chọn `full` và `recent20`. Không chứng minh được cách máy chủ chọn toàn bộ ngữ cảnh. |
| Ký ức sự kiện | `memory-multiplier-slider-B8Y5TlJs.js`, `index-D0BwWbx2.js` | Có service list/edit/delete/pin, các mode auto/important_only/disabled và field lossless_restatement/keywords. |
| Hướng dẫn ký ức | `resource-rest-CHVqvDJ8.js` | UI tiếng Việt mô tả tự lưu sự kiện, gọi lại tối đa 20 ký ức liên quan, ghim để luôn tham khảo và cửa sổ cũ để tránh lặp với phần gần đây. Đây là mô tả UI, không là chứng minh retrieval backend. |
| Hệ số nhớ | `memory-multiplier-slider-B8Y5TlJs.js` | Slider có giá trị 1, 1.5, 2, 2.5, áp dụng theo phòng hoặc mọi phòng; có tính giá phía UI. Chưa xác định ý nghĩa token/window phía server. |
| Lorebook | `lorebook.transformer-B5A1flxv.js` | Client gửi nội dung, từ khóa kích hoạt, trạng thái bật, cờ quan trọng và công khai. Chỉ xác nhận cấu trúc dữ liệu gửi đi. |
| Trả lời và biến thể | `ai.client-HE4jkZeP.js`, `chat-v2-room-page-B6f0nsh9.js` | Có nhận trả lời theo stream, reroll, dữ liệu branch và lựa chọn branch. |
| Trạng thái truyện | `chat-v2-room-page-B6f0nsh9.js` | Client xử lý HUD, cửa sổ trạng thái, lệnh playroom, gợi ý lượt tiếp và cờ hoàn thành scenario. |
| Chọn model | `model-react-query-BvQPx4VL.js` | Danh sách model được lấy từ service; client phân biệt phạm vi `chat` và `playroom`. Không thể suy ra đầy đủ model đang phục vụ chỉ từ APK. |
| AI phía máy chủ | `ai.client-HE4jkZeP.js` | Client POST tin nhắn với Bearer token tới máy chủ LLM, gồm các route `/v2beta/chats` và `/v2alpha/narrative/chat/{roomId}`. |

Các file JavaScript được liệt kê nằm dưới `whif/analysis/assets/public/assets/` trong workspace gốc `D:\Tool\platform-tools-latest-windows\platform-tools\mindgraph-apk`. Chúng là code đã bundle/minify, không phải source project gốc; các đường dẫn này không phải file trong repo Playroom.

## Cơ chế bộ nhớ đáng tham khảo sau khi đọc sâu

Whif client có cả tóm tắt hội thoại, event-memory riêng, ghim quan trọng và lorebook. UI mô tả ký ức cũ vẫn được gọi khi liên quan; các bản tiếng Nhật/Korean ghi chỉ gọi phần được trích từ trước 40 messages gần nhất để giảm lặp. Translation Việt diễn đạt cửa sổ này ít rõ hơn. Client lấy pin limit qua entitlement, fallback 20, nên không coi số 20 là invariant cho mọi account/mode.

Điều mình học cho Playroom: lưu event có nguồn riêng khỏi summary, ghim dữ kiện, retrieval theo diễn biến, tránh gửi cùng sự kiện lặp cả trong raw recent/summary/event. Không sao chép máy móc giới hạn 20/40 hoặc multiplier. Chưa có chứng cứ backend dùng vector DB, model cụ thể, relevance formula hoặc prompt nào; các phần đó phải thiết kế và thử riêng.

## Đối chiếu với phiên chơi hiện tại

Trong các lượt đọc được, người chơi nhập hành động và lời thoại của Henn. AI trả lại chương truyện bằng tiếng Việt, có thời gian, địa điểm, nhiều cảnh và nhiều người nói. Dàn nhân vật gồm Minji, Linh Chi, Mai, Ngọc Anh, Sora, Yoongi và các nhân vật khác. Câu chuyện gần nhất là trận chung kết bóng chuyền Bangtan–Seorin.

App riêng cần giữ được cả dữ kiện cố định lẫn diễn biến mới: tên và vai trò nhân vật, cách xưng hô, quan hệ, vị trí hiện tại, kết quả trận đấu, lời hứa và các chi tiết người chơi đã thiết lập. Quy tắc AI không tự quyết định hành động mới của nhân vật người chơi là đề xuất cần người dùng xác nhận, không phải điều đã được xác nhận từ toàn bộ phiên chơi.

## Hướng đề xuất, chưa triển khai

1. Web app/PWA cá nhân: có thể mở trên PC và điện thoại, ưu tiên kiểm chứng chất lượng chơi trước. Đây là hướng đề xuất ban đầu.
2. Dùng cùng nền web rồi đóng gói Android bằng Capacitor: phù hợp nếu cần APK và tích hợp thiết bị. Tài liệu chính thức: https://capacitorjs.com/docs.
3. App desktop dùng AI local: có thể nghiên cứu nếu ưu tiên chạy trên máy riêng, nhưng cần biết cấu hình máy và thử chất lượng kể chuyện tiếng Việt trước khi chọn.

Các lựa chọn trên là đánh giá ban đầu. Hướng đã chốt sau đó là web ưu tiên điện thoại, backend trên VPS sẵn của người dùng và Caddy hiện có; xem [thiết kế hiện tại](../superpowers/specs/2026-10-12-personal-playroom-design.md) và [plan đã review](../superpowers/plans/2026-10-12-personal-playroom-implementation-plan.md) làm nguồn quyết định.

Bản đầu nên tập trung vào tạo thế giới và dàn nhân vật, persona người chơi, phòng kể chuyện, hồ sơ và tóm tắt có thể sửa, lorebook, tạo lại câu trả lời, lưu và xuất phiên chơi. Cơ chế snapshot để quay lại hoặc rẽ nhánh cần được thiết kế sao cho trạng thái truyện và bộ nhớ đi theo đúng nhánh.

Luồng dự kiến: hành động người chơi → chọn hồ sơ/lore liên quan và trạng thái cảnh → AI viết tiếp → lưu lượt trả lời và cập nhật dữ kiện. Dữ kiện do AI đề xuất phải có cách kiểm tra và sửa; không nên để tóm tắt tự động ghi đè sự kiện đã chốt mà người chơi không biết.

Hạ tầng đã chọn trong thiết kế hiện tại: VPS của người dùng và Caddy. Provider/model runtime vẫn cần cấu hình và thử, với cả quality/economy và free-only policy; xem [runtime context policy](../superpowers/specs/2026-10-12-runtime-ai-context-policy.md). Việc chuyển toàn bộ phiên `playrooom` cần thêm lịch sử và hồ sơ đầu truyện; năm lượt cuối chỉ đủ để hiểu mẫu chơi và một phần trạng thái hiện tại. Xem [mẫu giọng kể và đánh giá](playrooom-style-and-evaluation.md).
