"""Drawing for voice_gui (no ROS): mic button panel, map panel, radar panel.

Everything is drawn with PIL so Vietnamese text keeps its accents, then
converted to a BGR numpy image for cv2.imshow.
"""

from __future__ import annotations

import math
import os

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

from voice_person_perception import contract

PANEL_W = 460
PANEL_H = 620
BG = (245, 247, 250)
TITLE_BG = (31, 47, 153)
BTN_CX, BTN_CY, BTN_R = PANEL_W // 2, 190, 78
GREY, DARK, BLUE = (120, 120, 120), (40, 40, 40), (31, 47, 153)
GREEN, AMBER, RED = (27, 130, 60), (200, 120, 0), (200, 40, 40)

FONT_PATHS = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans{b}.ttf',
    '/usr/share/fonts/TTF/DejaVuSans{b}.ttf',
    '/usr/share/fonts/truetype/noto/NotoSans-{nb}.ttf',
)
_FONTS = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _FONTS:
        _FONTS[key] = None
        for path in FONT_PATHS:
            p = path.format(b='-Bold' if bold else '', nb='Bold' if bold else 'Regular')
            if os.path.exists(p):
                _FONTS[key] = ImageFont.truetype(p, size)
                break
        if _FONTS[key] is None:
            _FONTS[key] = ImageFont.load_default()
    return _FONTS[key]


def to_bgr(img):
    return np.ascontiguousarray(np.array(img.convert('RGB'))[:, :, ::-1])


def text_w(draw, text, f):
    box = draw.textbbox((0, 0), text, font=f)
    return box[2] - box[0]


def wrap(draw, text, f, max_w):
    lines, cur = [], ''
    for word in text.split():
        trial = (cur + ' ' + word).strip()
        if cur and text_w(draw, trial, f) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def center(draw, text, y, f, fill, width=PANEL_W):
    draw.text(((width - text_w(draw, text, f)) / 2, y), text, font=f, fill=fill)


# ---------------------------------------------------------------- text helpers

BUTTON_LOOK = {
    # state: (button colour, line under the button, colour of that line)
    contract.ASR_IDLE: ((140, 140, 140), 'Bấm để nói', DARK),
    contract.ASR_LISTENING: (RED, 'Đang nghe... hãy nói', RED),
    contract.ASR_SPEECH: (RED, 'Đang nghe... bấm lần nữa để gửi', RED),
    contract.ASR_RECOGNIZING: (AMBER, 'Đang nhận dạng...', AMBER),
    contract.ASR_CALIBRATING: ((150, 150, 150), 'Giữ im lặng, đang đo tiếng ồn', GREY),
    contract.ASR_MUTED: ((90, 90, 90), 'Mic tạm tắt (robot đang nói)', GREY),
    None: ((200, 200, 200), 'Chưa thấy asr_node', GREY),
}


def describe_command(cmd, names=None):
    """(text, colour) for a /voice/intent dict; names maps station id -> spoken name."""
    if not cmd:
        return 'Chưa có lệnh', GREY
    names = names or {}
    intent = cmd.get('intent')
    src, dst = cmd.get('source_station'), cmd.get('destination_station')
    src_name, dst_name = names.get(src, src), names.get(dst, dst)
    ask = cmd.get('needs_confirm')
    if intent == contract.INTENT_CREATE_DELIVERY:
        if dst is None:
            return f'Lấy hàng ở {src_name}, giao đến đâu? Cần xác nhận', AMBER
        route = f'{src_name} → {dst_name}' if src else f'đến {dst_name}'
        if ask:
            others = [names.get(c.get('station'), c.get('station'))
                      for c in cmd.get('candidates', [])
                      if isinstance(c, dict) and c.get('station') not in (None, src, dst)][:2]
            extra = f" (hoặc {', '.join(others)}?)" if others else ''
            return f'Giao hàng {route}? Cần xác nhận{extra}', AMBER
        return f'Giao hàng {route}', GREEN
    if intent == contract.INTENT_CHANGE_DESTINATION:
        return (f'Đổi đích sang {dst_name}' + ('? Cần xác nhận' if ask else ''),
                AMBER if ask else GREEN)
    if intent == contract.INTENT_PAUSE:
        return 'TẠM DỪNG', RED
    if intent == contract.INTENT_RESUME:
        return 'Tiếp tục', GREEN
    if intent == contract.INTENT_CANCEL:
        return 'Hủy đơn', AMBER
    if intent == contract.INTENT_GET_STATUS:
        return 'Hỏi trạng thái đơn hàng', BLUE
    return 'Không hiểu lệnh (không có trạm này?)', GREY


def side(bearing):
    if abs(bearing) < 8:
        return 'phía trước'
    return f"bên {'trái' if bearing > 0 else 'phải'} {abs(bearing):.0f}°"


def describe_persons(msg, age_s=None, stale_s=1.5):
    """(text, colour) summary of a /person_detections dict."""
    if msg is None:
        return 'Camera: chưa có dữ liệu', GREY
    if (age_s is not None and age_s > stale_s) or not msg.get('healthy', False):
        return 'Camera: mất tín hiệu', RED
    persons = [p for p in msg.get('persons', []) if p.get('distance_m') is not None]
    if not persons:
        n = len(msg.get('persons', []))
        return ('Không có ai phía trước' if n == 0
                else f'{n} người (chưa đo được khoảng cách)'), GREEN
    near = min(persons, key=lambda p: p['distance_m'])
    text = f"{len(persons)} người, gần nhất {near['distance_m']:.1f} m {side(near['bearing_deg'])}"
    if near.get('approaching'):
        text += ', đang tiến lại'
    colour = RED if near['distance_m'] < 1.0 else AMBER if near['distance_m'] < 2.0 else GREEN
    return text, colour


def backend_line(status):
    if not status:
        return ''
    line = f"Nhận dạng: {status.get('backend', '?')}"
    if status.get('fallback'):
        ready = status.get('backup_ready')
        line += f", dự phòng {status['fallback']} ({'sẵn sàng' if ready else 'đang tải'})"
    if status.get('push_to_talk'):
        line += ' | bấm để nói'
    return line


NAV_REASONS = {
    'UNKNOWN_STATION': 'không có trạm này',
    'NO_POSE': 'trạm chưa đánh dấu trên map',
    'NAV2_UNAVAILABLE': 'Nav2 chưa chạy',
    'GOAL_REJECTED': 'Nav2 từ chối',
    'NAV2_ABORTED': 'bị chặn hoặc không tìm được đường',
    'TIMEOUT': 'đi quá lâu',
}


def describe_nav(nav, names=None, age_s=None, stale_s=3.0):
    """(text, colour) for a /navigation/status dict, or None when no client runs."""
    if nav is None:
        return None
    if age_s is not None and age_s > stale_s:
        return 'Robot: mất kết nối Navigation Client', RED
    names = names or {}
    station = nav.get('station_id')
    name = names.get(station, station or '?')
    state = nav.get('state')
    if state == 'MOVING':
        text = f'Robot: đang đến {name}'
        if nav.get('distance_remaining_m') is not None:
            text += f", còn {nav['distance_remaining_m']:.1f} m"
            if nav.get('eta_s'):
                text += f" (~{nav['eta_s']:.0f} s)"
        return text, BLUE
    if state == 'SUCCEEDED':
        return f'Robot: đã tới {name}', GREEN
    if state == 'CANCELED':
        return f'Robot: đã hủy đường đến {name}', AMBER
    if state == 'FAILED':
        reason = NAV_REASONS.get(nav.get('reason'), nav.get('reason') or 'lỗi')
        return f'Robot: không tới được {name} ({reason})', RED
    return 'Robot: đang chờ lệnh', GREY


# ---------------------------------------------------------------- left panel

def render_voice_panel(view, t=0.0, height=PANEL_H):
    """view: dict with status, heard, command, names, persons, persons_age."""
    img = Image.new('RGB', (PANEL_W, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, PANEL_W, 56], fill=TITLE_BG)
    d.text((14, 14), 'Robot giao đồ: ra lệnh bằng giọng nói', font=font(20, True),
           fill=(255, 255, 255))

    status = view.get('status')
    state = status.get('state') if status else None
    colour, label, label_colour = BUTTON_LOOK.get(state, BUTTON_LOOK[None])
    r = BTN_R
    if state in (contract.ASR_LISTENING, contract.ASR_SPEECH):
        r = int(BTN_R * (0.9 + 0.1 * math.sin(t * 6)))
        halo = BTN_R + 14
        d.ellipse([BTN_CX - halo, BTN_CY - halo, BTN_CX + halo, BTN_CY + halo],
                  outline=(240, 170, 170), width=4)
    d.ellipse([BTN_CX - r, BTN_CY - r, BTN_CX + r, BTN_CY + r], fill=colour)
    _draw_mic(d, BTN_CX, BTN_CY)
    if state == contract.ASR_LISTENING and status and not status.get('push_to_talk'):
        label = 'Đang nghe (nói bất cứ lúc nào)'
    center(d, label, BTN_CY + BTN_R + 22, font(20, True), label_colour)

    # microphone level vs speech threshold
    y = BTN_CY + BTN_R + 54
    if status:
        top = max(status.get('threshold', 1.0) * 2.5, 1.0)
        x0, x1 = 60, PANEL_W - 60
        d.rectangle([x0, y, x1, y + 10], fill=(225, 228, 235))
        lvl = min(status.get('level', 0.0) / top, 1.0)
        d.rectangle([x0, y, x0 + (x1 - x0) * lvl, y + 10],
                    fill=RED if status.get('level', 0) > status.get('threshold', 0) else GREY)
        tx = x0 + (x1 - x0) * min(status.get('threshold', 0) / top, 1.0)
        d.line([tx, y - 4, tx, y + 14], fill=DARK, width=2)
    y += 30

    heard = view.get('heard')
    d.text((20, y), 'Bạn đã nói:', font=font(17), fill=GREY)
    y += 24
    text = f"“{heard['text']}”" if heard else '-'
    for line in wrap(d, text, font(22, True), PANEL_W - 40)[:3]:
        d.text((20, y), line, font=font(22, True), fill=BLUE)
        y += 28
    if heard and heard.get('latency_s') is not None:
        info = []
        if heard.get('engine'):
            info.append(heard['engine'])
        if heard.get('audio_s') is not None:
            info.append(f"câu dài {heard['audio_s']:.1f} s")
        info.append(f"nhận dạng {heard['latency_s']:.1f} s")
        info.append(f"tin cậy {heard.get('asr_conf', 0):.2f}")
        d.text((20, y), ', '.join(info), font=font(14), fill=GREY)
        y += 20
    y += 8
    d.text((20, y), 'Robot hiểu:', font=font(17), fill=GREY)
    y += 24
    cmd_text, cmd_colour = describe_command(view.get('command'), view.get('names'))
    for line in wrap(d, cmd_text, font(22, True), PANEL_W - 40)[:2]:
        d.text((20, y), line, font=font(22, True), fill=cmd_colour)
        y += 28

    nav = describe_nav(view.get('nav'), view.get('names'), view.get('nav_age'))
    if nav is not None:
        ny = max(y + 6, height - 124)
        d.text((20, ny), wrap(d, nav[0], font(17, True), PANEL_W - 40)[0],
               font=font(17, True), fill=nav[1])
        y = ny + 24
    y = max(y + 10, height - 92)
    d.line([16, y, PANEL_W - 16, y], fill=(215, 218, 225), width=1)
    p_text, p_colour = describe_persons(view.get('persons'), view.get('persons_age'))
    for line in wrap(d, 'Người: ' + p_text, font(17, True), PANEL_W - 40)[:2]:
        d.text((20, y + 10), line, font=font(17, True), fill=p_colour)
        y += 22
    footer = backend_line(status) or 'Phím: Space = nói/dừng, Q = thoát'
    d.text((20, height - 26), footer, font=font(13), fill=GREY)
    return img


def _draw_mic(d, cx, cy):
    white = (255, 255, 255)
    d.rounded_rectangle([cx - 14, cy - 38, cx + 14, cy + 6], radius=14, fill=white)
    d.arc([cx - 26, cy - 22, cx + 26, cy + 22], 0, 180, fill=white, width=5)
    d.line([cx, cy + 22, cx, cy + 34], fill=white, width=5)
    d.line([cx - 14, cy + 36, cx + 14, cy + 36], fill=white, width=5)


def inside_button(x, y):
    return (x - BTN_CX) ** 2 + (y - BTN_CY) ** 2 <= (BTN_R + 14) ** 2


# ---------------------------------------------------------------- map panel

def load_map(yaml_path):
    """(PIL grayscale image, resolution, (origin_x, origin_y)) of a map_saver map."""
    with open(yaml_path, encoding='utf-8') as f:
        meta = yaml.safe_load(f)
    image = meta['image']
    if not os.path.isabs(image):
        image = os.path.join(os.path.dirname(os.path.abspath(yaml_path)), image)
    img = Image.open(image).convert('L')
    if meta.get('negate', 0):
        img = Image.eval(img, lambda v: 255 - v)
    origin = meta.get('origin', [0.0, 0.0, 0.0])
    return img, float(meta['resolution']), (float(origin[0]), float(origin[1]))


class MapView:
    def __init__(self, image, resolution, origin, max_w=700, max_h=PANEL_H):
        self.res, self.origin = resolution, origin
        self.w, self.h = image.size
        self.scale = min(max_w / self.w, max_h / self.h)
        size = (max(1, int(self.w * self.scale)), max(1, int(self.h * self.scale)))
        self.base = image.convert('RGB').resize(size, Image.NEAREST)

    def to_px(self, x, y):
        px = (x - self.origin[0]) / self.res * self.scale
        py = (self.h - (y - self.origin[1]) / self.res) * self.scale
        return px, py


def person_world(robot, person):
    """Map position of a person seen at (distance, bearing) from robot (x, y, yaw)."""
    x, y, yaw = robot
    ang = yaw + math.radians(person['bearing_deg'])
    return x + person['distance_m'] * math.cos(ang), y + person['distance_m'] * math.sin(ang)


def _arrow(d, px, py, yaw, length, colour, width=3):
    ex, ey = px + length * math.cos(yaw), py - length * math.sin(yaw)
    d.line([px, py, ex, ey], fill=colour, width=width)
    for da in (2.6, -2.6):
        d.line([ex, ey, ex + 8 * math.cos(yaw + da), ey - 8 * math.sin(yaw + da)],
               fill=colour, width=width)


def render_map_panel(mapview, destinations, robot=None, persons=None, target=None):
    img = mapview.base.copy()
    d = ImageDraw.Draw(img)
    for item in destinations:
        pose = item.get('pose')
        if not pose:
            continue
        px, py = mapview.to_px(pose['x'], pose['y'])
        hot = item['id'] == target
        colour = GREEN if hot else (30, 110, 220)
        r = 9 if hot else 6
        d.ellipse([px - r, py - r, px + r, py + r], fill=colour)
        _arrow(d, px, py, pose.get('yaw', 0.0), 20 if hot else 14, colour)
        d.text((px + 10, py - 22), item.get('name', item['id']),
               font=font(15 if hot else 13, hot), fill=colour)
    if robot is not None:
        if persons:
            for p in persons:
                if p.get('distance_m') is None:
                    continue
                qx, qy = mapview.to_px(*person_world(robot, p))
                c = RED if p.get('approaching') or p['distance_m'] < 1.0 else (240, 130, 30)
                rx, ry = mapview.to_px(robot[0], robot[1])
                d.line([rx, ry, qx, qy], fill=c, width=1)
                d.ellipse([qx - 8, qy - 8, qx + 8, qy + 8], fill=c, outline=(255, 255, 255))
                label = f"{p['distance_m']:.1f} m" + (' ←' if p.get('approaching') else '')
                d.text((qx + 10, qy - 9), label, font=font(14, True), fill=c)
        px, py = mapview.to_px(robot[0], robot[1])
        d.ellipse([px - 10, py - 10, px + 10, py + 10], fill=BLUE, outline=(255, 255, 255))
        _arrow(d, px, py, robot[2], 22, BLUE)
    else:
        d.text((10, 8), 'Chưa có vị trí robot (cần SLAM/AMCL)', font=font(14, True), fill=RED)
    return _with_legend(img)


def _with_legend(img):
    """Map image plus a strip below it explaining the symbols."""
    out = Image.new('RGB', (img.size[0], max(img.size[1] + 34, PANEL_H)), BG)
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    y = img.size[1] + 10
    x = 12
    for colour, label in ((BLUE, 'robot'), ((30, 110, 220), 'trạm'),
                          (GREEN, 'đang tới'), ((240, 130, 30), 'người'),
                          (RED, 'người đang tiến lại')):
        d.ellipse([x, y + 3, x + 12, y + 15], fill=colour)
        d.text((x + 17, y), label, font=font(13), fill=DARK)
        x += 30 + text_w(d, label, font(13))
    return out


def plan_view(destinations, robot=None, margin_m=1.5, res=0.02, max_w=700, max_h=PANEL_H - 40):
    """A MapView over an empty grid that fits every station (and the robot),
    for when there is no saved map yet (e.g. with the fake Nav2 server).
    None when no station has a pose."""
    pts = [(i['pose']['x'], i['pose']['y']) for i in destinations if i.get('pose')]
    if not pts:
        return None
    if robot is not None:
        pts.append((robot[0], robot[1]))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = min(xs) - margin_m, min(ys) - margin_m
    w_m = max(max(xs) - x0 + margin_m, 3.0)
    h_m = max(max(ys) - y0 + margin_m, 3.0)
    size = (max(1, int(w_m / res)), max(1, int(h_m / res)))
    mv = MapView(Image.new('L', size, 252), res, (x0, y0), max_w=max_w, max_h=max_h)
    d = ImageDraw.Draw(mv.base)
    for gx in range(math.ceil(x0), math.floor(x0 + w_m) + 1):
        px, _ = mv.to_px(gx, 0)
        d.line([px, 0, px, mv.base.size[1]], fill=(225, 228, 235) if gx else (190, 195, 205))
    for gy in range(math.ceil(y0), math.floor(y0 + h_m) + 1):
        _, py = mv.to_px(0, gy)
        d.line([0, py, mv.base.size[0], py], fill=(225, 228, 235) if gy else (190, 195, 205))
    d.text((8, mv.base.size[1] - 20), 'Sơ đồ trạm (chưa có map), ô lưới 1 m',
           font=font(13), fill=GREY)
    return mv


# ---------------------------------------------------------------- radar panel

RADAR_W = 460
RADAR_RANGE_M = 3.0
RADAR_TOP = 64  # pixels kept free for the title


def _radar_geometry(size=RADAR_W, range_m=RADAR_RANGE_M):
    cx, cy = size / 2, size - 40
    return cx, cy, (cy - RADAR_TOP) / range_m


def radar_px(person, size=RADAR_W, range_m=RADAR_RANGE_M):
    """Screen position of a person: robot at bottom centre facing up, left = +bearing."""
    cx, cy, k = _radar_geometry(size, range_m)
    ang = math.radians(person['bearing_deg'])
    dist = min(person['distance_m'], range_m)
    return cx - dist * math.sin(ang) * k, cy - dist * math.cos(ang) * k


def render_radar_panel(persons_msg, destinations=(), target=None, height=PANEL_H):
    img = Image.new('RGB', (RADAR_W, height), (250, 251, 253))
    d = ImageDraw.Draw(img)
    d.text((14, 10), 'Người quanh robot (camera)', font=font(17, True), fill=DARK)
    cx, cy, k = _radar_geometry()
    for dist in (0.5, 1.0, 2.0, 3.0):
        r = dist * k
        colour = (240, 200, 200) if dist <= 1.0 else (220, 224, 232)
        d.arc([cx - r, cy - r, cx + r, cy + r], 180 + 55, 360 - 55, fill=colour, width=2)
        d.text((cx + 4, cy - r - 16), f'{dist:g} m', font=font(12), fill=GREY)
    for a in (-34.5, 34.5):  # camera field of view
        ang = math.radians(a)
        d.line([cx, cy, cx - 3.0 * k * math.sin(ang), cy - 3.0 * k * math.cos(ang)],
               fill=(225, 228, 235), width=1)
    d.polygon([(cx, cy - 16), (cx - 12, cy + 10), (cx + 12, cy + 10)], fill=BLUE)
    for p in (persons_msg or {}).get('persons', []):
        if p.get('distance_m') is None:
            continue
        px, py = radar_px(p)
        c = RED if p.get('approaching') else (240, 130, 30)
        d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=c, outline=(255, 255, 255))
        d.text((px + 11, py - 8), f"{p['distance_m']:.1f} m", font=font(13, True), fill=c)
    y = RADAR_W + 6
    d.text((14, y), 'Trạm:', font=font(15, True), fill=DARK)
    y += 22
    names = [(i['id'], i.get('name', i['id'])) for i in destinations]
    line = ''
    for dest_id, name in names:
        trial = (line + ' · ' + name) if line else name
        if text_w(d, trial, font(14)) > RADAR_W - 28:
            d.text((14, y), line, font=font(14), fill=GREY)
            y += 20
            line = name
        else:
            line = trial
    if line and y < height - 20:
        d.text((14, y), line, font=font(14), fill=GREY)
    if target:
        tname = dict(names).get(target, target)
        d.text((14, height - 24), f'Đang hướng tới: {tname}', font=font(14, True), fill=GREEN)
    return img


def compose(left, right):
    h = max(left.size[1], right.size[1] if right is not None else 0)
    w = left.size[0] + (right.size[0] if right is not None else 0)
    out = Image.new('RGB', (w, h), BG)
    out.paste(left, (0, 0))
    if right is not None:
        out.paste(right, (left.size[0], 0))
    return out
