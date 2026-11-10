# Giao tiếp của package `voice_person_perception`

Package **chỉ phát thông tin**, không điều khiển robot. Lệnh thoại đi theo hợp đồng chung của
nhóm (`docs/interfaces.md` của repo `tb4-hri-delivery`, mục 2): Mission Manager kiểm tra quyền
rồi quyết định; nhận diện người chỉ báo có ai, ở đâu; việc dừng/cảnh báo do Mission Manager
quyết. Mọi message là JSON trong `std_msgs/msg/String` (chờ ARCH-01 chốt kiểu message riêng).
Muốn đổi định dạng thì sửa file này trước, báo cả nhóm rồi mới sửa code.

`stamp` là thời gian ROS (giây, kiểu số thực), tức là chạy được cả khi dùng `use_sim_time`.

| Topic | Hướng | Tần suất | Ý nghĩa |
|---|---|---|---|
| `/voice/intent` | giọng nói → Mission Manager | theo sự kiện | Một lệnh nói đã hiểu (hợp đồng nhóm mục 2) |
| `/person_detections` | cảm nhận → thực thi | 10 Hz đều đặn | Những người đang thấy |
| `/asr_mute` | thực thi → cảm nhận | khi cần | `std_msgs/Bool`: `true` = tạm ngừng nghe |
| `/asr_status` | cảm nhận → (giao diện) | 10 Hz | Trạng thái micro; bên thực thi không bắt buộc dùng |
| `/asr_listen` | giao diện → cảm nhận | khi bấm nút | `std_msgs/Bool`: `true` = nghe một câu (bấm-để-nói) |

## `config/destinations.yaml` (trạm và vị trí trên map)

Một file dùng chung: phần giọng nói đọc `id`, `name`, `aliases`; Navigation Client đọc `pose`
để gửi `NavigateToPose`. `id` là mã trạm của nhóm (`A`, `B`, `C`, `D`).

```yaml
map: lab_tang3        # tên map lúc đánh dấu; đổi map thì phải đánh dấu lại
frame: map
destinations:
- id: B
  name: trạm B
  aliases: [điểm B, trạm bê, bếp, chỗ tủ lạnh]   # thêm tên chỗ thật của trạm
  pose: {x: 1.5, y: -0.25, yaw: 1.571}           # mét, mét, radian (hệ map)
```

- Ghi bằng `waypoint_marker` (README). Trạm nào chưa có `pose` thì Navigation Client báo
  "chưa biết đường đến X" thay vì đi.
- Thêm tên chỗ thật vào `aliases` ("bếp", "bàn thầy") để nói "mang đến bếp" cũng ra trạm đó.
- Đổi quaternion: `z = sin(yaw/2)`, `w = cos(yaw/2)`, `x = y = 0`.

## `/voice/intent`

Sáu trường đầu là **hợp đồng nhóm** (`docs/interfaces.md` mục 2); các trường sau là thông tin
thêm, Mission Manager có thể bỏ qua.

```json
{"request_id":"voice-103606-0001","intent":"CREATE_DELIVERY",
 "source_station":"A","destination_station":"B","confidence":0.93,"input_channel":"VOICE",
 "text":"mang hàng từ trạm A đến trạm B","needs_confirm":false,
 "candidates":[{"station":"A","score":1.0},{"station":"B","score":1.0}],"stamp":100.5}
```

| Trường | Ý nghĩa |
|---|---|
| `request_id` | `voice-<giờ khởi động>-<số thứ tự>`, mỗi lệnh một mã, để không xử lý một lệnh hai lần |
| `intent` | `CREATE_DELIVERY`, `GET_STATUS`, `PAUSE`, `RESUME`, `CHANGE_DESTINATION`, `CANCEL` (hợp đồng nhóm), hoặc `UNKNOWN` (xem dưới) |
| `source_station` | Trạm lấy hàng nếu người nói có nói ("**từ** trạm A", "lấy hàng **ở** A"); không nói thì `null` |
| `destination_station` | Trạm giao (`CREATE_DELIVERY`) hoặc trạm đích mới (`CHANGE_DESTINATION`); các lệnh khác `null` |
| `confidence` | 0-1: độ khớp tên trạm × độ tin cậy nhận dạng. **Không phải** độ tin cậy về người nói |
| `input_channel` | Luôn `VOICE` |
| `text` | Câu nhận dạng được (hiển thị, ghi log) |
| `needs_confirm` | `true` = chưa chắc (nghe gần đúng, thiếu trạm đích, nhận dạng kém): nên hỏi lại trước khi làm |
| `candidates` | Tối đa 3 trạm khớp nhất kèm điểm, để hỏi lại "trạm B hay trạm C?" |

Ví dụ câu nói → intent:

| Câu | intent | source | destination |
|---|---|---|---|
| "mang hàng từ trạm A đến trạm B" | `CREATE_DELIVERY` | A | B |
| "giao đến trạm C" / "mang đến C" | `CREATE_DELIVERY` | `null` | C |
| "lấy hàng ở trạm A" | `CREATE_DELIVERY` (`needs_confirm: true`) | A | `null` |
| "đổi sang trạm D" | `CHANGE_DESTINATION` | `null` | D |
| "dừng lại", "tạm dừng", "chờ đã" | `PAUSE` | | |
| "tiếp tục", "đi tiếp" | `RESUME` | | |
| "hủy đơn", "thôi không cần nữa" | `CANCEL` | | |
| "đơn hàng đến đâu rồi", "giao xong chưa" | `GET_STATUS` | | |
| "đi đến nhà vệ sinh" (không phải trạm) | `UNKNOWN` | | |

Quy ước:
- **Mỗi lệnh chỉ phát một lần.** Lệnh giống hệt trong 1,5 s bị bỏ. Không dùng topic này làm
  watchdog vì khi không ai nói thì nó im lặng.
- `PAUSE` không bao giờ cần xác nhận. Nút dừng khẩn cấp và watchdog vẫn phải có, không dựa vào
  giọng nói.
- Nhận lệnh thoại **không** cấp quyền: Mission Manager kiểm tra quyền như mọi yêu cầu khác.
- `UNKNOWN` **không có trong hợp đồng nhóm**: phát để giao diện/robot báo "chưa hiểu".
  Mission Manager bỏ qua hoặc trả `INVALID`; tắt bằng `publish_unknown:=false`.

## `/person_detections`

```json
{"v":1,"stamp":1730000000.2,"healthy":true,"frame_age_s":0.04,
 "persons":[{"id":3,"distance_m":1.2,"bearing_deg":14.5,"confidence":0.88,"approaching":true}]}
```

| Trường | Ý nghĩa |
|---|---|
| `healthy` | `false` = camera không có hình gần đây (chết, rút cáp...). Khi đó `persons` rỗng nhưng **không có nghĩa là không có người**; bên thực thi nên coi là không biết |
| `frame_age_s` | Số giây từ khung hình cuối; `null` nếu chưa nhận khung nào |
| `persons` | Sắp xếp người gần nhất trước |
| `id` | Mã theo dõi (ổn định qua các khung hình); `null` nếu không theo dõi |
| `distance_m` | Khoảng cách tới người (m); `null` nếu chưa có độ sâu hợp lệ |
| `bearing_deg` | **Dương = người ở bên TRÁI robot**, âm = bên phải (cùng chiều quay yaw của ROS); 0 = chính giữa |
| `approaching` | `true` nếu người đang lại gần (> 0,2 m/s) |
| `source` | (tùy chọn) cách đo khoảng cách: `depth` (OAK-D), `height`/`width` (ước lượng từ khung, chỉ khi thử bằng webcam) |

Quy ước:
- Phát **đều 10 Hz kể cả khi không có ai**, nên bên thực thi dùng nó làm watchdog được:
  không nhận tin trong ~1 s nghĩa là node nhận diện đã chết.
- Ngưỡng dừng/cảnh báo (ví dụ "người trong 1 m và |góc| < 30°") do **bên thực thi** chọn.
  Phần cảm nhận chỉ báo số đo.

## `/asr_mute`

Bên thực thi gửi `true` trong lúc robot phát tiếng bíp hoặc nói, `false` sau đó, để micro
không nghe lại chính robot.

## `/asr_status` và `/asr_listen` (giao diện `voice_gui`)

`/asr_status` (`std_msgs/String`, JSON), ví dụ:

```json
{"v":1,"stamp":12.3,"state":"listening","level":180.5,"threshold":250.0,
 "backend":"google","fallback":"whisper","backup_ready":true,"push_to_talk":true}
```

`state`: `idle` (bấm-để-nói, chờ nút), `calibrating` (đo tiếng ồn), `listening` (chờ người nói),
`speech` (đang có người nói), `recognizing` (đang nhận dạng), `muted` (bị `/asr_mute` tắt).
Bên thực thi có thể dùng `speech`/`recognizing` để biết người dùng đang ra lệnh.

`/asr_listen`: `true` = nghe một câu rồi tự dừng (khi `asr_node` chạy `push_to_talk:=true`), tự hủy
nếu 8 s không ai nói; `false` = gửi ngay câu đang nói, hoặc hủy nếu chưa nói gì. Không có `push_to_talk` thì `true`/`false` là bật/tắt micro.
`/asr_mute` của bên thực thi vẫn ưu tiên hơn.

## Phát lại từ rosbag

Bên thực thi có thể test bằng bag do bên cảm nhận gửi (`ros2 bag play <bag>`). Khi đó
`stamp` là **thời điểm lúc thu**, không phải giờ hiện tại, nên bên thực thi:
- tính watchdog theo **thời điểm nhận tin** (giờ máy của mình), không so `stamp` với đồng hồ;
- dùng `request_id` để nhận biết lệnh mới; bag phát lặp (`--loop`) sẽ có `request_id` lặp lại.

## Test khi chưa có robot

```bash
ros2 launch voice_person_perception fake.launch.py   # câu nói mẫu + người đi tới/đi xa (vòng 20 s)
ros2 topic echo /voice/intent
ros2 topic echo /person_detections
```

Gõ tay một câu (đi qua đúng bộ hiểu lệnh thật):

```bash
ros2 topic pub --once /speech_text std_msgs/msg/String "{data: 'mang hàng từ trạm A đến trạm B'}"
```
