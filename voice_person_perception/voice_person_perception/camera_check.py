"""Check the robot camera before running person detection.

    ros2 run voice_person_perception camera_check
    ros2 run voice_person_perception camera_check --ros-args -p seconds:=8 -p live:=false

1. Finds colour, depth and camera_info topics (or use rgb_topic/depth_topic/
   info_topic parameters), listens for `seconds` and prints encoding, size, rate.
2. Reports problems: no depth, unsupported encoding, colour/depth with a
   different shape (not aligned), too slow.
3. Prints the person_detector_node command for these topics.
4. live: prints the depth at the image centre twice a second; point the
   camera at a wall or a person and compare with a tape measure. Ctrl+C to stop.
"""

import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

from voice_person_perception import camera_check_logic as cc
from voice_person_perception.ros_image import image_to_numpy


class CameraCheck(Node):

    def __init__(self):
        super().__init__('camera_check')
        for name in ('rgb_topic', 'depth_topic', 'info_topic'):
            self.declare_parameter(name, 'auto')
        self.declare_parameter('prefix', '')
        self.declare_parameter('seconds', 5.0)
        self.declare_parameter('live', True)
        self.stats = {}
        self.last_depth = None
        self.subscribed = set()

    def discover(self):
        get = lambda name: self.get_parameter(name).value  # noqa: E731
        found = cc.pick_topics(self.get_topic_names_and_types(), get('prefix'))
        for key, param in (('rgb', 'rgb_topic'), ('depth', 'depth_topic'),
                           ('info', 'info_topic')):
            if get(param) not in ('', 'auto'):
                found[key] = None if get(param) == 'none' else get(param)
        return found

    def listen(self, found):
        for key in ('rgb', 'depth'):
            name = found[key]
            if name and name not in self.subscribed:
                self.subscribed.add(name)
                self.stats[name] = cc.TopicStats(name)
                self.create_subscription(
                    Image, name, lambda msg, n=name, k=key: self._on_image(n, k, msg),
                    qos_profile_sensor_data)
        if found['info'] and found['info'] not in self.subscribed:
            name = found['info']
            self.subscribed.add(name)
            self.stats[name] = cc.TopicStats(name)
            self.create_subscription(CameraInfo, name, lambda msg, n=name: self._on_info(n, msg),
                                     qos_profile_sensor_data)

    def _on_image(self, name, key, msg):
        self.stats[name].add(time.monotonic(), msg.encoding, msg.width, msg.height)
        if key == 'depth':
            self.last_depth = msg

    def _on_info(self, name, msg):
        self.stats[name].add(time.monotonic(), '', msg.width, msg.height)
        self.stats[name].k = list(msg.k)

    def center(self):
        msg = self.last_depth
        if msg is None or msg.encoding not in cc.DEPTH_ENCODINGS:
            return None
        return cc.depth_center_m(image_to_numpy(msg), msg.encoding)


def spin_for(node, seconds):
    end = time.monotonic() + seconds
    while rclpy.ok() and time.monotonic() < end:
        rclpy.spin_once(node, timeout_sec=0.1)


def fmt(stats):
    if stats is None:
        return '  (không có)'
    if stats.count == 0:
        return f'  {stats.name}: KHÔNG nhận được tin nào'
    size = f'{stats.width}x{stats.height}'
    enc = f' {stats.encoding}' if stats.encoding else ''
    return f'  {stats.name}:{enc} {size}, {stats.hz:.1f} Hz ({stats.count} tin)'


def main(args=None):
    rclpy.init(args=args)
    node = CameraCheck()
    try:
        spin_for(node, 1.0)  # let discovery fill the topic list
        found = node.discover()
        print('\n=== Topic ảnh tìm thấy ===')
        for name in found['images']:
            print(f'  {name}')
        if found['compressed']:
            print('  (nén, node không đọc trực tiếp): ' + ', '.join(found['compressed']))
        if not found['images']:
            print('  Không có topic sensor_msgs/Image nào. Camera đã chạy và cùng '
                  'ROS_DOMAIN_ID chưa?')
        print(f"\nChọn: ảnh màu = {found['rgb']}, depth = {found['depth']}, "
              f"camera_info = {found['info']}")
        node.listen(found)
        seconds = float(node.get_parameter('seconds').value)
        print(f'Đang nghe {seconds:.0f} s...')
        spin_for(node, seconds)

        get = node.stats.get
        rgb, depth, info = get(found['rgb']), get(found['depth']), get(found['info'])
        print('\n=== Kết quả ===')
        for s in (rgb, depth, info):
            print(fmt(s))
        center = node.center()
        if center and center[0] is not None:
            print(f'  Độ sâu giữa ảnh: {center[0]:.2f} m ({center[1]:.0%} điểm hợp lệ)')
        problems, notes = cc.check(rgb, depth, info, center)
        for p in problems:
            print(f'  [LỖI] {p}')
        for n in notes:
            print(f'  [ghi chú] {n}')
        if not problems:
            print('  => Camera ổn để chạy nhận diện người với độ sâu.')
        print('\nLệnh chạy nhận diện người với các topic này:\n'
              + cc.detector_command(found['rgb'], found['depth'], found['info']))

        if node.get_parameter('live').value and depth is not None and depth.count:
            print('\nĐộ sâu giữa ảnh (so với thước đo), Ctrl+C để dừng:')
            while rclpy.ok():
                spin_for(node, 0.5)
                c = node.center()
                if c is None or c[0] is None:
                    print('  --  (không có độ sâu hợp lệ ở giữa ảnh)', flush=True)
                else:
                    print(f'  {c[0]:.2f} m  ({c[1]:.0%} hợp lệ)', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
