# Nguồn tham khảo

Chỉ học ý tưởng, không sao chép mã. Repo không có giấy phép thì mặc định không được sao chép.

| Nguồn | Học được gì | Giấy phép |
|---|---|---|
| FrancescoPisacane/SLAM-and-Computer-Vision-for-Autonomous-Object-Search | Tách micro / nhận dạng / phân tích lệnh thành các node; chạy phần giọng nói trên laptop, điều hướng trên robot | Không có |
| vicoslab/dis_tutorial3 (`detect_people.py`) | YOLOv8n lớp `person` + tra khoảng cách từ ảnh depth khớp với ảnh preview của OAK-D | Không có |
| TDKCoder/robocar-perception | Vosk offline, lọc theo độ tin cậy từng từ, STOP luôn ưu tiên, xuất ý định dạng JSON | Không có |
| OppaAI/eric (`oakd.py`) | Làm mượt góc bằng trung bình trượt, nhận ra người đang đi xa; hạn chế bộ nhớ OAK-D Lite khi chạy NN | Apache-2.0 |
| Sjschhabra/voice-operated-mobile-manipulator-turtlebot-mycobot | Bài học tránh: model Whisper chỉ tiếng Anh, thu âm theo cửa sổ cố định, phát lặp lệnh | Chỉ dùng học thuật |

Điểm khác với các repo trên, do đọc mã của họ mà thấy:

- Tiếng Việt: cần model đa ngôn ngữ (`language="vi"`), và phải xử lý riêng chữ `đ` khi bỏ dấu.
- Tách đoạn nói bằng VAD thay vì cắt cửa sổ cố định, tránh mất từ.
- Mỗi lệnh chỉ phát một lần kèm `seq`, không phát lặp.
- Bỏ các câu Whisper hay "bịa" khi gặp im lặng hoặc tiếng ồn.
