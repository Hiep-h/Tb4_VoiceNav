"""Draw destinations.yaml on RViz and redraw whenever the file changes.

    ros2 run voice_person_perception destination_markers --ros-args \\
        -p file:=$PWD/src/<repo>/voice_person_perception/config/destinations.yaml

In RViz: Add -> By topic -> /destination_markers (MarkerArray).
"""

import os

import rclpy
import yaml
from rclpy.node import Node
from visualization_msgs.msg import Marker, MarkerArray

from voice_person_perception.intent_resolver_node import _default_destinations_file
from voice_person_perception.marker_specs import marker_specs
from voice_person_perception.waypoints import quaternion_from_yaw


class DestinationMarkers(Node):

    def __init__(self):
        super().__init__('destination_markers')
        self.declare_parameter('file', '')
        self.declare_parameter('rate_hz', 1.0)
        self.path = self.get_parameter('file').value or _default_destinations_file()
        self.pub = self.create_publisher(MarkerArray, '/destination_markers', 10)
        self._mtime = None
        self._msg = MarkerArray()
        self.create_timer(1.0 / float(self.get_parameter('rate_hz').value), self._tick)
        self.get_logger().info(f'Vẽ điểm đến từ {os.path.abspath(self.path)}')

    def _tick(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.get_logger().warn(f'Không thấy file {self.path}', throttle_duration_sec=10.0)
            return
        if mtime != self._mtime:
            self._mtime = mtime
            self._reload()
        self.pub.publish(self._msg)

    def _reload(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            specs, missing = marker_specs(data)
        except Exception as exc:  # half-written or hand-edited file: keep the old drawing
            self.get_logger().warn(f'Đọc file lỗi, giữ hình cũ: {exc}')
            return
        frame = data.get('frame', 'map')
        clear = Marker()
        clear.header.frame_id = frame
        clear.action = Marker.DELETEALL
        markers = [clear] + [self._to_marker(s, frame) for s in specs]
        self._msg = MarkerArray(markers=markers)
        self.get_logger().info(
            f'{len(specs) // 2} điểm có vị trí'
            + (f", chưa có vị trí: {', '.join(missing)}" if missing else ''))

    def _to_marker(self, spec, frame):
        m = Marker()
        m.header.frame_id = frame
        m.ns, m.id = spec['ns'], spec['id']
        m.type = Marker.ARROW if spec['kind'] == 'arrow' else Marker.TEXT_VIEW_FACING
        m.action = Marker.ADD
        m.pose.position.x, m.pose.position.y, m.pose.position.z = \
            spec['x'], spec['y'], spec['z']
        qx, qy, qz, qw = quaternion_from_yaw(spec['yaw'])
        m.pose.orientation.x, m.pose.orientation.y = qx, qy
        m.pose.orientation.z, m.pose.orientation.w = qz, qw
        m.scale.x, m.scale.y, m.scale.z = spec['scale']
        m.color.r, m.color.g, m.color.b, m.color.a = spec['color']
        m.text = spec.get('text', '')
        return m


def main(args=None):
    rclpy.init(args=args)
    node = DestinationMarkers()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
