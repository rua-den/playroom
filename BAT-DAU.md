# Mở Playroom trên Windows

## Chơi với model của bạn

1. Nhấp đúp **Start Playroom.cmd** trong thư mục Playroom.
2. Lần đầu, nhập email đăng nhập và mật khẩu ít nhất 12 ký tự trong cửa sổ vừa mở. Nhập lại mật khẩu để xác nhận; ký tự mật khẩu được ẩn khi gõ.
3. Trình duyệt tự mở khi ứng dụng sẵn sàng tại **http://127.0.0.1:8000**. Đăng nhập bằng tài khoản vừa tạo.
4. Vào **Cài đặt** để cấu hình model. Với API riêng, chọn **Custom / OpenAI-compatible**, nhập URL, model ID và API key nếu endpoint yêu cầu. Lưu cấu hình rồi chọn model kể chuyện; có thể đổi model ngay cạnh nút **Gửi**. Với OpenRouter hoặc Ollama Cloud, thêm credential và xác minh model theo luồng có sẵn.
5. Mở **Thư viện truyện**, chọn **Tạo truyện mới** hoặc **Nhập Legacy Bundle / Nhập Legacy**. Mỗi truyện có bối cảnh, nhân vật và lịch sử trò chuyện riêng. Truyện nhập vẫn chờ bạn duyệt hồ sơ, canon, ký ức và cảnh; bạn quyết định việc cho phép gửi context tới provider trước khi chủ động Gửi.

Trong **Thư viện truyện**, chọn **Mở truyện / Đọc tiếp** để trở lại truyện đã lưu. Màn trò chuyện ghi rõ **Đang đọc** và tên truyện. Tải lại sẽ mở truyện gần nhất đã chọn trên trình duyệt này; nếu chưa có lựa chọn hợp lệ, app mở thư viện. Nút **Thư viện truyện** luôn có để quay về danh sách. Chỉ nhấn **Tạo truyện mới** khi muốn bắt đầu một truyện riêng.

**Cài đặt**, **Hồ sơ và ký ức**, **Tạo truyện mới** và **Nhập dữ liệu** mở trong modal. Nút **Đóng** luôn ở đầu bảng; có thể nhấn **Esc** để quay lại truyện. Đóng rồi mở lại form tạo/nhập sẽ giữ bản nháp chưa lưu; sau khi tạo hoặc nhập thành công, form được làm mới. Lời đang gõ trong truyện vẫn được giữ khi mở các bảng này.

Khi lưu cấu hình, hồ sơ, ký ức hoặc cảnh, thông báo nổi xuất hiện ở góc trên màn hình. Thành công hiện khoảng 5 giây và tạm dừng khi rê chuột hoặc dùng bàn phím trên thông báo; lỗi có nút **Đóng** và vẫn có chi tiết cạnh form.

Key đã lưu trong GitHub Actions được giữ riêng trong môi trường kiểm thử đó. Bản local không tự lấy key từ GitHub; bạn nhập credential của mình ở **Cài đặt**, không gửi key qua chat.

Custom nhận API tương thích OpenAI Chat Completions, chẳng hạn base URL `http://127.0.0.1:1234/v1` hoặc URL đầy đủ kết thúc bằng `/chat/completions`. API local có thể bỏ trống key. HTTP chỉ dùng cho loopback; endpoint trên server cần HTTPS. Form không yêu cầu khai báo giá hoặc giới hạn token/ngân sách. App dùng ngân sách token mặc định; chi phí và quota Custom do endpoint quản lý, Playroom không coi chúng là miễn phí hay đã xác minh giá. Lưu cấu hình không gọi AI hoặc kiểm tra kết nối; chỉ khi bạn chủ động **Gửi** mới có yêu cầu kể chuyện. OpenRouter và Ollama Cloud vẫn giữ chính sách chi phí riêng.

Những lần sau chỉ cần mở lại cùng file **Start Playroom.cmd**. Tài khoản, chiến dịch và cấu hình được giữ trong `.playroom-live/`. Không cần tạo tài khoản lại. Giữ cửa sổ chạy app mở; nhấn **Ctrl+C** trong cửa sổ đó để dừng.

## Thử giao diện ngay, chưa cần API key

Nhấp đúp **Try Playroom Demo.cmd**. Bản demo mở tại **http://127.0.0.1:8001**, dùng dữ liệu riêng trong `.playroom-demo/`. Email và mật khẩu demo được hiện trong cửa sổ ở lần tạo đầu tiên; lưu lại để dùng cho những lần sau.

Demo dùng phản hồi mẫu lặp lại. Bạn có thể thử tạo chiến dịch, Gửi, tải lại, chỉnh hồ sơ/ký ức và import. Muốn đánh giá chất lượng kể chuyện của model thật, dùng **Start Playroom.cmd** và cấu hình model của bạn. Hai bản dùng kho dữ liệu riêng; dữ liệu demo không tự chuyển sang bản thật.

## Khi chưa mở được

Lần đầu launcher cần **uv**, **Node.js/npm** và kết nối mạng để cài các dependency đã khóa phiên bản, sau đó build giao diện. Thiếu công cụ hoặc build lỗi sẽ hiện hướng dẫn trong cửa sổ; không đóng cửa sổ trước khi đọc thông báo. Đây là bản chạy trên máy Windows hiện tại; chưa phải địa chỉ truy cập từ điện thoại.

Nếu cổng đang được dùng, dừng cửa sổ Playroom cũ rồi mở lại. Không xóa `.playroom-live/` để sửa lỗi khởi động: thư mục đó chứa dữ liệu và credential của bạn. Khi sao lưu, giữ riêng toàn bộ thư mục dữ liệu và không đưa nó lên GitHub.
