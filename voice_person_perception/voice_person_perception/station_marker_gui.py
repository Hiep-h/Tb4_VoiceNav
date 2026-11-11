"""Window to mark the delivery stations on the map (replaces typing in waypoint_marker).

    ros2 run voice_person_perception station_marker_gui --ros-args \\
        -p file:=$DEST -p map_name:=lab

Works while mapping (slam.launch.py) or on a saved map (localization.launch.py):
it shows the live /map, the robot (TF map -> base_link) and the stations.

- Click a station row (or press A-D) to select it.
- "Lưu vị trí robot" / Space: the robot's current pose becomes the station.
- "Chọn trên map" / P, then click on the map: the station goes there; drag
  while clicking to set the direction the robot should face.
- "Xóa vị trí" / Delete: remove the station's pose (the station stays).
- "Lưu map" / M: runs map_saver_cli to <maps_dir>/<map_name>(.yaml/.pgm).
- Q / Esc: quit. destinations.yaml is saved after every change.
"""

import math
import os
import subprocess
import threading
import time

import cv2
import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time

from voice_person_perception import gui_render as gr
from voice_person_perception import station_gui as sg
from voice_person_perception import waypoints as wp

WINDOW = 'TB4 - danh dau tram'


class StationMarkerGui(Node):

    def __init__(self):
        super().__init__('station_marker_gui')
        self.declare_parameter('file', '')
        self.declare_parameter('map_name', 'lab')
        self.declare_parameter('maps_dir', '~/maps')
        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('max_tf_age_s', 2.0)
        get = lambda name: self.get_parameter(name).value  # noqa: E731
        self.path = get('file')
        if not self.path:
            raise RuntimeError('Thiếu -p file:=<destinations.yaml trong thư mục src>')
        self.map_name = get('map_name')
        self.maps_dir = os.path.expanduser(get('maps_dir'))
        self.map_frame, self.base_frame = get('map_frame'), get('base_frame')
        self.max_age = float(get('max_tf_age_s'))

        self.data = wp.load(self.path)
        if self.map_name:
            self.data['map'] = self.map_name
        self.data['frame'] = self.map_frame
        ids = [d['id'] for d in self.data['destinations']]
        self.selected = next((d['id'] for d in self.data['destinations']
                              if 'pose' not in d), ids[0] if ids else None)
        self.pick_mode = False
        self.drag_start = None   # world point where the mouse went down (pick mode)
        self.drag_now = None
        self.message, self.message_colour = 'Chọn một trạm, lái robot tới đó rồi bấm Lưu.', gr.DARK
        self.saving_map = False

        self.lock = threading.Lock()
        self.grid = None         # latest OccupancyGrid
        self.grid_version = 0
        self._mapview = None
        self._mapview_version = -1

        from tf2_ros import Buffer, TransformListener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(OccupancyGrid, get('map_topic'), self._on_map, qos)
        self.get_logger().info(f'File trạm: {self.path}')

    # ---- ROS callbacks (executor thread)

    def _on_map(self, msg):
        with self.lock:
            self.grid = msg
            self.grid_version += 1

    # ---- state

    def robot_pose(self):
        """(x, y, yaw) or None, and the reason when None."""
        try:
            tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, Time())
        except Exception:
            return None, 'Chưa có vị trí robot: SLAM/AMCL đã chạy chưa? (localization cần ' \
                         '2D Pose Estimate)'
        age = (self.get_clock().now() - Time.from_msg(tf.header.stamp)).nanoseconds * 1e-9
        if age > self.max_age:
            return None, f'Vị trí robot cũ {age:.1f} s: SLAM/AMCL có đang chạy không?'
        t, q = tf.transform.translation, tf.transform.rotation
        return (t.x, t.y, wp.yaw_from_quaternion(q.x, q.y, q.z, q.w)), None

    def mapview(self):
        with self.lock:
            grid, version = self.grid, self.grid_version
        if grid is None:
            robot, _ = self.robot_pose()
            return gr.plan_view(self.data['destinations'], robot, max_w=sg.MAP_W,
                                max_h=sg.PANEL_H - 34)
        if version != self._mapview_version:
            info = grid.info
            img = sg.occupancy_to_image(grid.data, info.width, info.height)
            self._mapview = gr.MapView(img, info.resolution,
                                       (info.origin.position.x, info.origin.position.y),
                                       max_w=sg.MAP_W, max_h=sg.PANEL_H - 34)
            self._mapview_version = version
        return self._mapview

    def say(self, text, colour=gr.DARK):
        self.message, self.message_colour = text, colour
        self.get_logger().info(text)

    # ---- actions

    def select(self, station_id):
        if wp.find(self.data, station_id) is not None:
            self.selected = station_id
            self.pick_mode = False
            self.say(f'Đang chọn trạm {station_id}.')

    def set_pose(self, x, y, yaw, how):
        if not self.selected:
            return
        wp.upsert(self.data, self.selected, pose=wp.make_pose(x, y, yaw))
        try:
            wp.save(self.path, self.data)
        except OSError as exc:
            self.say(f'Không ghi được file: {exc}', gr.RED)
            return
        self.say(f'Đã lưu trạm {self.selected} ({how}): x={x:.2f} y={y:.2f} '
                 f'hướng {math.degrees(yaw):.0f}°', gr.GREEN)
        todo = wp.missing_pose(self.data)
        if todo:
            self.selected = todo[0]  # move on to the next unmarked station

    def save_robot_pose(self):
        robot, why = self.robot_pose()
        if robot is None:
            self.say(why, gr.RED)
            return
        self.set_pose(*robot, how='vị trí robot')

    def clear_pose(self):
        item = wp.find(self.data, self.selected) if self.selected else None
        if not item or 'pose' not in item:
            self.say('Trạm này chưa có vị trí.', gr.GREY)
            return
        del item['pose']
        wp.save(self.path, self.data)
        self.say(f'Đã xóa vị trí trạm {self.selected}.', gr.AMBER)

    def toggle_pick(self):
        self.pick_mode = not self.pick_mode
        self.drag_start = self.drag_now = None
        if self.pick_mode:
            self.say(f'Bấm vào map để đặt trạm {self.selected}; giữ chuột và kéo để chọn hướng.',
                     gr.AMBER)

    def save_map(self):
        if self.saving_map:
            return
        os.makedirs(self.maps_dir, exist_ok=True)
        target = os.path.join(self.maps_dir, self.map_name or 'map')
        self.saving_map = True
        self.say(f'Đang lưu map vào {target}.yaml ...', gr.BLUE)

        def run():
            cmd = ['ros2', 'run', 'nav2_map_server', 'map_saver_cli', '-f', target]
            try:
                done = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                ok = done.returncode == 0 and os.path.isfile(target + '.yaml')
                if ok:
                    self.say(f'Đã lưu map: {target}.yaml và .pgm. Lần sau chạy '
                             f'localization.launch.py map:={target}.yaml', gr.GREEN)
                else:
                    tail = (done.stderr or done.stdout).strip().splitlines()[-1:]
                    self.say('Lưu map lỗi: ' + (tail[0] if tail else f'mã {done.returncode}'),
                             gr.RED)
            except Exception as exc:  # noqa: BLE001
                self.say(f'Lưu map lỗi: {exc}', gr.RED)
            finally:
                self.saving_map = False
        threading.Thread(target=run, daemon=True).start()

    # ---- drawing and input (main thread)

    def frame(self):
        robot, _ = self.robot_pose()
        left, self.rects = sg.render_left({
            'stations': self.data['destinations'], 'selected': self.selected,
            'pick_mode': self.pick_mode, 'robot_ok': robot is not None,
            'message': self.message, 'message_colour': self.message_colour,
            'map_target': f"{self._short(self.maps_dir)}/{self.map_name or 'map'}",
            'saving_map': self.saving_map})
        self.view = self.mapview()
        preview = None
        if self.pick_mode and self.drag_start is not None:
            yaw = sg.drag_yaw(self.drag_start, self.drag_now or self.drag_start)
            preview = (*self.drag_start, yaw if yaw is not None else (robot[2] if robot else 0))
        note = (f'Bấm vào map để đặt trạm {self.selected}, kéo để chọn hướng'
                if self.pick_mode else None)
        right = sg.render_right(self.view, self.data['destinations'], robot, self.selected,
                                preview, note)
        return gr.to_bgr(sg.compose(left, right))

    @staticmethod
    def _short(path):
        home = os.path.expanduser('~')
        return '~' + path[len(home):] if path.startswith(home) else path

    def on_mouse(self, event, x, y):
        if x >= sg.PANEL_W:
            if not self.pick_mode or self.view is None:
                return
            world = self.view.to_world(x - sg.PANEL_W, y)
            if event == cv2.EVENT_LBUTTONDOWN:
                self.drag_start, self.drag_now = world, world
            elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
                self.drag_now = world
            elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
                yaw = sg.drag_yaw(self.drag_start, world)
                if yaw is None:
                    robot, _ = self.robot_pose()
                    yaw = robot[2] if robot else 0.0
                self.set_pose(self.drag_start[0], self.drag_start[1], yaw, how='chọn trên map')
                self.pick_mode = False
                self.drag_start = self.drag_now = None
            return
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        name = sg.hit(getattr(self, 'rects', {}), x, y)
        if name is None:
            return
        if name.startswith('station:'):
            self.select(name.split(':', 1)[1])
        elif name == 'save_pose':
            self.save_robot_pose()
        elif name == 'pick':
            self.toggle_pick()
        elif name == 'clear':
            self.clear_pose()
        elif name == 'save_map':
            self.save_map()

    def on_key(self, key):
        """key from cv2.waitKeyEx. Returns False to quit."""
        if key in (65535, 65288, 65439, 8, 127):  # Delete / Backspace (GTK and Qt codes)
            self.clear_pose()
            return True
        key &= 0xFF
        if key in (ord('q'), ord('Q'), 27):
            return False
        if key == ord(' '):
            self.save_robot_pose()
        elif key in (ord('p'), ord('P')):
            self.toggle_pick()
        elif key in (ord('m'), ord('M')):
            self.save_map()
        elif 0 < key < 128 and chr(key).upper() in [str(d['id']).upper()
                                                    for d in self.data['destinations']]:
            match = [d['id'] for d in self.data['destinations']
                     if str(d['id']).upper() == chr(key).upper()]
            self.select(match[0])
        return True


def main(args=None):
    rclpy.init(args=args)
    node = StationMarkerGui()
    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, lambda e, x, y, f, p: node.on_mouse(e, x, y))
    try:
        while rclpy.ok():
            cv2.imshow(WINDOW, node.frame())
            key = cv2.waitKeyEx(80)
            if key != -1 and not node.on_key(key):
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        missing = wp.missing_pose(node.data)
        if missing:
            print(f"Còn trạm chưa có vị trí: {', '.join(missing)}")
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()
        time.sleep(0.1)


if __name__ == '__main__':
    main()
