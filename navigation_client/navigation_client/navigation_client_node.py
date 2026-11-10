"""Navigation Client: station id -> Nav2 /navigate_to_pose (docs/interfaces.md section 5).

    ros2 run navigation_client navigation_client --ros-args -p stations_file:=$DEST

Mission Manager sends JSON commands on /navigation/command and gets one reply
per command on /navigation/response; /navigation/status is published on every
change and once a second (see protocol.py). Voice and Web never call Nav2
directly: only this node does.
"""

import os

import rclpy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String

from navigation_client import core, protocol
from navigation_client.stations import default_stations_file, load_stations


class Nav2Backend(core.NavBackend):
    """Talks to the NavigateToPose action server and reports back to the core."""

    def __init__(self, node, action_name):
        self.node = node
        self.client = ActionClient(node, NavigateToPose, action_name)
        self.core = None
        self.handles = {}
        self.cancel_when_accepted = set()

    def available(self):
        return self.client.server_is_ready()

    def send(self, goal_id, pose, frame):
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = frame
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = pose.x
        goal.pose.pose.position.y = pose.y
        qx, qy, qz, qw = pose.quaternion()
        goal.pose.pose.orientation.x, goal.pose.pose.orientation.y = qx, qy
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = qz, qw
        future = self.client.send_goal_async(
            goal, feedback_callback=lambda msg: self._feedback(goal_id, msg))
        future.add_done_callback(lambda f: self._accepted(goal_id, f))

    def cancel(self, goal_id):
        handle = self.handles.get(goal_id)
        if handle is None:
            self.cancel_when_accepted.add(goal_id)  # goal still on its way to Nav2
        else:
            handle.cancel_goal_async()

    def _accepted(self, goal_id, future):
        try:
            handle = future.result()
        except Exception as exc:  # noqa: BLE001
            self.node.get_logger().error(f'Gửi goal lỗi: {exc}')
            self.core.on_accepted(goal_id, False)
            return
        if not handle.accepted:
            self.core.on_accepted(goal_id, False)
            return
        self.handles[goal_id] = handle
        self.core.on_accepted(goal_id, True)
        handle.get_result_async().add_done_callback(lambda f: self._result(goal_id, f))
        if goal_id in self.cancel_when_accepted:
            self.cancel_when_accepted.discard(goal_id)
            handle.cancel_goal_async()

    def _feedback(self, goal_id, msg):
        fb = msg.feedback
        eta = fb.estimated_time_remaining
        self.core.on_feedback(goal_id, fb.distance_remaining,
                              eta.sec + eta.nanosec * 1e-9, fb.number_of_recoveries)

    def _result(self, goal_id, future):
        self.handles.pop(goal_id, None)
        try:
            status = future.result().status
        except Exception as exc:  # noqa: BLE001
            self.node.get_logger().error(f'Lấy kết quả goal lỗi: {exc}')
            self.core.on_result(goal_id, core.FAILED, core.NAV2_ABORTED)
            return
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.core.on_result(goal_id, core.SUCCEEDED)
        elif status == GoalStatus.STATUS_CANCELED:
            self.core.on_result(goal_id, core.CANCELED)
        else:
            self.core.on_result(goal_id, core.FAILED, core.NAV2_ABORTED)


class NavigationClientNode(Node):

    def __init__(self):
        super().__init__('navigation_client')
        self.declare_parameter('stations_file', 'auto')
        self.declare_parameter('action_name', '/navigate_to_pose')
        self.declare_parameter('goal_timeout_s', 0.0)   # 0 = no limit
        self.declare_parameter('status_rate_hz', 1.0)
        get = lambda name: self.get_parameter(name).value  # noqa: E731

        path = get('stations_file')
        if path in ('', 'auto'):
            path = default_stations_file()
        if not path or not os.path.isfile(path):
            raise RuntimeError('Không tìm thấy file trạm: -p stations_file:=<destinations.yaml>')
        self.path = path
        self._mtime = os.path.getmtime(path)
        stations = load_stations(path)

        self.backend = Nav2Backend(self, get('action_name'))
        clock = lambda: self.get_clock().now().nanoseconds * 1e-9  # noqa: E731
        self.core = core.NavigationCore(stations, self.backend, clock,
                                        goal_timeout_s=float(get('goal_timeout_s')),
                                        on_change=self._publish_status)
        self.backend.core = self.core

        self.status_pub = self.create_publisher(String, protocol.STATUS_TOPIC, 10)
        self.response_pub = self.create_publisher(String, protocol.RESPONSE_TOPIC, 10)
        self.create_subscription(String, protocol.COMMAND_TOPIC, self._on_command, 10)
        self.create_timer(1.0 / float(get('status_rate_hz')), self._tick)

        marked = [s for s, p in stations.poses.items() if p is not None]
        missing = [s for s, p in stations.poses.items() if p is None]
        self.get_logger().info(
            f"Trạm có vị trí: {', '.join(marked) or 'chưa có'}"
            + (f"; chưa đánh dấu: {', '.join(missing)}" if missing else '')
            + f' (file {path})')
        if not self.client_ready(timeout=2.0):
            self.get_logger().warn(f"Chưa thấy Nav2 ({get('action_name')}); "
                                   'lệnh đi sẽ báo NAV2_UNAVAILABLE cho đến khi Nav2 chạy')

    def client_ready(self, timeout):
        return self.backend.client.wait_for_server(timeout_sec=timeout)

    def _on_command(self, msg):
        cmd, error = protocol.parse_command(msg.data)
        request_id = None
        if cmd is None:
            reply = protocol.bad_request(None, error, self.core.state)
        else:
            request_id = cmd.get('request_id')
            if cmd['action'] == protocol.NAVIGATE_TO:
                self._reload_if_changed()
                reply = self.core.navigate_to(cmd['station_id'], request_id)
            elif cmd['action'] == protocol.CANCEL:
                reply = self.core.cancel_navigation(request_id)
            else:
                reply = dict(self.core.get_navigation_status(), request_id=request_id,
                             accepted=True)
        self._publish(self.response_pub, reply)
        self.get_logger().info(f'{msg.data} -> {reply}')

    def _reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self.path)
            if mtime != self._mtime:
                self.core.set_stations(load_stations(self.path))
                self._mtime = mtime
                self.get_logger().info('Đã đọc lại file trạm')
        except Exception as exc:  # noqa: BLE001 - keep the old stations
            self.get_logger().warn(f'Đọc lại file trạm lỗi, dùng bản cũ: {exc}')

    def _tick(self):
        self.core.tick()
        self._publish_status(self.core.get_navigation_status())

    def _publish_status(self, status):
        self._publish(self.status_pub, status)

    def _publish(self, pub, payload):
        now = self.get_clock().now().nanoseconds * 1e-9
        pub.publish(String(data=protocol.dumps(protocol.with_stamp(payload, now))))


def main(args=None):
    rclpy.init(args=args)
    node = NavigationClientNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
