"""Read, edit and write destinations.yaml with map poses (no ROS).

Each destination may carry the pose the robot should drive to, in the `map`
frame of the saved map:

    - id: bep
      name: bếp
      aliases: [nhà bếp, chỗ tủ lạnh]
      pose: {x: 1.25, y: -0.4, yaw: 1.571}

The voice side only reads id/name/aliases; the execution side reads `pose`.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import unicodedata

import yaml

HEADER = """\
# Danh sách điểm đến dùng chung giữa phần giọng nói và bên thực thi.
# - id: tên waypoint mà /voice_command gửi đi (không dấu, không cách).
# - name, aliases: các cách gọi; thêm cả từ mà nhận dạng hay nghe nhầm.
#   Viết số bằng chữ trong aliases ("một không một").
# - pose: vị trí robot cần tới, hệ `map` của bản đồ ghi ở `map`; yaw tính bằng radian.
# Ghi bằng `ros2 run voice_person_perception waypoint_marker`, sửa tay cũng được.
"""


def slugify(name):
    """'Phòng khách' -> 'phong_khach', 'phòng 101' -> 'phong_101'."""
    text = unicodedata.normalize('NFC', name).lower().replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '_', text).strip('_')


def yaw_from_quaternion(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def quaternion_from_yaw(yaw):
    """(x, y, z, w) for a rotation about the vertical axis."""
    return 0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def parse_aliases(text):
    """'nhà bếp, chỗ tủ lạnh;khu bếp' -> ['nhà bếp', 'chỗ tủ lạnh', 'khu bếp']."""
    parts = re.split(r'[,;]', text or '')
    return list(dict.fromkeys(' '.join(p.split()) for p in parts if p.strip()))


def make_pose(x, y, yaw):
    return {'x': round(float(x), 3), 'y': round(float(y), 3),
            'yaw': round(math.atan2(math.sin(yaw), math.cos(yaw)), 3)}


def load(path):
    if not os.path.isfile(path):
        return {'destinations': []}
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    data.setdefault('destinations', [])
    return data


def find(data, dest_id):
    for item in data['destinations']:
        if item.get('id') == dest_id:
            return item
    return None


def upsert(data, dest_id, name=None, aliases=(), pose=None):
    """Add a destination or update it: keep old aliases, add new ones, set pose.

    Returns 'added' or 'updated'.
    """
    item = find(data, dest_id)
    status = 'updated'
    if item is None:
        item = {'id': dest_id, 'name': name or dest_id, 'aliases': []}
        data['destinations'].append(item)
        status = 'added'
    elif name:
        item['name'] = name
    merged = list(item.get('aliases', [])) + [a for a in aliases if a]
    names = {item['name'].lower()}
    item['aliases'] = [a for a in dict.fromkeys(merged) if a.lower() not in names]
    if pose is not None:
        item['pose'] = pose
    return status


def remove(data, dest_id):
    before = len(data['destinations'])
    data['destinations'] = [d for d in data['destinations'] if d.get('id') != dest_id]
    return len(data['destinations']) < before


def missing_pose(data):
    return [d['id'] for d in data['destinations'] if 'pose' not in d]


def dumps(data):
    ordered = {}
    for key in ('map', 'frame'):
        if key in data:
            ordered[key] = data[key]
    ordered['destinations'] = []
    for item in data['destinations']:
        out = {k: item[k] for k in ('id', 'name', 'aliases', 'pose') if k in item}
        out.update({k: v for k, v in item.items() if k not in out})
        ordered['destinations'].append(out)
    for key, value in data.items():
        if key not in ordered:
            ordered[key] = value
    body = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False,
                          default_flow_style=None, width=100)
    return HEADER + body


def save(path, data, backup=True):
    """Write the file; the first save keeps the old file as <path>.bak."""
    if backup and os.path.isfile(path) and not os.path.isfile(path + '.bak'):
        shutil.copyfile(path, path + '.bak')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(dumps(data))
    os.replace(tmp, path)


def nav_goal_command(item, frame='map'):
    """`ros2 action send_goal` line that drives Nav2 to this destination."""
    pose = item['pose']
    _, _, qz, qw = quaternion_from_yaw(float(pose.get('yaw', 0.0)))
    goal = (f"{{pose: {{header: {{frame_id: {frame}}}, pose: {{position: "
            f"{{x: {float(pose['x']):.3f}, y: {float(pose['y']):.3f}, z: 0.0}}, "
            f"orientation: {{x: 0.0, y: 0.0, z: {qz:.4f}, w: {qw:.4f}}}}}}}}}")
    return ('ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose '
            f'"{goal}" --feedback')


def goal_main(argv=None):
    """CLI: print the Nav2 goal command for one destination (or all)."""
    import argparse
    ap = argparse.ArgumentParser(description='In lệnh gửi robot tới một điểm đến (thử Nav2).')
    ap.add_argument('id', nargs='?', help='id điểm đến; bỏ trống = in tất cả')
    ap.add_argument('--file', required=True, help='đường dẫn destinations.yaml')
    args = ap.parse_args(argv)
    data = load(args.file)
    frame = data.get('frame', 'map')
    items = [find(data, args.id)] if args.id else data['destinations']
    if args.id and items[0] is None:
        print(f'Không có điểm {args.id}')
        return 1
    for item in items:
        if 'pose' not in item:
            print(f"# {item['id']}: chưa có vị trí")
            continue
        print(f"# {item['id']} ({item.get('name', '')})")
        print(nav_goal_command(item, frame))
    return 0
