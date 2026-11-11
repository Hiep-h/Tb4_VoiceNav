"""Drawing and layout for station_marker_gui (no ROS).

Left panel: the stations with their state and the buttons. Right panel: the
live map (/map) or a grid, the robot, the stations. Everything is drawn with
PIL so Vietnamese text keeps its accents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from voice_person_perception import gui_render as gr

PANEL_W = gr.PANEL_W
PANEL_H = gr.PANEL_H
MAP_W = 700

GREEN, BLUE, AMBER, RED, GREY, DARK = gr.GREEN, gr.BLUE, gr.AMBER, gr.RED, gr.GREY, gr.DARK
ROW_BG, SEL_BG = (255, 255, 255), (228, 236, 255)


@dataclass(frozen=True)
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


def layout(station_ids):
    """Clickable areas of the left panel: {'station:A': Rect, 'save_pose': Rect, ...}."""
    rects = {}
    top, bottom = 66, 352
    row_h = min(68, max(36, (bottom - top) // max(1, len(station_ids))))
    for i, sid in enumerate(station_ids):
        y = top + i * row_h
        rects[f'station:{sid}'] = Rect(14, y, PANEL_W - 14, y + row_h - 6)
    y = max(top + len(station_ids) * row_h + 6, 360)
    rects['save_pose'] = Rect(14, y, PANEL_W - 14, y + 54)
    y += 64
    half = (PANEL_W - 14 * 2 - 10) // 2
    rects['pick'] = Rect(14, y, 14 + half, y + 42)
    rects['clear'] = Rect(PANEL_W - 14 - half, y, PANEL_W - 14, y + 42)
    y += 52
    rects['save_map'] = Rect(14, y, PANEL_W - 14, y + 42)
    return rects


def hit(rects, x, y):
    for name, rect in rects.items():
        if rect.contains(x, y):
            return name
    return None


def occupancy_to_image(data, width, height):
    """nav_msgs/OccupancyGrid data (row 0 = bottom) -> greyscale PIL image (row 0 = top),
    with map_saver colours: free 254, occupied 0, unknown 205."""
    grid = np.asarray(data, dtype=np.int16).reshape(height, width)
    img = np.full((height, width), 205, dtype=np.uint8)
    img[(grid >= 0) & (grid < 25)] = 254
    img[grid >= 65] = 0
    mid = (grid >= 25) & (grid < 65)
    img[mid] = (254 - grid[mid] * 254 // 100).astype(np.uint8)
    return Image.fromarray(np.flipud(img), mode='L')


def drag_yaw(start, end, min_m=0.15):
    """Heading from a mouse drag on the map (world coords), or None for a click."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    if math.hypot(dx, dy) < min_m:
        return None
    return math.atan2(dy, dx)


def station_line(item):
    pose = item.get('pose')
    if not pose:
        return 'chưa đánh dấu', RED
    return (f"✓ x={pose['x']:.2f}  y={pose['y']:.2f}  hướng {math.degrees(pose['yaw']):.0f}°",
            GREEN)


def _button(d, rect, text, fill, fg=(255, 255, 255), size=17):
    d.rounded_rectangle([rect.x0, rect.y0, rect.x1, rect.y1], radius=8, fill=fill)
    f = gr.font(size, True)
    w = gr.text_w(d, text, f)
    d.text(((rect.x0 + rect.x1 - w) / 2, (rect.y0 + rect.y1) / 2 - size * 0.62), text,
           font=f, fill=fg)


def _fit(d, path, max_w=300):
    """Shorten a long path from the left so the button text fits."""
    f = gr.font(15, True)
    while gr.text_w(d, path, f) > max_w and len(path) > 8:
        path = '…' + path[2:]
    return path


def render_left(view):
    """view: stations (list of dicts), selected, pick_mode, robot_ok, message,
    message_colour, map_target (e.g. '~/maps/lab'), saving_map."""
    img = Image.new('RGB', (PANEL_W, PANEL_H), gr.BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, PANEL_W, 56], fill=gr.TITLE_BG)
    d.text((14, 14), 'Đánh dấu trạm trên map', font=gr.font(20, True), fill=(255, 255, 255))
    stations = view.get('stations', [])
    rects = layout([s['id'] for s in stations])
    for item in stations:
        r = rects[f"station:{item['id']}"]
        sel = item['id'] == view.get('selected')
        d.rounded_rectangle([r.x0, r.y0, r.x1, r.y1], radius=8, fill=SEL_BG if sel else ROW_BG,
                            outline=BLUE if sel else (215, 218, 225), width=3 if sel else 1)
        d.text((r.x0 + 12, r.y0 + 8), str(item['id']), font=gr.font(26, True),
               fill=BLUE if sel else DARK)
        d.text((r.x0 + 56, r.y0 + 6), item.get('name', item['id']), font=gr.font(16, True),
               fill=DARK)
        text, colour = station_line(item)
        d.text((r.x0 + 56, r.y0 + 28), text, font=gr.font(14), fill=colour)
        aliases = ', '.join(item.get('aliases', []))
        if aliases and r.y1 - r.y0 > 56:
            line = gr.wrap(d, 'gọi là: ' + aliases, gr.font(12), r.x1 - r.x0 - 70)[0]
            d.text((r.x0 + 56, r.y0 + 46), line, font=gr.font(12), fill=GREY)

    sel = view.get('selected')
    save_ok = bool(sel) and view.get('robot_ok')
    _button(d, rects['save_pose'], f'Lưu vị trí robot cho trạm {sel or "?"}   [Space]',
            GREEN if save_ok else (170, 175, 185), size=18)
    _button(d, rects['pick'], 'Đang chọn trên map...' if view.get('pick_mode')
            else 'Chọn trên map  [P]', AMBER if view.get('pick_mode') else BLUE, size=15)
    _button(d, rects['clear'], 'Xóa vị trí  [Del]', (150, 60, 60), size=15)
    _button(d, rects['save_map'], 'Đang lưu map...' if view.get('saving_map')
            else f"Lưu map → {_fit(d, view.get('map_target', '~/maps/lab'))}  [M]",
            (90, 90, 90) if view.get('saving_map') else gr.TITLE_BG, size=15)

    y = rects['save_map'].y1 + 14
    msg = view.get('message') or ''
    for line in gr.wrap(d, msg, gr.font(15, True), PANEL_W - 30)[:3]:
        d.text((16, y), line, font=gr.font(15, True), fill=view.get('message_colour', DARK))
        y += 20
    d.text((16, PANEL_H - 24), 'Chọn trạm: bấm vào dòng hoặc phím A-D  |  Q: thoát',
           font=gr.font(13), fill=GREY)
    return img, rects


def render_right(mapview, stations, robot, selected, preview=None, note=None):
    """mapview: gr.MapView of the live map (or a plan grid). preview: (x, y, yaw) being
    placed with the mouse."""
    if mapview is None:
        img = Image.new('RGB', (MAP_W, PANEL_H), (250, 251, 253))
        d = ImageDraw.Draw(img)
        gr.center(d, 'Chưa có map', PANEL_H // 2 - 30, gr.font(20, True), GREY, MAP_W)
        gr.center(d, 'Chạy SLAM (slam.launch.py) hoặc localization để có /map',
                  PANEL_H // 2 + 4, gr.font(15), GREY, MAP_W)
        return img
    legend = ((BLUE, 'robot'), ((30, 110, 220), 'trạm'), (GREEN, 'trạm đang chọn'),
              (AMBER, 'vị trí đang đặt'))
    img = gr.render_map_panel(mapview, stations, robot, None, selected, legend=legend)
    d = ImageDraw.Draw(img)
    if preview is not None:
        px, py = mapview.to_px(preview[0], preview[1])
        d.ellipse([px - 11, py - 11, px + 11, py + 11], outline=AMBER, width=3)
        gr._arrow(d, px, py, preview[2], 26, AMBER, width=3)
    if note:
        d.rectangle([0, 0, img.size[0], 26], fill=(255, 244, 214))
        d.text((8, 4), note, font=gr.font(14, True), fill=AMBER)
    return img


def compose(left, right):
    return gr.compose(left, right)
