"""A stand-in for Nav2's /navigate_to_pose, to test without a robot or a map.

    ros2 run navigation_client fake_nav2_server
    ros2 run navigation_client fake_nav2_server --ros-args -p speed:=1.0 -p fail_after_s:=10.0

The "robot" drives in a straight line to the goal at `speed` m/s, sends
feedback (distance, time left), can be cancelled, and is preempted by a newer
goal like the real bt_navigator. It publishes TF map -> base_link so RViz,
voice_gui and waypoint_marker see it move. fail_after_s > 0 aborts goals that
take longer, to test the FAILED path.
"""

import math
import threading
import time

import rclpy
from geometry_msgs.msg import TransformStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from navigation_client.sim import SimRobot


class FakeNav2Server(Node):

    def __init__(self):
        super().__init__('fake_nav2_server')
        self.declare_parameter('action_name', 'navigate_to_pose')
        self.declare_parameter('speed', 0.4)
        self.declare_parameter('start_x', 0.0)
        self.declare_parameter('start_y', 0.0)
        self.declare_parameter('start_yaw', 0.0)
        self.declare_parameter('fail_after_s', 0.0)
        self.declare_parameter('publish_tf', True)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('base_frame', 'base_link')
        get = lambda name: self.get_parameter(name).value  # noqa: E731

        self.robot = SimRobot(float(get('start_x')), float(get('start_y')),
                              float(get('start_yaw')), float(get('speed')))
        self.fail_after = float(get('fail_after_s'))
        self.map_frame, self.base_frame = get('map_frame'), get('base_frame')
        self.lock = threading.Lock()
        self.active = None  # uuid bytes of the goal being executed

        group = ReentrantCallbackGroup()
        self.server = ActionServer(
            self, NavigateToPose, get('action_name'), execute_callback=self._execute,
            goal_callback=lambda goal: GoalResponse.ACCEPT,
            cancel_callback=lambda handle: CancelResponse.ACCEPT,
            callback_group=group)
        self.tf = None
        if get('publish_tf'):
            from tf2_ros import TransformBroadcaster
            self.tf = TransformBroadcaster(self)
            self.create_timer(0.1, self._publish_tf, callback_group=group)
        self.get_logger().info(
            f"Nav2 giả sẵn sàng: /{get('action_name').lstrip('/')}, tốc độ {get('speed')} m/s, "
            f'robot ở ({self.robot.x:.1f}, {self.robot.y:.1f})')

    def _execute(self, handle):
        goal = handle.request.pose.pose
        gx, gy = goal.position.x, goal.position.y
        gyaw = 2.0 * math.atan2(goal.orientation.z, goal.orientation.w)
        my_id = bytes(handle.goal_id.uuid)
        with self.lock:
            self.active = my_id  # a newer goal preempts this one
        self.get_logger().info(
            f'Goal mới: ({gx:.2f}, {gy:.2f}), cách {self.robot.distance_to(gx, gy):.2f} m')
        started = time.monotonic()
        dt = 0.1
        while rclpy.ok():
            with self.lock:
                preempted = self.active != my_id
            if preempted:
                self.get_logger().info('Goal cũ bị thay bằng goal mới')
                handle.abort()
                return NavigateToPose.Result()
            if handle.is_cancel_requested:
                handle.canceled()
                self._clear(my_id)
                self.get_logger().info('Đã hủy goal')
                return NavigateToPose.Result()
            if self.fail_after > 0 and time.monotonic() - started > self.fail_after:
                handle.abort()
                self._clear(my_id)
                self.get_logger().warn(f'Giả lập lỗi: quá {self.fail_after:.0f} s')
                return NavigateToPose.Result()
            with self.lock:
                arrived = self.robot.step(gx, gy, gyaw, dt)
            fb = NavigateToPose.Feedback()
            fb.current_pose.header.frame_id = self.map_frame
            fb.current_pose.header.stamp = self.get_clock().now().to_msg()
            fb.current_pose.pose.position.x = self.robot.x
            fb.current_pose.pose.position.y = self.robot.y
            fb.current_pose.pose.orientation.z = math.sin(self.robot.yaw / 2)
            fb.current_pose.pose.orientation.w = math.cos(self.robot.yaw / 2)
            remaining = self.robot.distance_to(gx, gy)
            fb.distance_remaining = float(remaining)
            eta = remaining / self.robot.speed if self.robot.speed > 0 else 0.0
            fb.estimated_time_remaining.sec = int(eta)
            fb.estimated_time_remaining.nanosec = int((eta % 1) * 1e9)
            elapsed = time.monotonic() - started
            fb.navigation_time.sec = int(elapsed)
            fb.navigation_time.nanosec = int((elapsed % 1) * 1e9)
            fb.number_of_recoveries = 0
            handle.publish_feedback(fb)
            if arrived:
                handle.succeed()
                self._clear(my_id)
                self.get_logger().info('Đã tới đích')
                return NavigateToPose.Result()
            time.sleep(dt)
        handle.abort()
        return NavigateToPose.Result()

    def _clear(self, my_id):
        with self.lock:
            if self.active == my_id:
                self.active = None

    def _publish_tf(self):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = self.map_frame
        t.child_frame_id = self.base_frame
        with self.lock:
            t.transform.translation.x = self.robot.x
            t.transform.translation.y = self.robot.y
            t.transform.rotation.z = math.sin(self.robot.yaw / 2)
            t.transform.rotation.w = math.cos(self.robot.yaw / 2)
        self.tf.sendTransform(t)


def main(args=None):
    rclpy.init(args=args)
    node = FakeNav2Server()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
