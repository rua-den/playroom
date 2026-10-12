# Playroom cá nhân — web ưu tiên điện thoại

Ngày: 12/10/2026. Trạng thái: đã review và sửa thiết kế, chưa triển khai. Thông tin trực tiếp mới nhất của người dùng về VPS: dùng Caddy; mô tả Nginx trong repo wedding-online là tài liệu cũ.

## 1. Mục tiêu đã xác nhận

Người dùng muốn một app/tool roleplay cá nhân, tham khảo Whif và kiểu chơi trong chat `playrooom`. Đã đổi lựa chọn sang ưu tiên điện thoại, mở mọi lúc qua một link web riêng; PC vẫn dùng được. Vấn đề cần giải quyết là quản lý context qua nhiều chương: nhân vật, quan hệ, sự kiện và trạng thái cảnh phải có nơi lưu, kiểm tra và sửa ngoài khung chat.

Mẫu chơi: người chơi điều khiển Henn; AI kể chuyện và đóng vai dàn nhân vật còn lại. Các lượt đã đọc chỉ bao gồm phần chương 25–29, không đủ để tái dựng toàn bộ thiết lập ban đầu. Không tự suy ra hồ sơ đầy đủ từ năm lượt cuối.

Mục tiêu kiểm chứng: sau một chiến dịch dài, app chọn đúng dữ kiện cần gửi cho AI, tôn trọng dữ kiện người chơi chốt, không trộn nhánh hoặc thế giới, và có thể giải thích vì sao một dữ kiện được đưa vào context. Không hứa LLM không bao giờ viết sai; phải có cơ chế nhìn thấy và sửa sai.

## 2. Phương án và quyết định đề xuất

| Hướng | Điểm thuận lợi | Đánh đổi |
|---|---|---|
| Web riêng ưu tiên điện thoại — đã chọn | Một link dùng trên điện thoại và PC; kiểm soát bộ nhớ và giao diện | Cần server lưu dữ liệu bền, HTTPS và đăng nhập riêng |
| Cấu hình một công cụ roleplay có sẵn | Có thể thử kiểu chơi sớm hơn | Khả năng sửa quy tắc bộ nhớ và luồng truyện phụ thuộc công cụ được chọn |
| Native desktop/Android từ đầu | Có thể tích hợp sâu với thiết bị | Tăng công việc đóng gói trước khi kiểm chứng lõi kể chuyện |

Hướng đã chốt: app web responsive ưu tiên điện thoại, backend chạy trên server riêng, dữ liệu SQLite trên ổ lưu trữ bền. Có thể thêm vào màn hình chính dưới dạng PWA trên trình duyệt hỗ trợ. PC của người chơi không phải bật để app hoạt động. AI qua API riêng; nhà cung cấp/model sẽ được chọn qua một bước cấu hình và thử chất lượng, không giả định dùng được tài khoản chat hiện tại làm API.

Repository: [rua-den/playroom](https://github.com/rua-den/playroom), do người dùng tạo. Checkout local hiện tại: `D:\stu\repo\playroom`. Tài liệu này đã được đưa vào repo; code ứng dụng và deployment chưa được triển khai. Các đường dẫn file trong implementation plan là relative với root repo này.

## 3. Phạm vi MVP

- Tạo thế giới, nhân vật và persona người chơi.
- Tạo chiến dịch, cảnh mở đầu và chơi qua luồng kể chuyện tiếng Việt có stream.
- Sửa dữ kiện cố định, trạng thái cảnh, quan hệ, lorebook và ghi chú sự kiện.
- Xem context trước khi gửi và bản context đã gửi ở từng lượt.
- Tóm tắt đoạn truyện và đề xuất bộ nhớ có nguồn; người chơi xem/sửa trước khi chốt.
- Tạo lại câu trả lời, chọn phiên bản, tạo nhánh tại một lượt cũ.
- Nhập transcript cũ theo định dạng rõ ràng, xem trước khi nhập; xuất và khôi phục chiến dịch.
- Đăng nhập một tài khoản chủ sở hữu, HTTPS, giao diện mobile, khôi phục trạng thái sau khi điện thoại mất mạng/tắt màn hình và manifest PWA.

Chưa đưa vào MVP: marketplace nhân vật, mạng xã hội, quảng cáo/gem, sinh ảnh, voice, đồng bộ nhiều server, chơi offline và APK. Hosting web có lưu trữ bền nằm trong MVP.

## 4. Năm lớp dữ liệu

| Lớp | Nội dung | Quy tắc |
|---|---|---|
| Canon/hồ sơ | Thế giới, nhân vật, cách xưng hô, điều người chơi đã chốt | Chỉ người chơi sửa hoặc duyệt; AI không âm thầm ghi đè |
| Trạng thái cảnh | Thời gian, địa điểm, người đang có mặt, mục tiêu, tình trạng đang diễn ra | Phân biệt người được nhắc đến với người thực sự có mặt |
| Sự kiện/quan hệ | Sự kiện đã xảy ra, lời hứa, quan hệ, việc chưa giải quyết | Có lượt nguồn, nhánh và thời điểm hiệu lực |
| Tóm tắt/lorebook | Tóm tắt đoạn cũ; kiến thức kích hoạt theo tên, alias và từ khóa | Là tài liệu hỗ trợ, không mạnh hơn canon hoặc nguồn gốc |
| Transcript | Toàn bộ lượt gốc và các phiên bản | Giữ nguyên nguồn; prompt mỗi lượt chỉ lấy phần cần thiết |

Sự kiện và quan hệ lưu dưới dạng văn bản có cấu trúc tối thiểu: chủ thể, nội dung, người liên quan, lượt nguồn và trạng thái duyệt. Không tạo hệ thống điểm tình cảm tự động trong bản đầu. Trong schema và fixture, một turn là một cặp hành động người chơi + câu trả lời AI được chọn; các candidate là revision của cặp đó. Transcript mới được chốt khi chọn candidate hoàn chỉnh, nhưng hành động/partial response vẫn được giữ trong job để không mất khi lỗi.

## 5. Vòng chơi và context

1. Người chơi nhập hành động/lời thoại. Bản nháp còn nguyên nếu mạng lỗi.
2. Backend đọc đúng đầu nhánh hiện tại và các phiên bản hồ sơ có hiệu lực.
3. Context composer chọn quy tắc chơi, canon cần thiết, trạng thái cảnh đã chốt, dữ kiện/lore liên quan, tóm tắt các đoạn cũ và các lượt gần đây chưa được tóm tắt.
4. Tạo bản xem trước: nội dung, nguồn dữ kiện, lý do chọn, phần bị bỏ và số token chính xác hoặc ước lượng được ghi rõ. Khi chơi thường, nút gửi tự chạy preview rồi gửi nếu hợp lệ; không bắt mở bảng kỹ thuật mỗi lượt. “Xem context” là thao tác tùy chọn, lỗi budget sẽ mở phần giải thích tương ứng.
5. Gửi AI; stream trả lời vào một phiên bản nháp. Lỗi/hủy không biến trả lời dở thành sự kiện đã xảy ra.
6. Câu trả lời hoàn chỉnh xuất hiện để người chơi chọn. Chọn “Dùng lượt này”, hoặc gửi hành động tiếp, sẽ chốt phiên bản đang chọn. Tạo lại trước khi chốt không đổi bộ nhớ.
7. Trích đề xuất sự kiện/cảnh/tóm tắt từ phần đã chốt. Hiện trạng thái “chờ duyệt”; chưa dùng chúng như sự thật đã chốt. Người chơi có thể duyệt theo lô ở cuối cảnh.

Trong lúc đề xuất cảnh chưa được duyệt, composer gửi cảnh đã chốt kèm các lượt mới nguyên văn, chỉ rõ các thay đổi mới còn nằm trong transcript. Không gửi một cảnh cũ như thể chắc chắn vẫn là hiện tại. Gợi ý cập nhật bộ nhớ ở mốc chuyển cảnh hoặc khi context đạt 75% trần input hữu dụng; không chờ một số lượt cố định vì một chương có thể rất dài. Người chơi duyệt theo lô, không bị bắt duyệt từng fact mỗi lượt. Nếu phần bắt buộc không còn vừa, cần duyệt/sửa bản tóm tắt hoặc tăng budget hợp lệ trước khi gọi AI tiếp.

Quy tắc điều khiển đề xuất: AI không tự tạo lời thoại, suy nghĩ hoặc quyết định mới cho Henn. AI có thể diễn đạt lại hành động Henn mà người chơi vừa nhập, mô tả tác động và phản ứng của NPC. Người chơi có thể sửa quy tắc này trong hồ sơ chiến dịch.

### Ngân sách context

- Mặc định trần input 12.000 token, dự trữ output 4.000 token, dự trữ bao gói 512 token. Đây là lựa chọn sản phẩm, không phải giới hạn của một model cụ thể.
- Input thực tế tối đa là giá trị nhỏ hơn giữa trần người chơi đặt và cửa sổ model trừ hai khoản dự trữ.
- Model config phải ghi context window và giới hạn output; không đoán cửa sổ từ tên model.
- Nếu có tokenizer phù hợp, dùng token thực. Nếu không có, dùng ước lượng bảo thủ, gắn nhãn “ước lượng” và cho phép đặt trần thấp hơn. Không bảo đảm request sẽ vừa chỉ bằng phép đếm ký tự.
- Các phần bắt buộc: quy tắc chơi, canon được ghim, cảnh đã chốt, phần diễn biến mới chưa có tóm tắt được duyệt, và hành động hiện tại.
- Phần mới chưa được nén chỉ được thay bằng tóm tắt đã duyệt có khoảng nguồn đúng; lượt gần nhất vẫn giữ nguyên văn. Test 120 lượt cần có fixture tóm tắt đã duyệt để kiểm tra chơi dài; không giả vờ gửi 120 lượt nguyên văn vào trần 12.000 token.
- Phần tùy chọn giảm theo thứ tự: lore ít liên quan, sự kiện xa ít liên quan, tóm tắt không liên quan. Không âm thầm cắt hành động người chơi hoặc canon bắt buộc.
- Khi phần bắt buộc không vừa, dừng trước khi gọi API và chỉ rõ phần nào cần rút gọn/duyệt tóm tắt.

### Tìm dữ kiện trong MVP

Dùng tên/alias nhân vật, từ khóa lore, nhân vật đang trong cảnh và truy vấn văn bản để chọn dữ kiện. Xếp hạng theo ghim, trùng chủ thể, độ liên quan từ khóa, việc chưa giải quyết và recency. Tie-break theo ID để preview lặp lại được. Lọc nhánh và thời điểm trước khi xếp hạng.

Chưa dùng vector database hoặc một agent riêng cho từng NPC. Chỉ thêm semantic retrieval khi bộ tình huống kiểm chứng cho thấy tìm bằng tên/từ khóa bỏ sót quan trọng.

## 6. Canon, tóm tắt và xung đột

Mỗi memory item có ID, loại, nội dung, entity IDs, source turn/revision IDs, origin (`user`, `import`, `ai`), trạng thái (`pending`, `approved`, `rejected`), phiên bản và state cursor hiệu lực trên nhánh. Trường cấu trúc tùy loại gồm `subject_id`, `predicate`, `value`/`object_id` và `supersedes_id`. Các slot đơn trị như vị trí nhân vật, chủ sở hữu đồ vật hoặc trạng thái quan hệ được so sánh bằng ID/predicate; tên/alias không phải identity. Alias trùng giữa hai nhân vật không tự gộp họ.

- Dữ kiện do người chơi tạo được duyệt khi lưu, nhưng vẫn có lịch sử chỉnh sửa.
- AI chỉ tạo đề xuất. Hai giá trị khác nhau cho cùng slot đơn trị đã chốt tạo conflict để người chơi xem nội dung và nguồn; thay đổi hợp lệ theo thời gian phải ghi supersession, không xóa giá trị cũ. Với văn bản tự do, phát hiện mâu thuẫn bằng AI chỉ là gợi ý, không hứa phát hiện mọi mâu thuẫn ngữ nghĩa. Nội dung có lượt nguồn hợp lệ vẫn có thể diễn giải sai và vẫn cần duyệt.
- Duyệt một dữ kiện mới có thể thay thế dữ kiện cũ từ một thời điểm, nhưng không xóa lịch sử hoặc ảnh hưởng nhánh khác.
- Tóm tắt chỉ lấy các lượt/revision đã chốt. Giữ khoảng lượt nguồn; không dùng bản tóm tắt nếu đoạn nguồn đã đổi nhánh hoặc đổi phiên bản.
- Khi tóm tắt được duyệt, nó thay cho lượt cũ trong prompt, không xóa transcript gốc trong DB.
- Tách đề xuất trích xuất khỏi generation chính; thất bại bước trích xuất không làm mất lượt truyện đã hoàn tất. Mỗi tác vụ summary/extraction có budget input/output riêng theo model; chia nguồn theo ranh giới lượt/đoạn khi quá dài, lưu coverage và chạy tiếp theo lựa chọn người chơi. Các job đã gọi provider nhưng chưa có kết quả chắc chắn không tự gửi lại sau restart. Chỉ job queued chưa dispatch mới được khôi phục tự động; lưu retry như attempt mới để không giấu chi phí gọi lại.

## 7. Phiên bản và nhánh

Transcript lưu lượt và các revision; branch lưu parent, checkpoint fork và lựa chọn revision. Memory/profile cũng có phiên bản. Một `StateCursor` gồm turn/revision đã chốt và state version tăng đơn điệu trên branch. Mỗi mutation chốt lượt, sửa hồ sơ, duyệt memory/scene/summary đều tạo checkpoint mới. Vì vậy sửa hai lần ở cùng một lượt vẫn phân biệt được. Snapshot tham chiếu các version ID bất biến, không dùng truy vấn “lấy bản mới nhất” để dựng lịch sử.

- Tạo lại lượt cuối: giữ bản cũ, tạo candidate mới; chỉ candidate được chọn/chốt mới thành nguồn memory.
- Muốn tạo lại một lượt đã chốt, kể cả lượt cuối, tạo nhánh tại checkpoint trước lượt đó rồi sinh lại. Candidate chưa chốt có thể tạo lại trên cùng branch. Không sửa quá khứ tại chỗ rồi giữ nguyên bộ nhớ tương lai.
- Fork kế thừa đúng transcript, hồ sơ, memory và tóm tắt tại checkpoint đã chọn. Mọi dữ kiện hay chỉnh sửa được duyệt sau checkpoint này bị loại, kể cả khi source của chúng là một lượt cũ.
- Context run lưu snapshot ID, hash payload, danh sách source IDs và model config dùng thực tế. Bản snapshot đã tạo không bị thay đổi bởi lần sửa hồ sơ sau đó.
- Một generation tại một thời điểm cho mỗi branch, tối đa hai provider job chạy đồng thời toàn app (kể cả consolidation); mỗi attempt timeout tổng mặc định 300 giây, cấu hình được theo provider. Preview/start/commit và mọi mutation state dùng expected state version, trả 409 nếu đã cũ. Khi một generation đang chạy, mutation canon/scene/memory trên branch đó trả 409; UI có thể giữ bản sửa nháp để áp dụng sau. Candidate hoàn chỉnh bị stale do sửa state vẫn được giữ để đọc/copy nhưng không commit vào state khác.
- UI tạo và lưu idempotency key trước khi gửi, backend reserve job trong transaction trước khi gọi provider. Nếu response đầu bị mất và UI chưa biết job ID, truy vấn status bằng key đó để lấy job cũ; không sinh key mới/tự gọi provider lại. Job idempotency áp dụng trên owner, branch và operation; cùng key nhưng payload khác trả 409. Retry tự động bên provider adapter mặc định tắt. Backend không bảo đảm provider không tính phí một request đã nhận trước khi timeout, nên không suy diễn phí từ trạng thái job.
- Điện thoại mất kết nối không tự hủy generation. Backend giữ job và tiến độ; UI mở lại sẽ lấy trạng thái/nội dung đã nhận theo job ID, không tự gửi một request AI mới. Chỉ nút hủy mới yêu cầu dừng. Khi server restart giữa request, giữ draft và đánh dấu interrupted; không âm thầm gọi lại một API có thể đã tính phí.
- Job và delta được lưu bền theo thứ tự; reconnect trả offset/cursor và nội dung hiện có, loại duplicate delta. Logout/thu hồi session chặn đọc stream mới ngay; kết nối dài kiểm tra session mỗi 15 giây và đóng khi revoke. Job có thể hoàn tất phía server nhưng không tiếp tục lộ nội dung cho session đã revoke.

## 8. Giao diện ưu tiên điện thoại

Điện thoại dùng một cột truyện, ô nhập phía dưới, danh sách chiến dịch trong drawer và nhân vật/cảnh/bộ nhớ trong sheet có thể mở khi cần. Tránh đặt ba panel cạnh nhau trên màn hình nhỏ. PC mở rộng thành ba vùng: chiến dịch/chương, truyện và bộ nhớ.

Kiểm tra ở độ rộng 360, 390 và 430 CSS px; không cuộn ngang. Nút chạm tối thiểu 44 CSS px, ô nhập/font đọc dễ chỉnh, xét safe-area và bàn phím ảo; ô nhập không che câu cuối hay nút gửi. Khi người chơi cuộn đọc lượt cũ, stream không kéo họ về cuối. Tab background/resume hiển thị đúng job đang chạy hoặc đã hoàn tất.

Các thao tác quan trọng: “AI đang nhớ gì”, “Xem context”, “Sửa cảnh”, “Duyệt bộ nhớ”, “Tạo lại”, “Dùng lượt này”, “Tạo nhánh” và “Xuất phiên”. Nội dung truyện render Markdown; raw HTML bị tắt.

Màn hình hồ sơ cho phép sửa nhân vật và alias; người chơi chọn persona và cast. Màn hình AI config cho endpoint/model/key, kiểm tra kết nối và giới hạn context/output. Key gửi cho backend lưu cấu hình được bảo vệ trên server, không trả lại nguyên key trong API đọc hoặc context preview.

## 9. Lưu trữ, nhập và vận hành

- SQLite lưu trên ổ bền dưới thư mục `shared/data/playroom.sqlite3` riêng của Playroom, có schema migration và transaction. Production dùng một app instance/worker; không đặt DB trong filesystem tạm của serverless hoặc autoscale nhiều bản app chia sẻ một file DB.
- Phát triển trên PC ở `127.0.0.1`; production qua reverse proxy HTTPS, UI và API cùng origin. Link riêng phải có đăng nhập, không coi URL khó đoán là quyền truy cập.
- Một tài khoản chủ được tạo bằng lệnh quản trị, không có đăng ký công khai. Hash mật khẩu bằng thư viện Argon2id; lưu session phía server, cookie HttpOnly/Secure/SameSite, hết hạn và revoke khi logout. Rate-limit login. Kiểm tra quyền trên cả read/stream/export và mutation, kiểm tra Origin/Host và chống request chéo site.
- API key không ghi vào transcript, prompt preview, export hay log. Export chiến dịch không chứa session đăng nhập hoặc provider secrets. DB backup quản trị có thể chứa bảng owner/session nên chỉ quản trị viên truy cập; khi restore server phải revoke session cũ. Provider secrets ở cấu hình server riêng, không nằm trong export chiến dịch.
- PWA manifest có tên, icon 192/512, start URL và standalone display. Cài qua thao tác trình duyệt hỗ trợ; không hứa cùng một nút cài hoạt động trên mọi hệ điều hành. Bản đầu không cache API/truyện riêng qua service worker; generation vẫn cần Internet.
- Dùng SQLite backup API để sao lưu DB đang hoạt động; không copy tùy tiện một file DB khi đang có WAL.
- Export JSON có `schema_version`, hồ sơ, turns/revisions, branches, memory, scene, summaries và snapshot metadata; không chứa provider secrets. Import tạo campaign mới, validate trước và commit nguyên transaction.
- Export kiểm tra giới hạn kích thước tương ứng importer trước khi tạo file chuyển phiên; không xuất thành công một file mà chính app không thể nhập. Campaign vượt giới hạn có thể tăng cấu hình transfer sau khi kiểm tra tài nguyên, hoặc dùng backup DB quản trị để khôi phục đầy đủ. Không cắt dữ liệu âm thầm.
- Nhập truyện cũ: nhận JSON turns hoặc TXT/Markdown người chơi đã đánh dấu lượt; không tự đoán chắc ai nói chỉ từ một khối văn bản. Preview cho chỉnh speaker/thứ tự và chọn “đây là đoạn trích” khi thiếu phần đầu. File tối đa 20 MiB trong MVP, kiểm tra kích thước trước khi đọc hết; import/validation có tiến độ và không chạy SQL/script lấy từ file.
- Với import transcript lịch sử: lưu raw trước, chia đoạn theo budget model, đề xuất tóm tắt và một hồ sơ/cảnh checkpoint tiếp tục chơi; người dùng duyệt checkpoint trước khi sinh truyện. Đoạn thiếu lịch sử được đánh dấu unknown. Các lượt trước checkpoint import chỉ là archive để tra; không cho fork tại thời điểm không có state lịch sử xác thực. Với export schema v1 của chính app, bảo toàn checkpoint/version references để fork và round-trip chính xác.
- Link chat `playrooom` là nguồn tham khảo hiện có, không phải cam kết app tự đồng bộ toàn bộ lịch sử ChatGPT. Chỉ nhập nội dung thực sự lấy được và người chơi duyệt.

## 10. Stack đề xuất

Frontend React + TypeScript + Vite. Backend Python 3.12 trở lên, FastAPI, Uvicorn, Pydantic và `sqlite3` stdlib. Node dùng để build frontend trên máy dev/CI, tối thiểu 22.12 trên nhánh 22 hoặc một phiên bản mới hơn được Vite hỗ trợ; không cần đổi Node đang chạy wedding-online. Lock dependency cụ thể khi tạo project và kiểm tra tương thích runtime.

Chọn hai runtime vì phần context/lưu trữ dễ cô lập để test bằng Python, frontend vẫn linh hoạt. Người dùng đã có VPS và xác nhận trực tiếp đang dùng Caddy. Repo wedding-online ghi Oracle ARM64, Node/PM2 và release/shared storage, nhưng phần Nginx/Certbot đã cũ và không được dùng làm sự thật về proxy hiện tại. OS chính xác, RAM/dung lượng trống, Python/systemd, domain thật và topology hiện tại vẫn cần live audit trước deploy.

Hướng deployment: thêm site block Playroom vào cấu hình Caddy đang hoạt động, reverse proxy về Uvicorn/systemd riêng serve API và frontend build, cùng thư mục release/shared riêng của Playroom. Không cài proxy thứ hai hoặc đổi process manager của wedding-online. Kiểm tra systemd/Python/port trống, Caddy version/config/storage và các site hiện có trước khi sửa. Đề xuất `127.0.0.1:3100` chỉ sau khi xác nhận port còn trống. Backend stream theo SSE với `Content-Type: text/event-stream`; Caddy hỗ trợ flush SSE ngay, vẫn phải kiểm tra chunk qua HTTPS trên version đang cài. Giữ certificate storage và cách cấp HTTPS hiện tại, không thêm Certbot mặc định.

Lưu bản cấu hình Caddy trước sửa, kiểm tra config đầy đủ với adapter/env đang dùng, rồi reload instance hiện tại khi được phép deploy. Không restart/cài lại Caddy để thêm một site. Check health các site đang chạy trước/sau; nếu reload hoặc Playroom health fail, phục hồi riêng cấu hình/ứng dụng bị thay đổi. DB restore chỉ thực hiện chủ đích, không gắn vào rollback code tự động.

Build/package đúng Linux ARM64, có Python wheel tương thích với runtime đã kiểm tra. Thư mục app, service, domain/subdomain, credentials, DB và backup đều riêng; không dùng chung database hay sửa release/shared của wedding-online. App gọi AI API ngoài nên không yêu cầu VPS chạy model/GPU. Không thuê server mới trong plan này.

Thứ tự nguồn deployment: thông tin trực tiếp mới nhất của người dùng (Caddy) → live inventory khi được thực hiện → repo/handoff lịch sử. Nguồn tham khảo release/persistence: [wedding-online DEPLOYMENT.md](https://github.com/rua-den/wedding-online/blob/main/DEPLOYMENT.md) và [handoff 2026-09-30](https://github.com/rua-den/wedding-online/blob/main/docs/superpowers/plans/2026-09-30-codex-handoff.md). Checkout tham khảo trên máy người dùng là `D:\stu\repo\wedding-online`. File Nginx cũ chỉ là tài liệu lịch sử, không copy vào Playroom. Các ví dụ domain/path không được coi là giá trị production thật. Giữ CD_ENABLED và dữ liệu SQLite/uploads/.env của wedding-online khi thao tác trên hạ tầng chung.

AI provider nằm sau interface riêng; MVP có fake provider để test không tốn tiền và một HTTP adapter cho endpoint có contract đã kiểm tra. Thay provider không thay schema memory. Không tự thử model có phí trước khi người chơi cấu hình key và chạy phép thử.

Tài liệu nền đã kiểm tra:

- [Vite Getting Started](https://vite.dev/guide/).
- [FastAPI](https://fastapi.tiangolo.com/).
- [Python sqlite3 và backup](https://docs.python.org/3/library/sqlite3.html).
- [PWA installability và khác biệt trình duyệt](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).
- [Caddy reverse proxy và streaming](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
- [Caddy validate/reload](https://caddyserver.com/docs/command-line).

## 11. Kiểm chứng và điều kiện hoàn thành

Test deterministic: cô lập thế giới/nhánh, budget, hồ sơ ghim, memory pending, tóm tắt stale, generation dở, restart, duplicate request, export/import và snapshot ở lượt cũ.

Kiểm chứng web/mobile: toàn bộ truyện/context/export cần session hợp lệ; logout chặn đọc kể cả kết nối stream đang mở; reconnect không sinh trùng lượt hoặc gọi AI lại, kể cả mất response trước khi nhận job ID. Smoke trên trình duyệt Android và iOS thực khi có thiết bị, ghi rõ nếu chỉ có viewport mô phỏng. Restart service và đổi release không làm mất DB; backup khôi phục ở thư mục dữ liệu mới được. Domain thật dùng HTTPS trước nghiệm thu truy cập từ Internet. Kiểm tra health các site hiện có trước/sau Caddy reload.

Bộ truyện kiểm chứng có ít nhất 120 lượt tổng hợp, có summary coverage đã duyệt, một lời hứa xa, hai người có alias gần nhau, thay đổi địa điểm, một nhân vật chỉ được nhắc đến, một mâu thuẫn slot canon và hai nhánh có kết quả khác nhau. Thêm tình huống duyệt memory từ source cũ sau điểm fork, import vượt budget và mất response job đầu. Đây là fixture kiểm tra chọn context, không phải bằng chứng AI kể truyện tốt.

Thử chất lượng thực với model được chọn: người chơi đánh giá giọng kể tiếng Việt, phân biệt NPC, quyền điều khiển Henn và giữ mạch sau 20 lượt tương tác. Ghi rõ model/config/context; mọi lần chạy có phí được tách khỏi test tự động.

MVP được nghiệm thu khi test dữ liệu/context đạt, giao diện hoàn thành vòng chơi và khôi phục được dữ liệu, bộ truyện kiểm chứng không rò dữ kiện sai nhánh, và người chơi chấp nhận chất lượng phiên thử. Không tuyên bố hoàn thành chỉ vì frontend build thành công.
