"""Station poses from destinations.yaml (no ROS).

The file is shared with voice_person_perception and written by its
waypoint_marker tool:

    frame: map
    destinations:
    - id: B
      name: trạm B
      pose: {x: 1.5, y: -0.25, yaw: 1.571}   # metres, metres, radians in `frame`

A station without `pose` is known but cannot be driven to yet.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float = 0.0

    def quaternion(self):
        """(x, y, z, w) of a rotation about the vertical axis."""
        return 0.0, 0.0, math.sin(self.yaw / 2.0), math.cos(self.yaw / 2.0)

    def distance_to(self, other):
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True)
class Stations:
    poses: dict          # station id -> Pose2D, or None when not marked yet
    names: dict          # station id -> spoken name
    frame: str = 'map'
    map_name: str = ''

    def has(self, station_id):
        return station_id in self.poses

    def pose(self, station_id):
        return self.poses.get(station_id)


def parse_stations(data):
    poses, names = {}, {}
    for item in (data or {}).get('destinations', []):
        sid = str(item['id'])
        names[sid] = item.get('name', sid)
        p = item.get('pose')
        poses[sid] = None if not p else Pose2D(float(p['x']), float(p['y']),
                                               float(p.get('yaw', 0.0)))
    return Stations(poses, names, str((data or {}).get('frame', 'map')),
                    str((data or {}).get('map', '')))


def load_stations(path):
    with open(path, encoding='utf-8') as f:
        return parse_stations(yaml.safe_load(f))


def default_stations_file():
    """destinations.yaml installed by voice_person_perception, if any."""
    try:
        from ament_index_python.packages import get_package_share_directory
        path = os.path.join(get_package_share_directory('voice_person_perception'),
                            'config', 'destinations.yaml')
        if os.path.isfile(path):
            return path
    except Exception:
        pass
    return None
