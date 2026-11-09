"""Publish a laptop/USB webcam as ROS images, to test person detection without the robot.

    ros2 run voice_person_perception webcam_node --ros-args -p device:=0

Publishes /webcam/image_raw (bgr8) and /webcam/camera_info (focal length from
hfov_deg, an estimate: most laptop webcams are 60-75 degrees wide).
"""

import math
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image

from voice_person_perception.ros_image import numpy_to_image


class WebcamNode(Node):

    def __init__(self):
        super().__init__('webcam_node')
        self.declare_parameter('device', 0)
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 15.0)
        self.declare_parameter('hfov_deg', 65.0)
        self.declare_parameter('frame_id', 'webcam')
        get = lambda name: self.get_parameter(name).value  # noqa: E731

        import cv2
        self._cv2 = cv2
        self._cap = cv2.VideoCapture(int(get('device')))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(get('width')))
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(get('height')))
        if not self._cap.isOpened():
            raise RuntimeError(f"Không mở được webcam {get('device')} "
                               '(thử device:=1, hoặc kiểm tra quyền /dev/video*)')
        self._frame_id = get('frame_id')
        self._hfov = float(get('hfov_deg'))
        self._img_pub = self.create_publisher(Image, '/webcam/image_raw', qos_profile_sensor_data)
        self._info_pub = self.create_publisher(CameraInfo, '/webcam/camera_info',
                                               qos_profile_sensor_data)
        self._fails = 0
        self.create_timer(1.0 / float(get('fps')), self._tick)
        self.get_logger().info(f"webcam_node: thiết bị {get('device')}, phát /webcam/image_raw")

    def _tick(self):
        ok, frame = self._cap.read()
        if not ok:
            self._fails += 1
            if self._fails % 30 == 1:
                self.get_logger().warn('Không đọc được ảnh từ webcam')
            return
        self._fails = 0
        stamp = self.get_clock().now().to_msg()
        self._img_pub.publish(numpy_to_image(frame, 'bgr8', self._frame_id, stamp))
        self._info_pub.publish(camera_info(frame.shape[1], frame.shape[0], self._hfov,
                                           self._frame_id, stamp))

    def destroy_node(self):
        self._cap.release()
        super().destroy_node()


def camera_info(width, height, hfov_deg, frame_id='', stamp=None):
    fx = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    msg = CameraInfo()
    if stamp is not None:
        msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.width, msg.height = int(width), int(height)
    msg.k = [fx, 0.0, width / 2.0, 0.0, fx, height / 2.0, 0.0, 0.0, 1.0]
    return msg


def main(args=None):
    rclpy.init(args=args)
    node = WebcamNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
        time.sleep(0.1)


if __name__ == '__main__':
    main()
