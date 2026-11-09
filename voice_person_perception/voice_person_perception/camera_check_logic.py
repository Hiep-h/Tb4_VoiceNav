"""Checks behind camera_check (no ROS): pick camera topics, spot mismatches
between colour and depth images, read the depth at the image centre, and
build the person_detector_node command line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

IMAGE_TYPE = 'sensor_msgs/msg/Image'
INFO_TYPE = 'sensor_msgs/msg/CameraInfo'
COMPRESSED_TYPE = 'sensor_msgs/msg/CompressedImage'
DEPTH_ENCODINGS = ('16UC1', 'mono16', '32FC1')


@dataclass
class TopicStats:
    name: str
    encoding: str = ''
    width: int = 0
    height: int = 0
    count: int = 0
    first_t: float = 0.0
    last_t: float = 0.0
    k: list = field(default_factory=list)  # camera_info only

    def add(self, t, encoding='', width=0, height=0):
        if self.count == 0:
            self.first_t = t
        self.count += 1
        self.last_t = t
        self.encoding, self.width, self.height = encoding, int(width), int(height)

    @property
    def hz(self):
        span = self.last_t - self.first_t
        return (self.count - 1) / span if self.count > 1 and span > 0 else 0.0


def _is_depth_name(name):
    n = name.lower()
    return 'depth' in n or 'stereo' in n


def _rank_rgb(name):
    n = name.lower()
    score = 0
    if 'rgb' in n or 'color' in n:
        score += 10
    if n.endswith('/image_raw'):
        score += 3
    if 'preview' in n:
        score -= 2  # preview is a small, possibly cropped image: worse match with depth
    if _is_depth_name(n) or 'mono' in n or 'left' in n or 'right' in n:
        score -= 20
    return score


def _rank_depth(name):
    n = name.lower()
    score = 0
    if 'stereo/image_raw' in n or n.endswith('/depth/image_raw'):
        score += 10
    if 'depth' in n:
        score += 5
    if 'stereo' in n:
        score += 4
    if 'rgb' in n and 'depth' not in n:
        score -= 20
    return score


def pick_topics(topics, prefix=''):
    """topics: [(name, [types])]. Returns dict rgb/depth/info/compressed topic names."""
    images = [n for n, types in topics if IMAGE_TYPE in types and n.startswith(prefix)]
    infos = [n for n, types in topics if INFO_TYPE in types and n.startswith(prefix)]
    compressed = [n for n, types in topics if COMPRESSED_TYPE in types and n.startswith(prefix)]
    rgb_list = sorted((n for n in images if _rank_rgb(n) > 0), key=_rank_rgb, reverse=True)
    depth_list = sorted((n for n in images if _is_depth_name(n)), key=_rank_depth,
                        reverse=True)
    rgb = rgb_list[0] if rgb_list else None
    depth = depth_list[0] if depth_list else None
    info = None
    if rgb:
        base = rgb.rsplit('/', 1)[0]
        same = [i for i in infos if i.rsplit('/', 1)[0] == base]
        info = same[0] if same else None
    return {'rgb': rgb, 'depth': depth, 'info': info, 'images': images, 'infos': infos,
            'compressed': compressed}


def depth_center_m(depth, encoding, frac=0.1, scale_16u=0.001):
    """Median depth (m) of the central patch and the share of valid pixels there."""
    h, w = depth.shape[:2]
    ph, pw = max(1, int(h * frac)), max(1, int(w * frac))
    patch = depth[(h - ph) // 2:(h + ph) // 2, (w - pw) // 2:(w + pw) // 2].astype(np.float64)
    if encoding != '32FC1':
        patch = patch * scale_16u
    valid = patch[np.isfinite(patch) & (patch > 0.05) & (patch < 20.0)]
    share = valid.size / patch.size if patch.size else 0.0
    return (float(np.median(valid)) if valid.size else None), share


def check(rgb, depth, info=None, center=None):
    """Return (problems, notes): lists of Vietnamese sentences."""
    problems, notes = [], []
    if rgb is None or rgb.count == 0:
        problems.append('Không nhận được ảnh màu nào. Camera đã bật chưa '
                        '(ros2 topic list | grep oakd)?')
    if depth is None or depth.count == 0:
        problems.append('Không có ảnh độ sâu. Bật stereo trong cấu hình OAK-D của TB4 '
                        '(stereo: i_publish_topic: true, i_align_depth: true) rồi chạy lại '
                        'camera. Không có depth thì khoảng cách chỉ là ước lượng.')
    if depth is not None and depth.count and depth.encoding not in DEPTH_ENCODINGS:
        problems.append(f'Encoding depth "{depth.encoding}" không hỗ trợ '
                        f'(cần {", ".join(DEPTH_ENCODINGS)}).')
    if rgb is not None and rgb.count and depth is not None and depth.count:
        ar_rgb = rgb.width / rgb.height if rgb.height else 0
        ar_depth = depth.width / depth.height if depth.height else 0
        if ar_rgb and ar_depth and abs(ar_rgb - ar_depth) / ar_depth > 0.03:
            problems.append(
                f'Ảnh màu {rgb.width}x{rgb.height} và depth {depth.width}x{depth.height} '
                'khác tỉ lệ khung: khung người sẽ lấy nhầm vùng độ sâu. Dùng ảnh màu cùng '
                'tỉ lệ (thường là /oakd/rgb/image_raw thay vì preview) và bật i_align_depth.')
        elif (rgb.width, rgb.height) != (depth.width, depth.height):
            notes.append(f'Ảnh màu {rgb.width}x{rgb.height}, depth {depth.width}x{depth.height}: '
                         'cùng tỉ lệ, node tự co giãn khung. Vẫn cần i_align_depth: true.')
        else:
            notes.append('Ảnh màu và depth cùng kích thước.')
        for s in (rgb, depth):
            if 0 < s.hz < 4:
                problems.append(f'{s.name} chỉ {s.hz:.1f} Hz: quá chậm để theo dõi người '
                                '(mạng wifi? chạy node trên robot hoặc giảm độ phân giải).')
    if info is None or info.count == 0:
        notes.append('Không có camera_info: góc lệch tính theo hfov_deg (69°), kém chính xác hơn.')
    if center is not None:
        dist, share = center
        if dist is None:
            notes.append('Giữa ảnh không có độ sâu hợp lệ (quá gần < 0,2 m, quá xa, hoặc bề mặt '
                         'trơn/bóng). Hướng camera vào tường hay người cách 1-2 m.')
        elif depth is not None and depth.encoding != '32FC1' and dist < 0.05:
            problems.append('Độ sâu rất nhỏ: có thể đơn vị không phải mm.')
        elif share < 0.5:
            notes.append(f'Chỉ {share:.0%} điểm giữa ảnh có độ sâu: kết quả có thể chập chờn.')
    return problems, notes


def detector_command(rgb, depth, info):
    args = [f'-p image_topic:={rgb or "<ảnh màu>"}']
    args.append(f'-p depth_topic:={depth or "none"}')
    if info:
        args.append(f'-p camera_info_topic:={info}')
    args.append('-p debug_image:=true')
    return ('ros2 run voice_person_perception person_detector_node --ros-args \\\n    '
            + ' '.join(args))
