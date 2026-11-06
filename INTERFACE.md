# Hợp đồng giao tiếp: phần cảm nhận ↔ phần thực thi

Phần cảm nhận (giọng nói, nhận diện người) **chỉ phát thông tin**, không điều khiển robot.
Bên thực thi quyết định dừng, cảnh báo, đi hay hỏi lại. Mọi message là JSON trong
`std_msgs/msg/String`, có trường `"v": 1` (phiên bản). Muốn đổi định dạng thì sửa file này
trước, báo cả nhóm rồi mới sửa code.

`stamp` là thời gian ROS (giây, kiểu số thực), tức là chạy được cả khi dùng `use_sim_time`.

| Topic | Hướng | Tần suất | Ý nghĩa |
|---|---|---|---|
| `/voice_command` | cảm nhận → thực thi | theo sự kiện | Một lệnh nói đã hiểu |
| `/person_detections` | cảm nhận → thực thi | 10 Hz đều đặn | Những người đang thấy |
| `/asr_mute` | thực thi → cảm nhận | khi cần | `std_msgs/Bool`: `true` = tạm ngừng nghe |

## `/voice_command`

```json
{"v":1,"seq":7,"stamp":1730000000.12,"text":"mang đồ đến phòng khách",
 "intent":"GO_TO","destination":"phong_khach","confidence":0.95,
 "needs_confirm":false,"candidates":[{"destination":"phong_khach","score":1.0}]}
```

| Trường | Ý nghĩa |
|---|---|
| `seq` | Số thứ tự tăng dần, mỗi lệnh một số. Dùng để không xử lý một lệnh hai lần |
| `text` | Câu nhận dạng được (để hiển thị/ghi log) |
| `intent` | `GO_TO`, `STOP`, `CANCEL` hoặc `UNKNOWN` |
| `destination` | `id` điểm đến (trùng `id` trong `config/destinations.yaml` và waypoint của bên thực thi); `null` nếu không phải `GO_TO` |
| `confidence` | 0-1, đã nhân độ tin cậy của nhận dạng giọng nói |
| `needs_confirm` | `true` = chưa chắc, bên thực thi nên hỏi lại ("Bạn muốn đến phòng khách đúng không?") rồi mới đi |
| `candidates` | Tối đa 3 điểm đến gần nhất kèm điểm khớp, để hỏi lại hoặc ghi log |

Quy ước:
- **Mỗi lệnh chỉ phát một lần.** Lệnh trùng nhau trong 1,5 s bị bỏ. Đừng coi topic này là
  tín hiệu sống để làm watchdog, vì khi không ai nói thì nó im lặng.
- `STOP` và `CANCEL` luôn có `needs_confirm: false`; bên thực thi nên dừng ngay.
  Nút dừng khẩn cấp vật lý và watchdog vẫn phải có, không dựa vào giọng nói.
- `UNKNOWN` là câu không hiểu; bên thực thi có thể bỏ qua hoặc nói "mình chưa hiểu".

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

Quy ước:
- Phát **đều 10 Hz kể cả khi không có ai**, nên bên thực thi dùng nó làm watchdog được:
  không nhận tin trong ~1 s nghĩa là node nhận diện đã chết.
- Ngưỡng dừng/cảnh báo (ví dụ "người trong 1 m và |góc| < 30°") do **bên thực thi** chọn.
  Phần cảm nhận chỉ báo số đo.

## `/asr_mute`

Bên thực thi gửi `true` trong lúc robot phát tiếng bíp hoặc nói, `false` sau đó, để micro
không nghe lại chính robot.

## Test khi chưa có robot

```bash
ros2 launch voice_person_perception fake.launch.py   # câu nói mẫu + người đi tới/đi xa (vòng 20 s)
ros2 topic echo /voice_command
ros2 topic echo /person_detections
```

Gõ tay một câu (đi qua đúng bộ hiểu lệnh thật):

```bash
ros2 topic pub --once /speech_text std_msgs/msg/String "{data: 'mang đồ đến chỗ nấu ăn'}"
```
