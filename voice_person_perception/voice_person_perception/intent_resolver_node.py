"""/speech_text -> /voice_command (intent + destination, one message per command)."""

import json
import os

import rclpy
import yaml
from rclpy.node import Node
from std_msgs.msg import String

from voice_person_perception import contract
from voice_person_perception.intent import load_destinations, parse_utterance


def _default_destinations_file():
    try:
        from ament_index_python.packages import get_package_share_directory
        path = os.path.join(get_package_share_directory('voice_person_perception'),
                            'config', 'destinations.yaml')
        if os.path.isfile(path):
            return path
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, '..', 'config', 'destinations.yaml')


class IntentResolverNode(Node):

    def __init__(self):
        super().__init__('intent_resolver_node')
        self.declare_parameter('destinations_file', '')
        self.declare_parameter('accept', 0.75)
        self.declare_parameter('confident', 0.97)
        self.declare_parameter('margin', 0.10)
        self.declare_parameter('min_asr_conf', 0.6)
        self.declare_parameter('dedupe_window_s', 1.5)

        path = self.get_parameter('destinations_file').value
        if path in ('', 'auto'):
            path = _default_destinations_file()
        with open(path, encoding='utf-8') as f:
            self._destinations = load_destinations(yaml.safe_load(f))
        self.get_logger().info(
            f'Đã nạp {len(self._destinations)} điểm đến từ {os.path.abspath(path)}')

        self._seq = 0
        self._last = (None, None, -1e9)
        self._pub = self.create_publisher(String, contract.VOICE_COMMAND_TOPIC, 10)
        self.create_subscription(String, contract.SPEECH_TEXT_TOPIC, self._on_text, 10)

    def _on_text(self, msg):
        text, asr_conf = msg.data, 1.0
        try:
            payload = json.loads(msg.data)
            text = payload['text']
            asr_conf = float(payload.get('asr_conf', 1.0))
        except (ValueError, KeyError, TypeError):
            pass  # plain text, e.g. typed with `ros2 topic pub`

        p = self.get_parameter
        result = parse_utterance(
            text, self._destinations, asr_conf=asr_conf,
            accept=p('accept').value, confident=p('confident').value,
            margin=p('margin').value, min_asr_conf=p('min_asr_conf').value)

        now = self.get_clock().now().nanoseconds * 1e-9
        last_intent, last_dest, last_time = self._last
        if (result.intent == last_intent and result.destination == last_dest
                and now - last_time < p('dedupe_window_s').value):
            return
        self._last = (result.intent, result.destination, now)

        self._seq += 1
        out = String()
        out.data = contract.dumps(contract.make_voice_command(
            self._seq, now, text, result.intent, result.destination,
            result.confidence, result.needs_confirm, result.candidates))
        self._pub.publish(out)
        self.get_logger().info(
            f'"{text}" -> {result.intent} {result.destination or ""} '
            f'(conf {result.confidence:.2f}, confirm={result.needs_confirm})')


def main(args=None):
    rclpy.init(args=args)
    node = IntentResolverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
