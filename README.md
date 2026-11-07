# TB4 VoiceNav: phần cảm nhận (giọng nói và nhận diện người)

Phần của đề tài robot giao đồ TurtleBot 4 do mình phụ trách: **hiểu lệnh nói tiếng Việt**
và **nhận diện người bằng camera OAK-D**. Package chỉ phát kết quả lên topic ROS 2; phần
điều hướng, dừng và cảnh báo do người làm thực thi đảm nhiệm. Định dạng message nằm trong
[INTERFACE.md](INTERFACE.md).

```
Micro → VAD → nhận dạng (Vosk | Whisper) → /speech_text → bộ hiểu lệnh → /voice_command
OAK-D RGB + depth → YOLOv8n (người) + khoảng cách + góc ──────────────────→ /person_detections
```

## Cấu trúc

```
voice_person_perception/            package ROS 2 (ament_python)
├── config/destinations.yaml        điểm đến và cách nói khác (thêm điểm không cần sửa code)
├── launch/perception.launch.py     chạy thật: micro + camera
├── launch/fake.launch.py           giả lập cho bên thực thi test khi chưa có robot
├── launch/record_bag.launch.py     thu đầu ra thành rosbag để gửi người khác
├── voice_person_perception/
│   ├── intent.py, vad.py, person_math.py, asr_backends.py   logic thuần, có test
│   ├── asr_node.py, intent_resolver_node.py, person_detector_node.py
│   └── fake_voice_node.py, fake_person_node.py
└── test/                           pytest, không cần ROS
```

## Cài đặt

Ubuntu 22.04, ROS 2 Humble.

```bash
cd ~/ros2_ws/src && git clone <repo này> && cd ..
pip install -r requirements.txt
sudo apt install portaudio19-dev            # cho sounddevice
colcon build --packages-select voice_person_perception
source install/setup.bash
```

Model nhận dạng giọng nói (chọn một):

- **Vosk (nhẹ, nhanh, hợp Raspberry Pi):** `bash scripts/download_vosk_model.sh` tải model tiếng
  Việt nhỏ `vosk-model-small-vn-0.4` về `models/` (đã chạy được offline trong bài trước: nạp 0,11 s,
  nhận dạng clip 2 s mất 1,39 s trên laptop).
- **Whisper (chính xác hơn với câu tự do, chậm hơn):** `faster-whisper` tự tải model lần đầu
  chạy; dùng `backend:=whisper`.

YOLOv8n (`yolov8n.pt`) được `ultralytics` tự tải lần đầu chạy.

## Chạy

```bash
# Chạy thật (cần micro, và camera OAK-D đang phát topic):
ros2 launch voice_person_perception perception.launch.py \
    backend:=vosk model_path:=$PWD/models/vosk-model-small-vn-0.4

# Giả lập (không cần micro/camera):
ros2 launch voice_person_perception fake.launch.py
```

Tham số hay chỉnh (`--ros-args -p tên:=giá trị`):

| Node | Tham số | Mặc định | Ý nghĩa |
|---|---|---|---|
| `asr_node` | `backend`, `model_path` | `vosk`, rỗng | Bộ nhận dạng và model |
| | `device_index` | `-1` | Chỉ số micro; xem `python3 -m sounddevice` |
| | `min_rms` | `250` | Ngưỡng tiếng tối thiểu; ngưỡng thật tự theo tiếng ồn nền |
| | `vosk_grammar` | `false` | Vosk chỉ nhận câu mẫu sinh từ `destinations.yaml` (xem dưới) |
| | `whisper_prompt` | `false` | Gợi ý tên điểm đến cho Whisper (`initial_prompt`) |
| `intent_resolver_node` | `confident` | `0.97` | Điểm khớp tối thiểu để không hỏi lại |
| | `accept` | `0.75` | Dưới mức này coi là `UNKNOWN` |
| `person_detector_node` | `image_topic`, `depth_topic`, `camera_info_topic` | `/oakd/rgb/preview/...` | Topic camera; **xác nhận bằng `ros2 topic list` trên robot** |
| | `hfov_deg` | `69` | Góc nhìn ngang dùng khi không có `camera_info` |
| | `infer_rate_hz`, `imgsz` | `5`, `320` | Giảm nếu CPU yếu |

### Thiên vị nhận dạng về danh sách lệnh

Cả hai đều lấy danh sách điểm đến từ `destinations.yaml` (`voice_person_perception/vocab.py`),
bật qua launch: `vosk_grammar:=true` hoặc `whisper_prompt:=true`.

- **Vosk grammar:** chỉ nhận khoảng 300 câu mẫu ("đi đến X", "mang đồ đến X", "giao đến X", "X",
  câu dừng/hủy) hoặc `[unk]`. Chính xác hơn nhiều với tập lệnh nhỏ, nhưng câu nói ngoài mẫu sẽ bị
  ép về câu mẫu gần nhất hoặc mất chữ. Rủi ro: tên chỗ không có trong danh sách ("nhà vệ sinh")
  có thể bị nghe thành một điểm đến có thật. Cột `wrong_auto` của `eval_voice` đo đúng lỗi này.
- **Whisper prompt:** giúp Whisper viết đúng tên điểm đến; câu nào lặp lại chính prompt bị bỏ.

Mặc định tắt cả hai, bật sau khi `eval_voice` cho thấy có lợi trên giọng thật.

**Thêm bí danh theo lỗi nhận dạng:** sau khi đo, xem cột `heard` trong file kết quả. Từ nào ASR hay
nghe nhầm cho một điểm đến (ví dụ "phòng khác" thay vì "phòng khách") thì thêm vào `aliases`.

## Đo độ chính xác giọng nói (`eval_voice`)

Chạy cùng khâu cắt câu, nhận dạng và hiểu lệnh như trên robot, không cần ROS đang chạy. Câu thử ở
`config/eval_phrases.yaml` (có câu dừng, hủy và điểm đến không tồn tại).

```bash
# 1) Ghi âm: mỗi câu nói 3 lần, lưu WAV để so sánh lại
ros2 run voice_person_perception eval_voice --backend vosk \
    --model-path models/vosk-model-small-vn-0.4 --reps 3 --record-dir eval_audio/hiep
# 2) Chạy lại CÙNG bản ghi với cấu hình khác
ros2 run voice_person_perception eval_voice --backend vosk \
    --model-path models/vosk-model-small-vn-0.4 --vosk-grammar --from-dir eval_audio/hiep
ros2 run voice_person_perception eval_voice --backend whisper --whisper-prompt --from-dir eval_audio/hiep
```

Mỗi lần in tỉ lệ đúng, số mẫu theo loại kết quả và thời gian nhận dạng (trung bình, p90), và ghi
`results_<cấu hình>.csv` cạnh bản ghi. Loại kết quả:

| Loại | Ý nghĩa |
|---|---|
| `correct_auto` | Đúng, robot đi luôn |
| `correct_confirm` | Đúng nhưng robot hỏi lại |
| `wrong_confirm` | Sai nhưng robot hỏi lại hoặc không làm gì (an toàn) |
| `missed` | Không nhận ra chữ nào |
| `wrong_auto` | Sai mà robot vẫn làm: lỗi nguy hiểm nhất, cần bằng 0 |

Thời gian đo chỉ là khâu nhận dạng sau khi nói xong; độ trễ đầy đủ còn cộng thêm `end_silence_ms`
(0,7 s chờ im lặng). Nên ghi âm nhiều người, ở chỗ có tiếng ồn giống lúc demo. Bản ghi `eval_audio/`
không commit.

## Thu dữ liệu bằng ros2 bag

Thu đầu ra của phần cảm nhận (đang chạy `perception.launch.py` ở terminal khác) để gửi cho
người làm thực thi test khi họ không có robot:

```bash
ros2 launch voice_person_perception record_bag.launch.py           # tên theo ngày giờ, nén zstd
ros2 launch voice_person_perception record_bag.launch.py name:=nguoi_chan_duong
```

Mặc định thu 3 topic nhỏ: `/speech_text`, `/voice_command`, `/person_detections`. Nhấn `Ctrl+C`
để dừng, bag nằm trong `bags/<tên>/`. Kiểm tra bằng `ros2 bag info bags/<tên>`.

Thu thêm ảnh RGB/depth để test lại bộ nhận diện người offline (rất nặng, vài MB mỗi giây,
chỉ thu đoạn ngắn): thêm `raw:=true`.

**Gửi cho người kia:** nén cả thư mục (`zip -r nguoi_chan_duong.zip bags/nguoi_chan_duong`) rồi
gửi qua Google Drive. Không commit bag lên GitHub.

**Người nhận phát lại:**

```bash
ros2 bag play bags/nguoi_chan_duong            # thêm --loop để lặp
```

Khi phát lại phải **tắt node thật** (`asr_node`, `person_detector_node`, `fake.launch.py`),
nếu không hai nguồn cùng publish một topic. Thu một bag cho từng tình huống cần test
(đi bình thường, người chắn đường, nói sai/không hiểu, mất camera) để người kia kiểm tra
từng trường hợp.

## Kiểm thử

```bash
cd voice_person_perception && python3 -m pytest test -q
```

Test phủ phần logic thuần: hiểu lệnh, tách đoạn nói, hình học góc/khoảng cách, định dạng
message. Các node ROS được kiểm tra bằng bản giả (stub) của `rclpy`/YOLO/micro khi phát triển.

## Chưa kiểm chứng (cần làm trên robot thật)

- Độ chính xác nhận dạng tiếng Việt của Vosk và Whisper trong môi trường ồn: cần tự đo
  (tỉ lệ nhận đúng điểm đến trên 30-50 câu).
- Tên topic camera (`/oakd/rgb/preview/...`) và đơn vị depth (mặc định mm) theo TB4 của nhóm.
- Tốc độ YOLO trên Raspberry Pi 4: nếu chậm, chạy node nhận diện trên laptop cùng
  `ROS_DOMAIN_ID`, hoặc bật phát hiện trên OAK-D (`yolo_spatial.yaml` của `depthai-ros`).
- `hfov_deg` mặc định 69° là giá trị ước lượng; dùng `camera_info` khi có.

## Tích hợp vào repo nhóm

```bash
git clone https://github.com/dhung68/tb4-hri-delivery && cd tb4-hri-delivery
git checkout -b voice-person-perception
cp -r /đường/dẫn/tb4_voicenav/voice_person_perception .
cp /đường/dẫn/tb4_voicenav/{INTERFACE.md,requirements.txt} .
git add . && git commit -m "Add voice and person perception package"
git push -u origin voice-person-perception
```

Nguồn ý tưởng và giấy phép: [docs/references.md](docs/references.md).
