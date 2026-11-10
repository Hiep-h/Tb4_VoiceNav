"""Mark destinations on a saved map and write them into destinations.yaml.

Run while the robot is localised on the map (Nav2 localization + AMCL):

    ros2 run voice_person_perception waypoint_marker --ros-args \\
        -p file:=$PWD/src/<repo>/voice_person_perception/config/destinations.yaml \\
        -p map_name:=lab_tang3

Drive the robot to a place, type its name, press Enter. The robot's pose
(map -> base_link) is saved under that destination. Type `p` first to use the
last point clicked with RViz "Publish Point" instead of the robot pose.
"""

import math
import threading

import rclpy
from geometry_msgs.msg import PointStamped
from rclpy.node import Node
from rclpy.time import Time

from voice_person_perception import waypoints as wp

HELP = """\
Gõ tên điểm đến (vd: bếp) rồi Enter để lưu vị trí robot hiện tại.
Lệnh: l = liệt kê | p = dùng điểm bấm trên RViz (Publish Point) cho lần lưu tới
      d <id> = xóa | h = trợ giúp | q = thoát (file được lưu sau mỗi lần thêm)"""


class WaypointMarker(Node):

    def __init__(self):
        super().__init__('waypoint_marker')
        self.declare_parameter('file', '')
        self.declare_parameter('map_name', '')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('max_tf_age_s', 2.0)
        get = lambda name: self.get_parameter(name).value  # noqa: E731
        self.path = get('file')
        if not self.path:
            raise RuntimeError(
                'Thiếu tham số file: -p file:=<đường dẫn tới config/destinations.yaml '
                'trong thư mục src (không phải install)>')
        self.map_frame, self.base_frame = get('map_frame'), get('base_frame')
        self.max_age = float(get('max_tf_age_s'))
        self.data = wp.load(self.path)
        if get('map_name'):
            self.data['map'] = get('map_name')
        self.data['frame'] = self.map_frame

        from tf2_ros import Buffer, TransformListener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.clicked = None
        self.create_subscription(PointStamped, '/clicked_point', self._on_click, 10)

    def _on_click(self, msg):
        if msg.header.frame_id and msg.header.frame_id != self.map_frame:
            self.get_logger().warn(f'Điểm bấm ở frame {msg.header.frame_id}, cần {self.map_frame}')
            return
        self.clicked = (msg.point.x, msg.point.y)
        print(f'\n  [RViz] điểm bấm x={msg.point.x:.2f} y={msg.point.y:.2f}', flush=True)

    def robot_pose(self):
        """(x, y, yaw) of base_frame in map_frame, or raise with a readable reason."""
        tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, Time())
        age = (self.get_clock().now() - Time.from_msg(tf.header.stamp)).nanoseconds * 1e-9
        if age > self.max_age:
            raise RuntimeError(f'TF {self.map_frame}->{self.base_frame} cũ {age:.1f}s '
                               '(AMCL đã chạy và đặt initial pose chưa?)')
        t, q = tf.transform.translation, tf.transform.rotation
        return t.x, t.y, wp.yaw_from_quaternion(q.x, q.y, q.z, q.w)

    # ---- terminal loop (runs in a thread while rclpy spins) ----

    def _resolve_id(self, name):
        key = name.strip().lower()
        for item in self.data['destinations']:
            names = [item.get('name', '').lower()] + [a.lower() for a in item.get('aliases', [])]
            if key == str(item['id']).lower() or key in names:
                return item['id']
        return wp.slugify(name)

    def _existing_id(self, answer):
        """Keep an existing id as written ("A", not "a"); slugify new ones."""
        for item in self.data['destinations']:
            if answer.strip().lower() == str(item['id']).lower():
                return item['id']
        return wp.slugify(answer)

    def _list(self):
        if not self.data['destinations']:
            print('  (chưa có điểm nào)')
        for item in self.data['destinations']:
            pose = item.get('pose')
            where = (f"x={pose['x']:.2f} y={pose['y']:.2f} yaw={math.degrees(pose['yaw']):.0f}°"
                     if pose else 'CHƯA CÓ VỊ TRÍ')
            print(f"  {item['id']:14s} {item.get('name', ''):16s} {where}  "
                  f"[{', '.join(item.get('aliases', []))}]")

    def _ask(self, prompt, default=''):
        answer = input(f'  {prompt}' + (f' [{default}]' if default else '') + ': ').strip()
        return answer or default

    def _mark(self, name, use_click):
        if use_click:
            if self.clicked is None:
                print('  Chưa có điểm bấm. Dùng nút "Publish Point" trên RViz rồi thử lại.')
                return
            x, y = self.clicked
            try:
                yaw = self.robot_pose()[2]  # face the way the robot faces now
            except Exception:
                yaw = 0.0
        else:
            try:
                x, y, yaw = self.robot_pose()
            except Exception as exc:
                print(f'  Không lấy được vị trí robot: {exc}')
                return
        print(f'  Vị trí: x={x:.2f} y={y:.2f} hướng={math.degrees(yaw):.0f}°')
        dest_id = self._existing_id(self._ask('id (không dấu)', self._resolve_id(name)))
        if not dest_id:
            print('  id rỗng, bỏ qua.')
            return
        old = wp.find(self.data, dest_id)
        if old and 'pose' in old and self._ask('Đã có vị trí, ghi đè? (c/k)', 'c') != 'c':
            return
        current = ', '.join(old.get('aliases', [])) if old else ''
        extra = wp.parse_aliases(self._ask(
            f'Thêm bí danh, cách nhau dấu phẩy (đang có: {current or "không"})'))
        status = wp.upsert(self.data, dest_id, name=None if old else name, aliases=extra,
                           pose=wp.make_pose(x, y, yaw))
        wp.save(self.path, self.data)
        print(f"  -> {'đã thêm' if status == 'added' else 'đã cập nhật'} {dest_id}, "
              f'lưu vào {self.path}')

    def run_terminal(self):
        print(HELP)
        print(f'File: {self.path}')
        self._list()
        use_click = False
        while rclpy.ok():
            try:
                line = input('\n> ' + ('(điểm bấm) ' if use_click else '')).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            cmd = line.lower()
            if cmd == 'q':
                break
            if cmd == 'h':
                print(HELP)
            elif cmd == 'l':
                self._list()
            elif cmd == 'p':
                use_click = not use_click
                print('  Lần lưu tới dùng điểm bấm trên RViz.' if use_click
                      else '  Dùng lại vị trí robot.')
            elif cmd.startswith('d '):
                dest_id = line[2:].strip()
                if wp.remove(self.data, dest_id):
                    wp.save(self.path, self.data)
                    print(f'  Đã xóa {dest_id}')
                else:
                    print(f'  Không có {dest_id}')
            else:
                self._mark(line, use_click)
                use_click = False
        todo = wp.missing_pose(self.data)
        if todo:
            print(f"Cảnh báo: chưa có vị trí cho {', '.join(todo)}")
        print('Thoát.')


def main(args=None):
    rclpy.init(args=args)
    node = WaypointMarker()
    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()
    try:
        node.run_terminal()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
