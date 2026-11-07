"""What to draw in RViz for destinations.yaml (no ROS, so it can be tested).

Each destination with a pose becomes an arrow (where the robot stops and which
way it faces) and a text label "name (id)" above it.
"""

from __future__ import annotations

ARROW_LENGTH = 0.5
TEXT_HEIGHT = 0.25
TEXT_Z = 0.6
COLOR_ARROW = (0.1, 0.6, 1.0, 0.9)
COLOR_TEXT = (1.0, 1.0, 1.0, 1.0)


def marker_specs(data):
    """Return (specs, missing_ids). specs: list of dicts, one per marker."""
    specs, missing = [], []
    for index, item in enumerate(data.get('destinations', [])):
        pose = item.get('pose')
        if not pose:
            missing.append(item['id'])
            continue
        x, y, yaw = float(pose['x']), float(pose['y']), float(pose.get('yaw', 0.0))
        name = item.get('name', item['id'])
        specs.append({'ns': 'arrow', 'id': index, 'kind': 'arrow',
                      'x': x, 'y': y, 'z': 0.05, 'yaw': yaw,
                      'scale': (ARROW_LENGTH, 0.08, 0.08), 'color': COLOR_ARROW})
        specs.append({'ns': 'label', 'id': index, 'kind': 'text',
                      'x': x, 'y': y, 'z': TEXT_Z, 'yaw': 0.0,
                      'text': name if name == item['id'] else f"{name} ({item['id']})",
                      'scale': (0.0, 0.0, TEXT_HEIGHT), 'color': COLOR_TEXT})
    return specs, missing
