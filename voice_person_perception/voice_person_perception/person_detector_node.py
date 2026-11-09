"""OAK-D RGB + depth -> /person_detections (distance and bearing of each person).

Without a depth camera (laptop webcam: depth_topic:=none) the distance is a
rough estimate from the box size (size_fallback). debug_image publishes the
camera image with boxes, distance and bearing on /person_detections/image.
"""

import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String

from voice_person_perception import contract
from voice_person_perception.person_math import (
    PersonSmoother,
    bearing_deg,
    depth_median_m,
    fx_from_hfov,
    scale_bbox,
    size_distance_m,
)
from voice_person_perception.ros_image import image_to_numpy, numpy_to_image


class PersonDetectorNode(Node):

    def __init__(self):
        super().__init__('person_detector_node')
        self.declare_parameter('image_topic', '/oakd/rgb/preview/image_raw')
        self.declare_parameter('depth_topic', '/oakd/rgb/preview/depth')
        self.declare_parameter('camera_info_topic', '/oakd/rgb/preview/camera_info')
        self.declare_parameter('model', 'yolov8n.pt')
        self.declare_parameter('device', '')
        self.declare_parameter('conf', 0.5)
        self.declare_parameter('imgsz', 320)
        self.declare_parameter('use_tracker', True)
        self.declare_parameter('infer_rate_hz', 5.0)
        self.declare_parameter('publish_rate_hz', 10.0)
        self.declare_parameter('depth_scale', 0.001)
        self.declare_parameter('hfov_deg', 69.0)
        self.declare_parameter('min_depth_m', 0.2)
        self.declare_parameter('max_depth_m', 8.0)
        self.declare_parameter('result_ttl_s', 0.5)
        self.declare_parameter('stale_after_s', 1.0)
        self.declare_parameter('approach_speed', 0.2)
        self.declare_parameter('size_fallback', True)
        self.declare_parameter('person_height_m', 1.7)
        self.declare_parameter('debug_image', False)

        get = lambda name: self.get_parameter(name).value  # noqa: E731
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError('Cài ultralytics: pip install ultralytics') from exc
        self._model = YOLO(get('model'))
        self._smoother = PersonSmoother(approach_speed=float(get('approach_speed')))

        self._depth = None
        self._depth_scale = float(get('depth_scale'))
        self._depth_rx = 0.0
        self._fx = None
        self._info_width = None
        self._last_frame_rx = None
        self._last_infer = 0.0
        self._persons = []
        self._persons_rx = 0.0

        self.create_subscription(Image, get('image_topic'), self._on_image,
                                 qos_profile_sensor_data)
        if get('depth_topic') not in ('', 'none'):
            self.create_subscription(Image, get('depth_topic'), self._on_depth,
                                     qos_profile_sensor_data)
        else:
            self.get_logger().info('Không có depth: khoảng cách ước lượng theo kích thước '
                                   'khung người (chỉ để thử, sai số lớn)')
        self._debug_pub = (self.create_publisher(Image, contract.PERSON_TOPIC + '/image', 2)
                           if get('debug_image') else None)
        self.create_subscription(CameraInfo, get('camera_info_topic'), self._on_info,
                                 qos_profile_sensor_data)
        self._pub = self.create_publisher(String, contract.PERSON_TOPIC, 10)
        self.create_timer(1.0 / float(get('publish_rate_hz')), self._publish)
        self.get_logger().info(f"person_detector_node sẵn sàng (model {get('model')})")

    def _on_info(self, msg):
        if msg.k[0] > 0:
            self._fx = float(msg.k[0])
            self._info_width = int(msg.width)

    def _on_depth(self, msg):
        try:
            self._depth = image_to_numpy(msg)
        except ValueError as exc:
            self.get_logger().warn(str(exc), throttle_duration_sec=10.0)
            return
        self._depth_scale = 1.0 if msg.encoding == '32FC1' else float(
            self.get_parameter('depth_scale').value)
        self._depth_rx = time.monotonic()

    def _on_image(self, msg):
        now_mono = time.monotonic()
        self._last_frame_rx = now_mono
        if now_mono - self._last_infer < 1.0 / float(self.get_parameter('infer_rate_hz').value):
            return
        self._last_infer = now_mono
        try:
            frame = image_to_numpy(msg)
        except ValueError as exc:
            self.get_logger().warn(str(exc), throttle_duration_sec=10.0)
            return
        self._persons = self._detect(frame, msg.header)
        self._persons_rx = time.monotonic()

    def _detect(self, frame, header=None):
        get = lambda name: self.get_parameter(name).value  # noqa: E731
        kwargs = dict(classes=[0], conf=float(get('conf')), imgsz=int(get('imgsz')),
                      verbose=False)
        if get('device'):
            kwargs['device'] = get('device')
        if get('use_tracker'):
            result = self._model.track(frame, persist=True, **kwargs)[0]
        else:
            result = self._model.predict(frame, **kwargs)[0]

        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            self._publish_debug(frame, [], [], header)
            return []
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        ids = (boxes.id.cpu().numpy().astype(int).tolist()
               if boxes.id is not None else [None] * len(xyxy))

        height, width = frame.shape[:2]
        if self._fx is not None and self._info_width:
            fx = self._fx * width / self._info_width
        else:
            fx = fx_from_hfov(width, float(get('hfov_deg')))
        depth_fresh = (self._depth is not None
                       and time.monotonic() - self._depth_rx < float(get('stale_after_s')))
        now = self.get_clock().now().nanoseconds * 1e-9

        persons, drawn = [], []
        for box, conf, track_id in zip(xyxy, confs, ids):
            bearing = bearing_deg((box[0] + box[2]) / 2.0, width / 2.0, fx)
            distance, source = None, None
            if depth_fresh:
                distance = depth_median_m(
                    self._depth, scale_bbox(box, (height, width), self._depth.shape[:2]),
                    self._depth_scale, min_m=float(get('min_depth_m')),
                    max_m=float(get('max_depth_m')))
                source = 'depth' if distance is not None else None
            elif get('size_fallback'):
                distance, source = size_distance_m(
                    box, frame.shape, fx, person_height_m=float(get('person_height_m')))
            approaching = False
            if track_id is not None:
                distance, bearing, approaching = self._smoother.update(
                    track_id, now, distance, bearing)
            person = contract.make_person(track_id, distance, bearing, float(conf),
                                          approaching, source)
            persons.append(person)
            drawn.append(box)
        self._smoother.prune(now)
        self._publish_debug(frame, drawn, persons, header)
        order = sorted(range(len(persons)), key=lambda i: (
            persons[i]['distance_m'] is None, persons[i]['distance_m'] or 0.0))
        return [persons[i] for i in order]

    def _publish_debug(self, frame, boxes, persons, header):
        if self._debug_pub is None:
            return
        from voice_person_perception.person_draw import draw_persons
        image = draw_persons(frame, boxes, persons)
        msg = numpy_to_image(image, 'bgr8', header.frame_id if header else '',
                             header.stamp if header else None)
        self._debug_pub.publish(msg)

    def _publish(self):
        now_mono = time.monotonic()
        frame_age = None if self._last_frame_rx is None else now_mono - self._last_frame_rx
        healthy = frame_age is not None and frame_age < float(
            self.get_parameter('stale_after_s').value)
        fresh = now_mono - self._persons_rx < float(self.get_parameter('result_ttl_s').value)
        persons = self._persons if (healthy and fresh) else []
        stamp = self.get_clock().now().nanoseconds * 1e-9
        msg = String()
        msg.data = contract.dumps(contract.make_person_message(stamp, persons, healthy,
                                                               frame_age))
        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
