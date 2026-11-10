# navigation_client: mã trạm → Nav2

Module Navigation Client của dự án `tb4-hri-delivery` (thư mục `src/navigation_client/`), người
phụ trách: Hiệp. Làm đúng 3 thao tác ở `docs/interfaces.md` mục 5:

| Thao tác | Lệnh JSON trên `/navigation/command` | Kết quả |
|---|---|---|
| `navigate_to(station_id)` | `{"request_id":"req-1","action":"NAVIGATE_TO","station_id":"B"}` | `goal_id`, đã gửi goal hay chưa và lý do |
| `cancel_navigation()` | `{"request_id":"req-2","action":"CANCEL"}` | Đã gửi lệnh hủy, hoặc `NOT_MOVING` |
| `get_navigation_status()` | `{"request_id":"req-3","action":"GET_STATUS"}` | `IDLE`, `MOVING`, `SUCCEEDED`, `FAILED`, `CANCELED` |

Chỉ node này gửi goal cho Nav2 (`/navigate_to_pose`); Voice và Web không gọi Nav2 trực tiếp,
Mission Manager quyết định rồi mới gửi lệnh cho node này. Tọa độ trạm lấy từ cùng file
`destinations.yaml` của `voice_person_perception` (ghi bằng `waypoint_marker`).

> Kiểu message tạm là JSON trong `std_msgs/String` cho đến khi ARCH-01 chốt `msg/srv/action`.

## Giao tiếp

| Topic | Hướng | Khi nào |
|---|---|---|
| `/navigation/command` | Mission Manager → Navigation Client | Mỗi lệnh |
| `/navigation/response` | Navigation Client → Mission Manager | Đúng một tin cho mỗi lệnh, cùng `request_id` |
| `/navigation/status` | Navigation Client → mọi người | Mỗi khi đổi trạng thái và mỗi giây |

`/navigation/response`:

```json
{"request_id":"req-1","accepted":true,"goal_id":"nav-1","state":"MOVING","reason":null,"stamp":50.0}
```

`/navigation/status`:

```json
{"request_id":"req-1","goal_id":"nav-1","station_id":"B","state":"MOVING","reason":null,
 "distance_remaining_m":2.4,"eta_s":6.5,"recoveries":0,"stamp":50.0}
```

| `reason` | Khi nào |
|---|---|
| `UNKNOWN_STATION` | Mã trạm không có trong `destinations.yaml` (lệnh bị từ chối, trạng thái giữ nguyên) |
| `NO_POSE` | Trạm có trong file nhưng chưa đánh dấu vị trí trên map |
| `NAV2_UNAVAILABLE` | Nav2 chưa chạy (`FAILED`) |
| `GOAL_REJECTED` | Nav2 từ chối goal (`FAILED`) |
| `NAV2_ABORTED` | Nav2 bỏ cuộc giữa đường: bị chặn, không tìm được đường (`FAILED`) |
| `TIMEOUT` | Đi lâu hơn `goal_timeout_s`, đã tự hủy (`FAILED`) |
| `PREEMPTED` | (trong response) lệnh đi mới thay goal đang chạy, dùng cho đổi đích |
| `CANCEL_REQUESTED` / `NOT_MOVING` | Trả lời lệnh hủy |
| `BAD_REQUEST` | Lệnh không phải JSON hoặc thiếu trường (`detail` ghi rõ) |

Quy ước:
- Mỗi lúc chỉ một goal. `NAVIGATE_TO` khi đang đi = **đổi đích**: goal mới thay goal cũ (Nav2 tự
  preempt), kết quả muộn của goal cũ bị bỏ qua. Không cần hủy rồi mới gửi (hủy xong gửi ngay dễ bị
  Nav2 từ chối).
- Lệnh hủy trả `CANCEL_REQUESTED` ngay; trạng thái thành `CANCELED` khi Nav2 xác nhận.
- `destinations.yaml` được đọc lại tự động khi file thay đổi (đánh dấu lại trạm không cần khởi
  động lại node).

## Thử khi chưa có robot (Nav2 giả)

`fake_nav2_server` đóng vai `/navigate_to_pose`: robot "đi" thẳng tới goal với `speed` m/s, gửi
phản hồi khoảng cách còn lại, hủy được, bị goal mới thay như Nav2 thật, và phát TF
`map → base_link` để RViz/`voice_gui` thấy robot chạy.

```bash
sudo apt install ros-humble-nav2-msgs        # nếu chưa có (thường có sẵn cùng TurtleBot 4)
export DEST=<đường dẫn>/voice_person_perception/config/destinations.yaml
# Trạm cần có `pose`; chưa có map thì tạm ghi tay, vd: pose: {x: 2.0, y: 1.0, yaw: 0.0}
ros2 launch navigation_client navigation_client.launch.py stations_file:=$DEST sim:=true   # T1
ros2 run navigation_client nav_cmd watch                                                    # T2
ros2 run navigation_client nav_cmd go B          # T3: đi tới trạm B
ros2 run navigation_client nav_cmd go D          #     đổi đích giữa chừng
ros2 run navigation_client nav_cmd cancel        #     hủy
ros2 run navigation_client nav_cmd status
```

T2 in ra từng thay đổi: `MOVING, trạm B, còn 1.80 m, ~4 s` … `SUCCEEDED, trạm B`.
Thử lỗi: `go E` (UNKNOWN_STATION), trạm chưa có `pose` (NO_POSE), tắt T1 rồi chạy riêng
`ros2 run navigation_client navigation_client --ros-args -p stations_file:=$DEST`
(NAV2_UNAVAILABLE), hoặc `fake_nav2_server` với `-p fail_after_s:=3.0` (NAV2_ABORTED).

Xem robot giả chạy trên giao diện: `ros2 run voice_person_perception voice_gui --ros-args
-p map_yaml:=<map.yaml> -p destinations_file:=$DEST` (cần một map bất kỳ để vẽ).

## Chạy với robot thật

Cần map đã lưu, các trạm đã đánh dấu (`waypoint_marker`), Nav2 đang chạy và robot đã định vị
(xem README của `voice_person_perception`, mục "Từ vẽ map đến lúc robot đi", bước 1-3). Rồi:

```bash
ros2 launch navigation_client navigation_client.launch.py stations_file:=$DEST goal_timeout_s:=120
ros2 run navigation_client nav_cmd go B
```

## Tham số

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `stations_file` | `auto` | `destinations.yaml`; `auto` = bản cài cùng `voice_person_perception` |
| `action_name` | `/navigate_to_pose` | Action của Nav2 |
| `goal_timeout_s` | `0` | Quá thời gian thì hủy và báo `FAILED/TIMEOUT`; 0 = không giới hạn |
| `status_rate_hz` | `1.0` | Tần suất phát `/navigation/status` |
| `fake_nav2_server`: `speed`, `start_x`, `start_y`, `fail_after_s` | `0.4`, `0`, `0`, `0` | Robot giả |

## Kiểm thử

```bash
cd navigation_client && python3 -m pytest -p no:anyio test -q
```

Test phủ logic trạng thái (đi tới, hủy, hủy trước khi Nav2 nhận goal, đổi đích, kết quả muộn của
goal cũ, timeout, lỗi), đọc file trạm, robot giả và lệnh `nav_cmd`. Node ROS và Nav2 giả đã chạy
với bản giả (stub) của rclpy/Nav2; **chưa chạy với Nav2 thật trên robot**.
