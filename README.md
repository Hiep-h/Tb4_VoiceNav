# voice_person_perception: lệnh thoại tiếng Việt và nhận diện người

Module HRI của dự án robot giao hàng TurtleBot 4 (`tb4-hri-delivery`, thư mục
`src/voice_interaction/`), người phụ trách: Hiệp. Package làm hai việc và **chỉ phát thông tin**:

- **Hiểu lệnh nói tiếng Việt** → `/voice/intent` theo hợp đồng nhóm (`docs/interfaces.md` mục 2):
  6 lệnh `CREATE_DELIVERY`, `GET_STATUS`, `PAUSE`, `RESUME`, `CHANGE_DESTINATION`, `CANCEL`,
  trạm `A`–`D`. Mission Manager kiểm tra quyền rồi mới cho robot làm.
- **Nhận diện người bằng camera OAK-D** → `/person_detections` (khoảng cách, góc, đang tiến lại).
  Dừng hay cảnh báo do Mission Manager quyết định.

Định dạng message chi tiết: [INTERFACE.md](INTERFACE.md).

Muốn chạy từ đầu (vẽ map, đánh dấu điểm đến, cho robot đi): xem
[Từ vẽ map đến lúc robot đi](#từ-vẽ-map-đến-lúc-robot-đi-làm-theo-thứ-tự).

```
Micro → VAD → nhận dạng (Google, Whisper dự phòng | Vosk) → /speech_text → bộ hiểu lệnh → /voice/intent
OAK-D RGB + depth → YOLOv8n (người) + khoảng cách + góc ──────────────────→ /person_detections
```

## Cấu trúc

```
voice_person_perception/            package ROS 2 (ament_python)
├── config/destinations.yaml        trạm A-D, cách gọi khác và vị trí trên map (dùng chung)
├── config/eval_phrases.yaml        câu thử cho eval_voice
├── launch/perception.launch.py     chạy thật: micro + camera
├── launch/fake.launch.py           câu nói và người giả để Mission Manager test khi chưa có robot
├── launch/record_bag.launch.py     thu đầu ra thành rosbag để gửi người khác
├── voice_person_perception/
│   ├── intent.py, vad.py, person_math.py, asr_backends.py   logic thuần, có test
│   ├── vocab.py, waypoints.py, marker_specs.py              logic thuần, có test
│   ├── asr_node.py, intent_resolver_node.py, person_detector_node.py
│   ├── waypoint_marker.py          đánh dấu điểm đến trên map, ghi vào destinations.yaml
│   ├── destination_markers.py      vẽ các điểm đến lên RViz, tự cập nhật khi file đổi
│   ├── voice_gui.py, gui_render.py giao diện: nút nói, lệnh đã hiểu, bản đồ/radar người
│   ├── webcam_node.py, person_draw.py  thử nhận diện người bằng webcam, ảnh debug có khung
│   ├── camera_check.py             kiểm tra topic, depth, căn chỉnh của camera robot
│   ├── eval_voice.py               đo độ chính xác + độ trễ giọng nói
│   └── fake_voice_node.py, fake_person_node.py
└── test/                           pytest, không cần ROS
```

## Cài đặt

Ubuntu 22.04, ROS 2 Humble.

```bash
cd ~/ros2_ws/src && git clone https://github.com/dhung68/tb4-hri-delivery && cd ..
pip install -r src/tb4-hri-delivery/src/voice_interaction/voice_person_perception/requirements.txt
                                     # đã ghim numpy<2, opencv<4.12 cho ROS Humble
sudo apt install portaudio19-dev            # cho sounddevice
colcon build --packages-select voice_person_perception
source install/setup.bash
```

Nhận dạng giọng nói: mặc định **Google** (cần Internet), **Whisper** dự phòng.

- **Google** (`backend:=google`): dùng gói `SpeechRecognition`, gửi từng câu lên Google, tiếng Việt
  tốt nhất trong ba bộ. Google trả vài phương án; node chọn phương án đầu tiên có tên một điểm đến
  trong `destinations.yaml`, không có thì lấy phương án đầu.
- **Whisper dự phòng** (`fallback:=whisper`): chỉ chạy khi Google báo lỗi (mất mạng, hết hạn mức,
  quá 5 s), và chỉ cho câu đó. Google nghe không ra chữ thì KHÔNG chuyển, để tránh tốn thời gian.
  Model Whisper được tải và nạp ở nền (lần đầu khoảng 500 MB), Google dùng được ngay; log báo
  `whisper dự phòng đã sẵn sàng` khi xong. Nên tải trước một lần, có thanh tiến độ:
  `python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', compute_type='int8')"`.
  Chạy trên laptop.
  Có thể trỏ `whisper_model:=` tới một thư mục model CTranslate2, ví dụ PhoWhisper (Whisper huấn
  luyện thêm cho tiếng Việt).
- **Vosk** (`backend:=vosk`, offline, hợp Raspberry Pi): `bash scripts/download_vosk_model.sh` tải
  `vosk-model-small-vn-0.4` về `models/`. Nhận tiếng Việt kém hơn hai bộ trên.

YOLOv8n (`yolov8n.pt`) được `ultralytics` tự tải lần đầu chạy.

## Chạy

```bash
# Chạy thật (cần micro, Internet, và camera OAK-D đang phát topic):
ros2 launch voice_person_perception perception.launch.py           # Google, Whisper dự phòng
ros2 launch voice_person_perception perception.launch.py whisper_model:=medium
ros2 launch voice_person_perception perception.launch.py fallback:=none   # chỉ Google

# Giả lập (không cần micro/camera):
ros2 launch voice_person_perception fake.launch.py
```

### Giao diện (`voice_gui`)

![voice_gui](docs/voice_gui.png)

```bash
# Laptop, chưa có camera: giọng nói + giao diện, bấm nút để nói
ros2 launch voice_person_perception perception.launch.py person:=false gui:=true push_to_talk:=true
# Có bản đồ: vẽ thêm điểm đến, vị trí robot và người lên bản đồ
ros2 launch voice_person_perception perception.launch.py gui:=true push_to_talk:=true \
    map_yaml:=$HOME/maps/lab.yaml destinations_file:=$DEST
# Xem dữ liệu giả
ros2 launch voice_person_perception fake.launch.py gui:=true
```

- **Trái:** nút micro (xám: bấm để nói; đỏ: đang nghe; vàng: đang nhận dạng), mức âm lượng so với
  ngưỡng (vạch đen), câu vừa nghe, lệnh robot hiểu (xanh: đi luôn; vàng: cần xác nhận; đỏ: dừng),
  tóm tắt người phía trước, bộ nhận dạng đang dùng.
- **Phải:** có `map_yaml` thì là bản đồ với điểm đến (xanh lá: đang tới), robot và người (cần
  SLAM/AMCL để có vị trí robot); không có thì là radar người quanh robot (0,5 / 1 / 2 / 3 m).
- Bấm nút hoặc phím **Space** rồi nói một câu. Câu kết thúc khi im 1,5 s (`ptt_end_silence_ms`),
  hoặc **bấm lần nữa để gửi ngay**; bấm lại khi chưa nói gì là hủy. **Q** để đóng. Không có
  `push_to_talk:=true` thì micro nghe liên tục (câu kết thúc khi im 0,7 s, `end_silence_ms`) và
  nút dùng để tắt/bật micro.
- Nhận dạng sai nhiều: chạy thêm `save_audio_dir:=~/asr_debug` (tham số của `asr_node`). Mỗi câu
  được lưu thành WAV kèm chữ nhận được trong `log.tsv`. Nghe lại: nếu WAV rõ mà chữ sai là lỗi bộ
  nhận dạng; nếu WAV nhỏ, rè, bị cắt là lỗi micro. Câu nói nhỏ được tự khuếch đại (tối đa 8 lần,
  `normalize_audio`).
- Câu bị cắt sớm: tăng `ptt_end_silence_ms` (vd. 2000) hoặc giảm `release_ratio` (mặc định 0,6:
  giữa câu, âm to hơn 60% ngưỡng vẫn tính là đang nói). Câu dài tối đa `max_utterance_s` = 10 s.
- Giao diện chỉ hiển thị và gửi `/asr_listen`; vẫn cần `asr_node`, `intent_resolver_node`.

Tham số hay chỉnh (`--ros-args -p tên:=giá trị`):

| Node | Tham số | Mặc định | Ý nghĩa |
|---|---|---|---|
| `asr_node` | `backend` | `google` | `google`, `whisper` hoặc `vosk` |
| | `fallback` | `whisper` | Bộ dự phòng khi `backend` lỗi; `none` = không dùng |
| | `whisper_model` | `small` | Cỡ model hoặc thư mục model CTranslate2 (PhoWhisper) |
| | `model_path` | `none` | Thư mục model Vosk (khi dùng Vosk) |
| | `push_to_talk` | `false` | Chỉ nghe một câu sau mỗi lần bấm nút (`voice_gui`, `/asr_listen`) |
| | `ptt_end_silence_ms` | `1500` | Bấm-để-nói: im bao lâu thì coi là nói xong |
| | `release_ratio` | `0.6` | Giữa câu, âm trên ngưỡng × hệ số này vẫn tính là đang nói |
| | `tail_ms` | `600` | Giữ lại bấy nhiêu ms sau chữ to cuối cùng (chữ cuối nói nhỏ như "sạc") |
| | `max_utterance_s` | `10` | Câu dài nhất |
| | `normalize_audio` | `true` | Khuếch đại câu nói nhỏ trước khi nhận dạng |
| | `save_audio_dir` | `none` | Lưu từng câu ra WAV + `log.tsv` để nghe lại |
| | `device_index` | `-1` | Chỉ số micro; xem `python3 -m sounddevice` |
| | `min_rms` | `250` | Ngưỡng tiếng tối thiểu; ngưỡng thật tự theo tiếng ồn nền |
| | `vosk_grammar` | `false` | Vosk chỉ nhận câu mẫu sinh từ `destinations.yaml` (xem dưới) |
| | `whisper_prompt` | `false` | Gợi ý tên điểm đến cho Whisper (`initial_prompt`) |
| `intent_resolver_node` | `confident` | `0.97` | Điểm khớp tối thiểu để không hỏi lại |
| | `accept` | `0.75` | Dưới mức này coi là `UNKNOWN` |
| `person_detector_node` | `image_topic`, `depth_topic`, `camera_info_topic` | `/oakd/rgb/preview/image_raw`, `/oakd/stereo/image_raw`, `/oakd/rgb/preview/camera_info` | Topic camera; **lấy theo `camera_check` trên robot** |
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

## Thử nhận diện người bằng webcam laptop (chưa cần robot)

Dùng webcam thay OAK-D để thử YOLO, theo dõi người, hướng và "đang tiến lại" trước khi lên robot.

```bash
sudo apt install ros-humble-rqt-image-view     # nếu chưa có (xem ảnh có khung người)
ros2 launch voice_person_perception webcam_person.launch.py            # device:=1 nếu có 2 camera
ros2 topic echo /person_detections                                       # terminal khác
```

Mở ra 2 cửa sổ: ảnh webcam có khung người (`rqt_image_view`, topic `/person_detections/image`) và
`voice_gui` với radar người. Nhãn trên khung: `#3 1.2m~ L15 <-` = người số 3, cách ~1,2 m, lệch
trái 15°, đang tiến lại; khung xanh lá xa hơn 2 m, cam 1-2 m, đỏ dưới 1 m hoặc đang tiến lại.

Thử lần lượt:
1. Ngồi trước laptop, rồi nghiêng người lại gần/ra xa: `distance_m` giảm/tăng, tiến lại nhanh thì
   `approaching: true`.
2. Đứng xa 2-3 m (thấy cả người) và đi sang trái/phải: `bearing_deg` dương khi người ở **bên trái
   camera** (bên phải của người đang nhìn vào camera).
3. Hai người cùng lúc: mỗi người giữ một `id` riêng khi di chuyển.
4. Đi ra khỏi khung hình: danh sách `persons` rỗng nhưng tin vẫn ra đều 10 Hz.

**Giới hạn:** webcam không có ảnh độ sâu nên khoảng cách chỉ là **ước lượng** từ kích thước khung
(`source: height` khi thấy cả người, giả sử cao 1,7 m; `source: width` khi chỉ thấy nửa trên, giả
sử vai rộng 0,5 m), sai số có thể 30-50%. Số đo cho báo cáo phải lấy bằng OAK-D trên robot
(`source: depth`). Lần đầu chạy, `ultralytics` tự tải `yolov8n.pt` (~6 MB).

## Kiểm tra camera trên robot (`camera_check`)

Làm trước khi chạy nhận diện người với OAK-D thật. Bật robot, laptop cùng `ROS_DOMAIN_ID`, rồi:

```bash
ros2 run voice_person_perception camera_check
```

Công cụ tự tìm topic ảnh màu, ảnh độ sâu, `camera_info`, nghe 5 s rồi in encoding, kích thước, tần
số và các lỗi thường gặp:

| Báo | Nghĩa | Cách sửa |
|---|---|---|
| Không có ảnh độ sâu | Cấu hình OAK-D của TB4 chỉ phát ảnh màu | Bật `stereo: i_publish_topic: true`, `i_align_depth: true` trong file cấu hình camera rồi chạy lại camera |
| Ảnh màu và depth khác tỉ lệ | Thường do dùng ảnh `preview` (vuông) với depth 16:9 | Dùng `/oakd/rgb/image_raw` (công cụ tự chọn nếu có) |
| Quá chậm (< 4 Hz) | Ảnh chưa nén qua wifi | Chạy node nhận diện trên robot, hoặc giảm độ phân giải |
| Encoding không hỗ trợ | Depth không phải `16UC1`/`32FC1` | Xem cấu hình camera |

Sau đó công cụ in **lệnh chạy `person_detector_node` với đúng topic**, và in liên tục độ sâu ở giữa
ảnh: hướng camera vào tường hoặc một người, đo bằng thước, so hai số (lệch vài cm là ổn). Truyền
các topic đó vào launch:

```bash
ros2 launch voice_person_perception perception.launch.py image_topic:=/oakd/rgb/image_raw \
    depth_topic:=/oakd/stereo/image_raw camera_info_topic:=/oakd/rgb/camera_info
```

Kiểm tra cuối: chạy lệnh `person_detector_node` công cụ in ra (có `debug_image:=true`), mở
`ros2 run rqt_image_view rqt_image_view /person_detections/image`, cho người đứng ở 0,5 / 1 / 2 m.
Nhãn khoảng cách **không có dấu `~`** nghĩa là đang đo bằng depth (`source: depth`).

## Từ vẽ map đến lúc robot đi (làm theo thứ tự)

Laptop và robot cùng mạng, cùng `ROS_DOMAIN_ID`; mọi lệnh chạy trên laptop, mỗi lệnh một
terminal đã `source install/setup.bash`. Để gõ ngắn, đặt biến trỏ tới file điểm đến **trong
thư mục `src`** (công cụ ghi vào đây, không phải `install`):

```bash
export DEST=~/ros2_ws/src/tb4-hri-delivery/src/voice_interaction/voice_person_perception/config/destinations.yaml
# dùng repo cá nhân Tb4_VoiceNav thì: ~/ros2_ws/src/tb4_voicenav/voice_person_perception/config/destinations.yaml
```

### Bước 1. Vẽ map và đánh dấu điểm đến cùng lúc

```bash
ros2 launch turtlebot4_navigation slam.launch.py                     # T1: vẽ map
ros2 launch turtlebot4_viz view_robot.launch.py                      # T2: RViz
ros2 run voice_person_perception destination_markers --ros-args -p file:=$DEST   # T3
ros2 run teleop_twist_keyboard teleop_twist_keyboard                 # T4: lái robot
ros2 run voice_person_perception waypoint_marker --ros-args -p file:=$DEST -p map_name:=lab  # T5
```

1. Trong RViz: **Add → By topic → `/destination_markers`** để thấy các điểm (mũi tên xanh + tên).
2. Lái robot **hết một vòng** khu vực trước cho map ổn định (SLAM có thể nắn lại map khi quay
   về chỗ cũ, làm lệch các điểm đã ghi trước đó).
3. Lái tới từng chỗ cần giao đồ, **dừng hẳn**, quay mặt robot về hướng muốn đứng khi tới nơi,
   rồi gõ tên ở T5:

   ```
   > trạm B
     Vị trí: x=1.50 y=-0.25 hướng=90°
     id (không dấu) [B]:
     Thêm bí danh, cách nhau dấu phẩy (đang có: điểm B, vị trí B, trạm bê, ...): bếp, chỗ tủ lạnh
     -> đã cập nhật B
   ```

   Mũi tên mới hiện ngay trên RViz. Thêm tên chỗ thật của trạm làm bí danh (vd. `bếp` cho trạm
   B) để nói "mang đến bếp" cũng hiểu là trạm B.
4. Gõ `q` ở T5. Công cụ báo điểm nào còn thiếu vị trí.

### Bước 2. Lưu map (khi SLAM vẫn đang chạy)

```bash
mkdir -p ~/maps && ros2 run nav2_map_server map_saver_cli -f ~/maps/lab
```

Được `~/maps/lab.yaml` và `lab.pgm`. Các điểm vừa ghi dùng đúng hệ tọa độ của map này. Vẽ map
mới thì phải đánh dấu lại.

### Bước 3. Chạy trên map đã lưu và kiểm tra điểm

Tắt T1 (SLAM), rồi:

```bash
ros2 launch turtlebot4_navigation localization.launch.py map:=$HOME/maps/lab.yaml   # T1
ros2 launch turtlebot4_navigation nav2.launch.py                                     # T6
```

Trong RViz bấm **2D Pose Estimate** đặt vị trí ban đầu của robot. Các mũi tên phải nằm đúng chỗ
trên map. Điểm nào lệch: lái robot tới đúng chỗ, chạy lại `waypoint_marker` (T5), gõ đúng tên đó
và chọn ghi đè.

### Bước 4. Thử cho robot đi tới một điểm (chưa cần giọng nói)

```bash
ros2 run voice_person_perception nav_goal_cmd B --file $DEST       # in lệnh, bỏ `B` để in tất cả
```

Chép lệnh `ros2 action send_goal ...` nó in ra, chạy là robot tự đi tới trạm B bằng Nav2. Làm
lần lượt mọi điểm để chắc đường đi được trước khi ghép giọng nói.

### Bước 5. Ra lệnh bằng giọng nói

```bash
ros2 launch voice_person_perception perception.launch.py destinations_file:=$DEST   # T7
ros2 topic echo /voice/intent                                       # T8: xem lệnh đã hiểu
```

Nói "mang hàng từ trạm A đến trạm B" sẽ ra `"intent": "CREATE_DELIVERY", "source_station": "A",
"destination_station": "B"`. Mission Manager nhận `/voice/intent`, kiểm tra quyền rồi nhờ
Navigation Client tra `pose` của trạm trong cùng `destinations.yaml` và gửi `NavigateToPose` như
bước 4. Định dạng và 6 loại lệnh xem [INTERFACE.md](INTERFACE.md).

### Lệnh trong `waypoint_marker`

| Gõ | Tác dụng |
|---|---|
| tên (vd. `trạm B`, `B`) | Lưu vị trí robot cho trạm đó. Tên, mã hoặc bí danh đã có thì cập nhật trạm cũ (gõ `bếp` là sửa trạm có bí danh `bếp`); tên mới thì thêm điểm, `id` tự sinh không dấu (`phòng họp` thành `phong_hop`) |
| `p` | Lần lưu tới dùng điểm bấm bằng nút **Publish Point** trên RViz thay vì vị trí robot |
| `l` | Liệt kê các điểm |
| `d <id>` | Xóa một điểm |
| `q` | Thoát |

File được lưu sau mỗi lần thêm; lần lưu đầu giữ bản cũ ở `destinations.yaml.bak`. Công cụ từ
chối lưu nếu không có vị trí robot mới (quá 2 s), tức là SLAM/AMCL chưa chạy hoặc chưa đặt vị trí
ban đầu. Ghi file sẽ thay phần chú thích đầu file bằng chú thích chuẩn.

Luôn truyền `destinations_file:=$DEST` khi chạy `perception.launch.py` để node đọc đúng file vừa
ghi; nếu bỏ trống, node đọc bản trong `install`, phải `colcon build` lại mới thấy điểm mới.

## Đo độ chính xác giọng nói (`eval_voice`)

Chạy cùng khâu cắt câu, nhận dạng và hiểu lệnh như trên robot, không cần ROS đang chạy. Câu thử ở
`config/eval_phrases.yaml` (có câu dừng, hủy và điểm đến không tồn tại).

```bash
# 1) Ghi âm (đánh giá luôn bằng Google): mỗi câu nói 3 lần, lưu WAV để so sánh lại
ros2 run voice_person_perception eval_voice --backend google --reps 3 --record-dir eval_audio/hiep
# 2) Chạy lại CÙNG bản ghi với cấu hình khác
ros2 run voice_person_perception eval_voice --backend whisper --from-dir eval_audio/hiep
ros2 run voice_person_perception eval_voice --backend whisper --whisper-model medium \
    --from-dir eval_audio/hiep
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
người làm Mission Manager / Navigation test khi không có robot:

```bash
ros2 launch voice_person_perception record_bag.launch.py           # tên theo ngày giờ, nén zstd
ros2 launch voice_person_perception record_bag.launch.py name:=nguoi_chan_duong
```

Mặc định thu 3 topic nhỏ: `/speech_text`, `/voice/intent`, `/person_detections`. Nhấn `Ctrl+C`
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
cd voice_person_perception && python3 -m pytest -p no:anyio test -q   # -p no:anyio: tránh lỗi _pytest.scope với pytest của Ubuntu
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
- `waypoint_marker`, `destination_markers` mới chạy với bản giả của ROS/TF; chưa chạy với SLAM,
  AMCL và RViz thật. Các lệnh `turtlebot4_navigation` ở bước 1-3 theo tài liệu TB4 Humble, kiểm
  tra lại tên launch trên máy nhóm.

## Phát triển và cập nhật lên repo nhóm

Code được phát triển ở repo cá nhân `Hiep-h/Tb4_VoiceNav` rồi chép vào repo nhóm, nhánh
`feature/voice-intent` (PR #1, issue `HRI-01`), theo `docs/workflow.md` của nhóm:

```bash
SRC=~/ros2_ws/src/tb4_voicenav                         # repo cá nhân
cd ~/tb4-hri-delivery && git switch feature/voice-intent && git pull
DST=src/voice_interaction/voice_person_perception
rm -rf $DST && cp -r $SRC/voice_person_perception $DST
find $DST -name __pycache__ -prune -exec rm -rf {} +
mkdir -p $DST/docs && cp $SRC/docs/* $DST/docs/
cp $SRC/README.md $SRC/INTERFACE.md $SRC/requirements.txt $DST/ && cp -r $SRC/scripts $DST/
git add src/voice_interaction && git commit -m "feat: ..." && git push
```

Không clone cả hai repo vào cùng `ros2_ws/src`: colcon sẽ thấy hai package trùng tên.

Nguồn ý tưởng và giấy phép: [docs/references.md](docs/references.md).
