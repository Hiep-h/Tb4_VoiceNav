import numpy as np

from voice_person_perception import camera_check_logic as cc

IMG, INFO = [cc.IMAGE_TYPE], [cc.INFO_TYPE]
TB4_TOPICS = [
    ('/oakd/rgb/preview/image_raw', IMG), ('/oakd/rgb/preview/camera_info', INFO),
    ('/oakd/rgb/image_raw', IMG), ('/oakd/rgb/camera_info', INFO),
    ('/oakd/stereo/image_raw', IMG), ('/oakd/stereo/camera_info', INFO),
    ('/oakd/stereo/image_raw/compressedDepth', [cc.COMPRESSED_TYPE]),
    ('/scan', ['sensor_msgs/msg/LaserScan']),
]


def test_pick_prefers_full_rgb_and_stereo_depth():
    found = cc.pick_topics(TB4_TOPICS)
    assert found['rgb'] == '/oakd/rgb/image_raw'
    assert found['depth'] == '/oakd/stereo/image_raw'
    assert found['info'] == '/oakd/rgb/camera_info'
    assert found['compressed'] == ['/oakd/stereo/image_raw/compressedDepth']


def test_pick_preview_only_and_no_depth():
    found = cc.pick_topics([('/oakd/rgb/preview/image_raw', IMG),
                            ('/oakd/rgb/preview/camera_info', INFO)])
    assert found['rgb'] == '/oakd/rgb/preview/image_raw'
    assert found['depth'] is None
    assert found['info'] == '/oakd/rgb/preview/camera_info'


def _stats(name, enc, w, h, n=20, hz=10.0):
    s = cc.TopicStats(name)
    for i in range(n):
        s.add(i / hz, enc, w, h)
    return s


def test_check_good_aligned_camera():
    rgb = _stats('/rgb', 'bgr8', 1280, 720)
    depth = _stats('/depth', '16UC1', 640, 360)
    problems, notes = cc.check(rgb, depth, _stats('/info', '', 1280, 720), (1.5, 0.9))
    assert problems == []
    assert any('cùng tỉ lệ' in n for n in notes)


def test_check_reports_each_problem():
    problems, _ = cc.check(_stats('/rgb', 'bgr8', 250, 250), None)
    assert any('Không có ảnh độ sâu' in p for p in problems)
    problems, _ = cc.check(_stats('/rgb', 'bgr8', 250, 250), _stats('/d', '16UC1', 1280, 720))
    assert any('khác tỉ lệ' in p for p in problems)  # square preview vs 16:9 depth
    problems, _ = cc.check(_stats('/rgb', 'bgr8', 640, 360), _stats('/d', 'rgb8', 640, 360))
    assert any('Encoding depth' in p for p in problems)
    problems, _ = cc.check(_stats('/rgb', 'bgr8', 640, 360, hz=2.0),
                           _stats('/d', '16UC1', 640, 360))
    assert any('quá chậm' in p for p in problems)
    problems, _ = cc.check(cc.TopicStats('/rgb'), None)
    assert any('Không nhận được ảnh màu' in p for p in problems)


def test_topic_stats_rate():
    assert abs(_stats('/x', 'bgr8', 1, 1, n=11, hz=5.0).hz - 5.0) < 1e-9
    assert cc.TopicStats('/x').hz == 0.0


def test_depth_center():
    depth = np.full((100, 200), 1500, np.uint16)  # 1.5 m in mm
    depth[45:55, 95:105] = 0                        # a hole in the middle
    dist, share = cc.depth_center_m(depth, '16UC1')
    assert dist == 1.5 and share < 1.0
    metres = np.full((10, 10), 2.25, np.float32)
    assert cc.depth_center_m(metres, '32FC1') == (2.25, 1.0)
    assert cc.depth_center_m(np.zeros((10, 10), np.uint16), '16UC1') == (None, 0.0)


def test_detector_command():
    cmd = cc.detector_command('/oakd/rgb/image_raw', '/oakd/stereo/image_raw',
                              '/oakd/rgb/camera_info')
    assert '-p depth_topic:=/oakd/stereo/image_raw' in cmd and 'debug_image:=true' in cmd
    assert '-p depth_topic:=none' in cc.detector_command('/rgb', None, None)
