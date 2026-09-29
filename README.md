# Công cụ lấy bài viết và bình luận Threads

Công cụ này mở Threads bằng trình duyệt thật, tìm bài theo từ khóa, lấy nội dung bài viết cùng các bình luận, xác định nội dung cha của từng bình luận và đưa dữ liệu đã làm sạch lên Google Sheets.

Phù hợp cho người không chuyên IT dùng trên Windows. Dữ liệu cũng được lưu dự phòng tại `crawled_data/threads_records.jsonl`, vì vậy có thể dừng và chạy tiếp mà không cào lại nội dung đã có.

## Công cụ lưu những gì?

Mỗi dòng trên tab `raw_data` là một bài viết hoặc một bình luận. Nếu tab đang trống, chương trình tạo cấu trúc tiếng Việt sau:

| Cột | Ý nghĩa |
|---|---|
| `ma_du_lieu` | Dấu vân tay dùng để chống trùng |
| `thoi_gian_thu_thap_utc` | Thời điểm lấy dữ liệu |
| `chu_de`, `tu_khoa` | Nhóm chủ đề và từ khóa đã tìm |
| `loai_noi_dung` | `bai_viet` hoặc `binh_luan` |
| `noi_dung` | Nội dung đã làm sạch, vẫn giữ nguyên emoji |
| `noi_dung_cha` | Bài viết hoặc bình luận cha trực tiếp |
| `ma_noi_dung`, `ma_cha` | Mã ẩn danh để dựng lại cây bình luận |
| `tac_gia_an_danh` | Mã tác giả đã ẩn danh |
| `lien_ket_nguon`, `danh_sach_anh` | Để trống theo mặc định nhằm giảm dữ liệu nhận diện |

Nếu tab đã dùng cấu trúc nghiên cứu 19 cột (`collected_at` … `image_urls`) của dự án, chương trình tự nhận dạng và ghi đúng cấu trúc đó, không sửa dữ liệu cũ. Trong cấu trúc này, `post_text` là bài gốc, `parent_comment_text` là bình luận cha trực tiếp và `target_text` là nội dung của dòng hiện tại. Bình luận cấp một có bài viết làm cha nên `parent_comment_text` để trống; nội dung cha nằm ở `post_text`.

Chương trình tự bỏ ký tự điều khiển và khoảng trắng thừa; làm mờ đường dẫn, email, số điện thoại và @tên-người-dùng. Emoji đơn, cờ và emoji gia đình ghép vẫn được giữ nguyên. Nội dung được gửi lên Sheets ở chế độ văn bản thô nên chuỗi bắt đầu bằng dấu `=` không bị chạy như công thức.

Các chuỗi chỉ thể hiện tương tác như `239K lượt xem`, `26,7K lượt xem` hoặc `5.2K views` không được coi là nội dung. Nếu Sheet đã có dòng cũ mắc lỗi này, lần crawl kế tiếp sẽ ghi đè nội dung đúng vào chính dòng đó. Bảng được định dạng nền trắng, chữ đen và các cột nội dung tự xuống dòng.

Các nhãn giao diện lặp lại như `Hàng đầu`, `Xem hoạt động`, `Chưa có câu trả lời nào`, `Trả lời <tài khoản>...`, dấu `/` hoặc `\` đứng riêng và phần điều khoản/chính sách ở chân trang cũng được loại theo từng dòng. Nếu một bài hoặc bình luận có quote post khác, `target_text` chứa thêm phần `[Bài viết được quote]` và nội dung của post được quote.

## Chuẩn bị lần đầu

### 1. Cài Python

Tải Python 3.11 trở lên từ [python.org](https://www.python.org/downloads/). Khi cài, nhớ đánh dấu ô **Add Python to PATH**.

### 2. Cài công cụ

Nhấp đúp `setup_windows.bat`. Cửa sổ sẽ tự cài các thư viện và trình duyệt Chromium cần thiết. Việc này chỉ cần làm một lần và cần kết nối Internet.

Nếu cửa sổ báo không tìm thấy lệnh `py`, hãy khởi động lại máy sau khi cài Python rồi thử lại.


### 3. Điền cấu hình

Dự án hiện đã có `config.yaml` (theo từng người) và `.env`. Khi cài ở máy mới mà chưa có hai file này:

1. Tạo thư mục mới "configs" ở root Bỏ file config anh gửi từ zalo vào.
2. Sao chép `.env.example`, đổi tên bản sao thành `.env`. Và thay cấu hình anh gửi ở Zalo
3. Tạo thư mục "secrets" ở root bỏ file nckh2627-ce003a8221f1.json vào thư mục đó

Không thêm dấu ngoặc kép quanh các giá trị trong `.env`.

## Cách chạy hằng ngày

1. Nhấp đúp `run_windows.bat`.
2. Khi trình duyệt mở, đăng nhập Threads nếu được yêu cầu. Chương trình không đọc hay lưu mật khẩu.
3. Khi đã thấy trang chủ Threads, quay lại cửa sổ chữ màu đen và nhấn **Enter**.
4. Có thể thu nhỏ cửa sổ, nhưng không đóng trình duyệt mà chương trình đã mở.
5. Mở Google Sheet để theo dõi dữ liệu mới.

Muốn dừng, bấm `Ctrl + C` trong cửa sổ chữ màu đen. Dữ liệu đã xử lý xong vẫn được giữ lại. Lần chạy kế tiếp sẽ tự bỏ qua dòng đã có và bù lên Sheet những dòng trước đó chưa tải lên được.

## Đổi từ khóa giáo dục, số lượng hoặc tốc độ

Mở `config.yaml` bằng Notepad.

- `target_per_topic`: tổng số bài và bình luận cần lấy cho mỗi nhóm.
- `education_keywords`: từ khóa học tập như môn học, bài tập, thi và học phí.
- `education_context_keywords`: từ khóa nhận diện bối cảnh trường, lớp, sinh viên và ký túc xá.
- `learning_environment_topics`: chủ đề đời sống/cảm xúc xảy ra trong môi trường học đường.
- `max_comments_per_post`: số bình luận tối đa xem trong mỗi bài.
- `min_delay_seconds` và `max_delay_seconds`: thời gian nghỉ ngẫu nhiên giữa hai thao tác.
- `max_actions_per_minute`: giới hạn thao tác trong một phút.

Thiết lập mặc định chờ 3–6 giây và không quá 12 thao tác/phút. Đây là mức cố ý chậm để giảm tải lên Threads và giảm nguy cơ tài khoản bị giới hạn. Không nên giảm các khoảng nghỉ. Hãy chạy vào thời gian phù hợp, chỉ lấy dữ liệu công khai cần thiết và tuân thủ điều khoản của nền tảng cũng như quy định bảo vệ dữ liệu áp dụng cho nghiên cứu.

Crawler chỉ dùng ba danh sách giáo dục nói trên. Các nhóm kinh tế, xã hội tổng quát, công nghệ và môi trường không còn được tìm kiếm.



