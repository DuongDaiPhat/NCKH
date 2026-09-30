# Hướng dẫn chia công việc crawl cho 4 người

Bốn em dùng cùng mã ẩn danh do người điều phối cung cấp và cùng một Google Spreadsheet, nhưng mỗi em có danh sách từ khóa, thư mục tiến độ và tab Sheet riêng. Không đổi file config cho nhau trong quá trình chạy.

## Phân công

| Người | File cấu hình | Tab Google Sheet | Dữ liệu dự phòng |
|---|---|---|---|
| Người 1 – Học tập cơ bản | `configs/config_Giang.yaml` | `Giang_hoc_tap` | `crawled_data/Giang` |
| Người 2 – Thi cử và học phí | `configs/config_Phuc.yaml` | `Phuc_thi_cu` | `crawled_data/Phuc` |
| Người 3 – Môi trường học đường | `configs/config_Dong.yaml` | `Dong_moi_truong` | `crawled_data/Dong` |
| Người 4 – Đời sống/tâm lý | `configs/config_Tam.yaml` | `Tam_doi_song` | `crawled_data/Tam` |

Các tab chưa tồn tại sẽ được chương trình tự tạo theo cùng cấu trúc nghiên cứu 19 cột, định dạng nền trắng chữ đen và đặt đúng hàng tiêu đề. Nhờ cùng cấu trúc, người điều phối có thể gộp bốn tab sau này mà không cần đổi tên cột.

## Chuẩn bị trên từng máy

1. Sao chép toàn bộ thư mục dự án sang máy của từng người.
2. Nhấp đúp `setup_windows.bat` và đợi thông báo cài đặt thành công. (Nếu bị mất mạng hoặc báo lỗi cài đặt dở dang, chỉ cần nhấp đúp file `reset.bat` để dọn dẹp rồi chạy lại `setup_windows.bat`).
3. Đặt file khóa Google Service Account vào thư mục `secrets`.
4. Tạo file `.env` từ `.env.example`.
5. Trong `.env`, đặt `ANONYMIZATION_SALT` bằng đúng mã chung do anh gửi trong Zalo. Cả bốn máy phải giống nhau tuyệt đối; không thêm khoảng trắng hoặc dấu ngoặc.
6. Sửa `GOOGLE_SERVICE_ACCOUNT_FILE` trong `.env` nếu tên file JSON trên máy khác với tên mẫu.

Không đưa `.env` hoặc file JSON trong `secrets` lên GitHub hay gửi cho người ngoài nhóm.

## Lệnh chạy của từng người

Mở PowerShell tại thư mục dự án và chỉ chạy đúng lệnh được phân công:

### Giang

```powershell
.\run_windows.bat configs\config_Giang.yaml
```

### Phúc

```powershell
.\run_windows.bat configs\config_Phuc.yaml
```

### Đông

```powershell
.\run_windows.bat configs\config_Dong.yaml
```

### Tâm

```powershell
.\run_windows.bat configs\config_Tam.yaml
```

Khi trình duyệt mở, đăng nhập Threads nếu cần, quay lại cửa sổ lệnh và nhấn **Enter**. Không chạy đồng thời hai config trên cùng một máy và không dùng `run_windows.bat` mà thiếu đường dẫn config.

## Thay đổi số lượng cần lấy

Mỗi file có dòng:

```yaml
target_per_topic: 5000
```

Đây là tổng số bài viết và bình luận của riêng ngách được giao. Có thể đổi thành số nhỏ như `10` để chạy thử. Không sao chép `output_dir`, `assigned_topics` hoặc `worksheet` từ file của người khác vì sẽ làm lẫn tiến độ và dữ liệu.

## Dừng và chạy tiếp

Bấm `Ctrl + C` trong cửa sổ lệnh để dừng. Lần sau chạy lại đúng lệnh cũ; chương trình đọc thư mục tiến độ riêng, bỏ qua dữ liệu đã có và tiếp tục phần còn thiếu.

Nếu Google Sheets tạm mất kết nối, dữ liệu vẫn được giữ trong thư mục `crawled_data/nguoi_X` và tự đồng bộ lại ở lần chạy sau.
