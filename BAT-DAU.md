# Mở Playroom trên Windows

## Chơi với model của bạn

1. Nhấp đúp **Start Playroom.cmd** trong thư mục Playroom.
2. Lần đầu, nhập email đăng nhập và mật khẩu ít nhất 12 ký tự trong cửa sổ vừa mở. Nhập lại mật khẩu để xác nhận; ký tự mật khẩu được ẩn khi gõ.
3. Trình duyệt tự mở khi ứng dụng sẵn sàng tại **http://127.0.0.1:8000**. Đăng nhập bằng tài khoản vừa tạo.
4. Vào **Cài đặt** để thêm credential của bạn, kiểm tra model rồi chọn narrator. Giữ chính sách free-only nếu bạn chỉ muốn dùng model miễn phí.
5. Tạo chiến dịch hoặc chọn **Nhập Legacy Bundle / Nhập Legacy** để nhập file truyện của bạn. Xem hồ sơ, canon, ký ức và cảnh; chiến dịch nhập vẫn chờ bạn duyệt. Bạn quyết định việc cho phép gửi context tới provider trước khi chủ động Gửi.

Key đã lưu trong GitHub Actions được giữ riêng trong môi trường kiểm thử đó. Bản local không tự lấy key từ GitHub; bạn nhập credential của mình ở **Cài đặt**, không gửi key qua chat.

Những lần sau chỉ cần mở lại cùng file **Start Playroom.cmd**. Tài khoản, chiến dịch và cấu hình được giữ trong `.playroom-live/`. Không cần tạo tài khoản lại. Giữ cửa sổ chạy app mở; nhấn **Ctrl+C** trong cửa sổ đó để dừng.

## Thử giao diện ngay, chưa cần API key

Nhấp đúp **Try Playroom Demo.cmd**. Bản demo mở tại **http://127.0.0.1:8001**, dùng dữ liệu riêng trong `.playroom-demo/`. Email và mật khẩu demo được hiện trong cửa sổ ở lần tạo đầu tiên; lưu lại để dùng cho những lần sau.

Demo dùng phản hồi mẫu lặp lại. Bạn có thể thử tạo chiến dịch, Gửi, tải lại, chỉnh hồ sơ/ký ức và import. Muốn đánh giá chất lượng kể chuyện của model thật, dùng **Start Playroom.cmd** và cấu hình model của bạn. Hai bản dùng kho dữ liệu riêng; dữ liệu demo không tự chuyển sang bản thật.

## Khi chưa mở được

Lần đầu launcher cần **uv**, **Node.js/npm** và kết nối mạng để cài các dependency đã khóa phiên bản, sau đó build giao diện. Thiếu công cụ hoặc build lỗi sẽ hiện hướng dẫn trong cửa sổ; không đóng cửa sổ trước khi đọc thông báo. Đây là bản chạy trên máy Windows hiện tại; chưa phải địa chỉ truy cập từ điện thoại.

Nếu cổng đang được dùng, dừng cửa sổ Playroom cũ rồi mở lại. Không xóa `.playroom-live/` để sửa lỗi khởi động: thư mục đó chứa dữ liệu và credential của bạn. Khi sao lưu, giữ riêng toàn bộ thư mục dữ liệu và không đưa nó lên GitHub.
