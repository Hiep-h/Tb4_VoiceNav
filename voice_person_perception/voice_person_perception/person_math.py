"""Geometry and smoothing for person detections (no ROS).

Bearing convention: positive = person on the robot's LEFT (counter-clockwise,
like ROS yaw); negative = right. Image x grows to the right, so it is negated.
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np


def fx_from_hfov(width_px, hfov_deg):
    return (width_px / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)


def bearing_deg(cx_px, cx0_px, fx):
    return -math.degrees(math.atan2(cx_px - cx0_px, fx))


def scale_bbox(bbox, from_shape, to_shape):
    """Map (x1, y1, x2, y2) between images of different (h, w)."""
    sy = to_shape[0] / from_shape[0]
    sx = to_shape[1] / from_shape[1]
    x1, y1, x2, y2 = bbox
    return x1 * sx, y1 * sy, x2 * sx, y2 * sy


def depth_median_m(depth, bbox, scale=0.001, region_frac=0.4, min_m=0.2, max_m=8.0):
    """Median depth over the central part of a box (the torso), or None."""
    h, w = depth.shape[:2]
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    half_w = (x2 - x1) * region_frac / 2.0
    half_h = (y2 - y1) * region_frac / 2.0
    xa, xb = int(max(0, cx - half_w)), int(min(w, cx + half_w + 1))
    ya, yb = int(max(0, cy - half_h)), int(min(h, cy + half_h + 1))
    if xb <= xa or yb <= ya:
        return None
    patch = depth[ya:yb, xa:xb].astype(np.float64) * scale
    valid = patch[np.isfinite(patch) & (patch >= min_m) & (patch <= max_m)]
    return float(np.median(valid)) if valid.size else None


def size_distance_m(bbox, frame_shape, fx, person_height_m=1.7, shoulder_m=0.5,
                    edge_frac=0.02, min_m=0.3, max_m=8.0):
    """Rough distance from box size, for cameras without depth (laptop webcam).

    Whole body visible: distance = fx * height / box height (fy ~ fx).
    Feet cut off but head visible (close to the camera): use the shoulder
    width instead. Head cut off: None. Returns (distance or None, source).
    """
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = bbox
    edge = edge_frac * h
    head_visible = y1 > edge
    feet_visible = y2 < h - edge
    if head_visible and feet_visible and y2 - y1 > 1:
        dist, source = fx * person_height_m / (y2 - y1), 'height'
    elif head_visible and x2 - x1 > 1:
        dist, source = fx * shoulder_m / (x2 - x1), 'width'
    else:
        return None, None
    return (float(dist), source) if min_m <= dist <= max_m else (None, None)


class PersonSmoother:
    """Per-track smoothing and approach detection."""

    def __init__(self, alpha=0.4, window_s=1.0, approach_speed=0.2, ttl_s=1.5):
        self.alpha = alpha
        self.window_s = window_s
        self.approach_speed = approach_speed
        self.ttl_s = ttl_s
        self._tracks = {}

    def update(self, track_id, now, distance_m, bearing):
        """Return (smoothed_distance, smoothed_bearing, approaching)."""
        tr = self._tracks.get(track_id)
        if tr is None:
            tr = {'d': distance_m, 'b': bearing, 'hist': deque(), 'seen': now}
            self._tracks[track_id] = tr
        else:
            tr['b'] = self.alpha * bearing + (1 - self.alpha) * tr['b']
            if distance_m is not None:
                tr['d'] = (distance_m if tr['d'] is None else
                           self.alpha * distance_m + (1 - self.alpha) * tr['d'])
            tr['seen'] = now
        hist = tr['hist']
        if tr['d'] is not None:
            hist.append((now, tr['d']))
        while hist and now - hist[0][0] > self.window_s:
            hist.popleft()
        approaching = False
        if len(hist) >= 2 and hist[-1][0] - hist[0][0] >= 0.4:
            speed = (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0])
            approaching = bool(speed < -self.approach_speed)
        return tr['d'], tr['b'], approaching

    def prune(self, now):
        stale = [k for k, t in self._tracks.items() if now - t['seen'] > self.ttl_s]
        for k in stale:
            del self._tracks[k]
