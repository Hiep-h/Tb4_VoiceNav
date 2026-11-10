"""Window for demos: mic button, what was heard, what the robot understood,
people around the robot, and (with a map) destinations and robot position.

    ros2 run voice_person_perception voice_gui
    ros2 run voice_person_perception voice_gui --ros-args -p map_yaml:=$HOME/maps/lab.yaml \\
        -p destinations_file:=$DEST

Click the round button or press Space to talk (asr_node with push_to_talk:=true
listens for one sentence; without it the button mutes/unmutes the mic).
Q or Esc closes the window. The GUI only displays and sends /asr_listen; it
needs asr_node, intent_resolver_node and (optionally) person_detector_node.
"""

import json
import os
import threading
import time

import cv2
import rclpy
import yaml
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import Bool, String

from voice_person_perception import contract
from voice_person_perception import gui_render as gr
from voice_person_perception.intent_resolver_node import _default_destinations_file

WINDOW = 'TB4 - dieu khien bang giong noi'


def _parse(data):
    try:
        out = json.loads(data)
        return out if isinstance(out, dict) else {'text': str(out)}
    except (TypeError, ValueError):
        return {'text': data}  # plain-text /speech_text (fake_voice_node)


class VoiceGui(Node):

    def __init__(self):
        super().__init__('voice_gui')
        self.declare_parameter('map_yaml', 'none')
        self.declare_parameter('destinations_file', 'auto')
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('base_frame', 'base_link')
        self.declare_parameter('nav_status_topic', '/navigation/status')
        # right side: auto = map if map_yaml, else station plan when the robot pose
        # is known (TF), else people radar; or force map / plan / radar
        self.declare_parameter('right_panel', 'auto')
        get = lambda name: self.get_parameter(name).value  # noqa: E731
        path = get('destinations_file')
        self.dest_path = _default_destinations_file() if path in ('', 'auto') else path
        self.map_frame, self.base_frame = get('map_frame'), get('base_frame')

        self.lock = threading.Lock()
        self.status = None
        self.status_at = 0.0
        self.heard = None
        self.command = None
        self.target = None
        self.persons = None
        self.persons_at = 0.0
        self.nav = None
        self.nav_at = 0.0
        self.right_panel = get('right_panel')
        self.destinations, self.names, self._dest_mtime = [], {}, None
        self._reload_destinations()

        self.mapview = None
        if get('map_yaml') not in ('', 'none'):
            image, res, origin = gr.load_map(get('map_yaml'))
            self.mapview = gr.MapView(image, res, origin)
            self.get_logger().info(f"Bản đồ {get('map_yaml')}")
        try:  # robot pose map -> base_link (AMCL, SLAM or fake_nav2_server)
            from tf2_ros import Buffer, TransformListener
            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(self.tf_buffer, self)
        except ImportError:
            self.tf_buffer = None

        self.listen_pub = self.create_publisher(Bool, contract.ASR_LISTEN_TOPIC, 10)
        self.create_subscription(String, contract.ASR_STATUS_TOPIC, self._on_status, 10)
        self.create_subscription(String, contract.SPEECH_TEXT_TOPIC, self._on_speech, 10)
        self.create_subscription(String, contract.VOICE_INTENT_TOPIC, self._on_command, 10)
        self.create_subscription(String, contract.PERSON_TOPIC, self._on_persons, 10)
        self.create_subscription(String, get('nav_status_topic'), self._on_nav, 10)

    # ---- subscriptions (executor thread)

    def _on_status(self, msg):
        with self.lock:
            self.status, self.status_at = _parse(msg.data), time.monotonic()

    def _on_speech(self, msg):
        with self.lock:
            self.heard = _parse(msg.data)

    def _on_command(self, msg):
        cmd = _parse(msg.data)
        with self.lock:
            self.command = cmd
            if (cmd.get('intent') in contract.STATION_INTENTS
                    and cmd.get('destination_station')):
                self.target = cmd.get('destination_station')
            elif cmd.get('intent') == contract.INTENT_CANCEL:
                self.target = None

    def _on_nav(self, msg):
        with self.lock:
            self.nav, self.nav_at = _parse(msg.data), time.monotonic()

    def _on_persons(self, msg):
        with self.lock:
            self.persons, self.persons_at = _parse(msg.data), time.monotonic()

    # ---- helpers

    def _reload_destinations(self):
        try:
            mtime = os.path.getmtime(self.dest_path)
        except OSError:
            return
        if mtime == self._dest_mtime:
            return
        try:
            with open(self.dest_path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:  # file being written: try again next frame
            self.get_logger().warn(f'Đọc {self.dest_path} lỗi: {exc}')
            return
        self._dest_mtime = mtime
        self.destinations = data.get('destinations', [])
        self.names = {d['id']: d.get('name', d['id']) for d in self.destinations}

    def robot_pose(self):
        if self.tf_buffer is None:
            return None
        try:
            tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, Time())
        except Exception:
            return None
        from voice_person_perception.waypoints import yaw_from_quaternion
        t, q = tf.transform.translation, tf.transform.rotation
        return t.x, t.y, yaw_from_quaternion(q.x, q.y, q.z, q.w)

    def press(self):
        """Button / Space: start or stop listening depending on the current state."""
        with self.lock:
            status = self.status if time.monotonic() - self.status_at < 1.5 else None
        if status is None:
            self.get_logger().warn('Chưa thấy /asr_status: asr_node đã chạy chưa?')
            return
        state = status.get('state')
        start = state in (contract.ASR_IDLE, contract.ASR_MUTED)
        if status.get('push_to_talk') and state == contract.ASR_RECOGNIZING:
            return
        self.listen_pub.publish(Bool(data=start))

    def frame(self, t):
        self._reload_destinations()
        now = time.monotonic()
        with self.lock:
            view = {
                'status': self.status if now - self.status_at < 1.5 else None,
                'heard': self.heard, 'command': self.command, 'names': self.names,
                'persons': self.persons,
                'persons_age': now - self.persons_at if self.persons else None,
                'nav': self.nav,
                'nav_age': now - self.nav_at if self.nav else None,
            }
            target = self.target
            nav = self.nav
        if nav and nav.get('state') in ('MOVING', 'SUCCEEDED') and nav.get('station_id'):
            target = nav['station_id']  # where the robot is really going
        left = gr.render_voice_panel(view, t)
        persons = (view['persons'] or {}).get('persons', [])
        if view['persons_age'] is not None and view['persons_age'] > 1.5:
            persons = []
        robot = self.robot_pose()
        mode = self.right_panel
        if mode == 'auto':
            mode = 'map' if self.mapview else ('plan' if robot is not None else 'radar')
        mapview = self.mapview if mode == 'map' else None
        if mode == 'plan':
            mapview = gr.plan_view(self.destinations, robot)
        if mapview is not None:
            right = gr.render_map_panel(mapview, self.destinations, robot, persons, target)
        else:
            right = gr.render_radar_panel({'persons': persons}, self.destinations, target)
        return gr.to_bgr(gr.compose(left, right))


def main(args=None):
    rclpy.init(args=args)
    node = VoiceGui()
    spinner = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spinner.start()

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and gr.inside_button(x, y):
            node.press()

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, on_mouse)
    t0 = time.monotonic()
    try:
        while rclpy.ok():
            cv2.imshow(WINDOW, node.frame(time.monotonic() - t0))
            key = cv2.waitKey(66) & 0xFF
            if key in (ord('q'), 27):
                break
            if key == ord(' '):
                node.press()
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
