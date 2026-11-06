"""Scripted /person_detections for testing the executor without a camera.

20 s loop: nobody (0-4 s), a person walks up to 0.6 m (4-10 s), stands
(10-13 s), walks away to 3 m (13-18 s), nobody (18-20 s).
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from voice_person_perception import contract
from voice_person_perception.fake_scenarios import LOOP_S, scenario


class FakePersonNode(Node):

    def __init__(self):
        super().__init__('fake_person_node')
        self.declare_parameter('bearing_deg', 0.0)
        self.declare_parameter('rate_hz', 10.0)
        self._start = self.get_clock().now().nanoseconds * 1e-9
        self._pub = self.create_publisher(String, contract.PERSON_TOPIC, 10)
        self.create_timer(1.0 / float(self.get_parameter('rate_hz').value), self._tick)
        self.get_logger().info('fake_person_node: phát kịch bản người đi tới/đi xa (vòng 20 s)')

    def _tick(self):
        now = self.get_clock().now().nanoseconds * 1e-9
        persons = scenario((now - self._start) % LOOP_S,
                           float(self.get_parameter('bearing_deg').value))
        msg = String()
        msg.data = contract.dumps(contract.make_person_message(now, persons, True, 0.0))
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = FakePersonNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
