"""Feeds sample sentences into /speech_text so the real intent resolver runs."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from voice_person_perception import contract

DEFAULT_SCRIPT = [
    'mang đồ đến phòng khách',
    'dừng lại',
    'đưa tới chỗ nấu ăn',
    'hủy đi',
    'hôm nay trời đẹp quá',
    'đến phòng khác',
]


class FakeVoiceNode(Node):

    def __init__(self):
        super().__init__('fake_voice_node')
        self.declare_parameter('script', DEFAULT_SCRIPT)
        self.declare_parameter('interval_s', 8.0)
        self.declare_parameter('repeat', True)
        self._script = list(self.get_parameter('script').value)
        self._index = 0
        self._pub = self.create_publisher(String, contract.SPEECH_TEXT_TOPIC, 10)
        self.create_timer(float(self.get_parameter('interval_s').value), self._tick)
        self.get_logger().info(
            f'fake_voice_node: {len(self._script)} câu, mỗi '
            f"{self.get_parameter('interval_s').value} s")

    def _tick(self):
        if self._index >= len(self._script):
            if not self.get_parameter('repeat').value:
                return
            self._index = 0
        text = self._script[self._index]
        self._index += 1
        stamp = self.get_clock().now().nanoseconds * 1e-9
        msg = String()
        msg.data = contract.dumps(contract.make_speech_text(stamp, text, 0.95, 0.0))
        self._pub.publish(msg)
        self.get_logger().info(f'Giả lập người nói: "{text}"')


def main(args=None):
    rclpy.init(args=args)
    node = FakeVoiceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
