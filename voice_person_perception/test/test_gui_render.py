import math

import pytest
import yaml
from PIL import Image

from voice_person_perception import contract
from voice_person_perception import gui_render as gr

NAMES = {'A': 'trạm A', 'B': 'trạm B', 'C': 'trạm C'}


def test_describe_command():
    assert gr.describe_command(None) == ('Chưa có lệnh', gr.GREY)
    go = {'intent': 'CREATE_DELIVERY', 'source_station': 'A', 'destination_station': 'B',
          'needs_confirm': False}
    assert gr.describe_command(go, NAMES) == ('Giao hàng trạm A → trạm B', gr.GREEN)
    to_b = dict(go, source_station=None)
    assert gr.describe_command(to_b, NAMES) == ('Giao hàng đến trạm B', gr.GREEN)
    ask = {'intent': 'CREATE_DELIVERY', 'source_station': None, 'destination_station': 'B',
           'needs_confirm': True,
           'candidates': [{'station': 'B', 'score': 0.9}, {'station': 'C', 'score': 0.6}]}
    text, colour = gr.describe_command(ask, NAMES)
    assert 'trạm B?' in text and 'trạm C' in text and colour == gr.AMBER
    no_dst = dict(go, destination_station=None, needs_confirm=True)
    assert 'giao đến đâu' in gr.describe_command(no_dst, NAMES)[0]
    change = {'intent': 'CHANGE_DESTINATION', 'destination_station': 'C'}
    assert gr.describe_command(change, NAMES) == ('Đổi đích sang trạm C', gr.GREEN)
    assert gr.describe_command({'intent': 'PAUSE'})[1] == gr.RED
    assert gr.describe_command({'intent': 'RESUME'})[1] == gr.GREEN
    assert gr.describe_command({'intent': 'CANCEL'})[0] == 'Hủy đơn'
    assert gr.describe_command({'intent': 'GET_STATUS'})[1] == gr.BLUE
    assert gr.describe_command({'intent': 'UNKNOWN'})[0].startswith('Không hiểu')


def test_describe_persons():
    assert gr.describe_persons(None)[0] == 'Camera: chưa có dữ liệu'
    assert gr.describe_persons({'healthy': False, 'persons': []})[1] == gr.RED
    assert gr.describe_persons({'healthy': True, 'persons': []}, age_s=5)[1] == gr.RED
    assert gr.describe_persons({'healthy': True, 'persons': []})[0] == 'Không có ai phía trước'
    msg = {'healthy': True, 'persons': [
        {'distance_m': 2.5, 'bearing_deg': -30.0, 'approaching': False},
        {'distance_m': 0.8, 'bearing_deg': 20.0, 'approaching': True}]}
    text, colour = gr.describe_persons(msg, age_s=0.1)
    assert text == '2 người, gần nhất 0.8 m bên trái 20°, đang tiến lại'
    assert colour == gr.RED


def test_side():
    assert gr.side(3) == 'phía trước'
    assert gr.side(-25) == 'bên phải 25°'


def test_person_world_and_radar_follow_left_positive_bearing():
    # Robot at origin facing +y; person 1 m at +90° (left) is at -x.
    x, y = gr.person_world((0.0, 0.0, math.pi / 2), {'distance_m': 1.0, 'bearing_deg': 90})
    assert (x, y) == pytest.approx((-1.0, 0.0))
    px_left, _ = gr.radar_px({'distance_m': 1.0, 'bearing_deg': 20})
    px_right, _ = gr.radar_px({'distance_m': 1.0, 'bearing_deg': -20})
    assert px_left < gr.RADAR_W / 2 < px_right
    _, py_near = gr.radar_px({'distance_m': 0.5, 'bearing_deg': 0})
    _, py_far = gr.radar_px({'distance_m': 3.0, 'bearing_deg': 0})
    assert py_far >= gr.RADAR_TOP and py_far < py_near


def test_map_view_pixels(tmp_path):
    Image.new('L', (200, 100), 254).save(tmp_path / 'm.pgm')
    (tmp_path / 'm.yaml').write_text(yaml.safe_dump(
        {'image': 'm.pgm', 'resolution': 0.05, 'origin': [-1.0, -2.0, 0.0], 'negate': 0}))
    img, res, origin = gr.load_map(str(tmp_path / 'm.yaml'))
    mv = gr.MapView(img, res, origin, max_w=400, max_h=400)
    assert mv.scale == 2.0
    assert mv.to_px(-1.0, -2.0) == pytest.approx((0.0, 200.0))  # origin = bottom-left
    assert mv.to_px(9.0, 3.0) == pytest.approx((400.0, 0.0))


@pytest.mark.parametrize('state', [None, contract.ASR_IDLE, contract.ASR_LISTENING,
                                   contract.ASR_SPEECH, contract.ASR_RECOGNIZING,
                                   contract.ASR_CALIBRATING, contract.ASR_MUTED])
def test_panels_render_every_state(state, tmp_path):
    status = None if state is None else {
        'state': state, 'level': 500, 'threshold': 300, 'backend': 'google',
        'fallback': 'whisper', 'backup_ready': False, 'push_to_talk': True}
    view = {'status': status, 'heard': {'text': 'mang đồ đến bếp', 'latency_s': 1.0,
                                        'asr_conf': 0.9},
            'command': {'intent': 'CREATE_DELIVERY', 'source_station': 'A',
                        'destination_station': 'B'}, 'names': NAMES,
            'persons': {'healthy': True, 'persons': []}, 'persons_age': 0.1}
    left = gr.render_voice_panel(view, t=1.0)
    dests = [{'id': 'bep', 'name': 'bếp', 'pose': {'x': 0.5, 'y': 0.5, 'yaw': 0.0}},
             {'id': 'kho', 'name': 'kho'}]
    right = gr.render_radar_panel({'persons': [{'distance_m': 1.0, 'bearing_deg': 0}]},
                                  dests, 'bep')
    frame = gr.to_bgr(gr.compose(left, right))
    assert frame.shape == (gr.PANEL_H, gr.PANEL_W + gr.RADAR_W, 3)

    Image.new('L', (100, 80), 254).save(tmp_path / 'm.pgm')
    mv = gr.MapView(Image.open(tmp_path / 'm.pgm'), 0.05, (0.0, 0.0))
    for robot in (None, (1.0, 1.0, 0.5)):
        img = gr.render_map_panel(mv, dests, robot, [{'distance_m': 1.0, 'bearing_deg': 10,
                                                      'approaching': True}], 'bep')
        assert img.size[1] >= gr.PANEL_H


def test_inside_button():
    assert gr.inside_button(gr.BTN_CX, gr.BTN_CY)
    assert not gr.inside_button(0, 0)


def test_describe_nav():
    assert gr.describe_nav(None) is None
    moving = {'state': 'MOVING', 'station_id': 'B', 'distance_remaining_m': 1.84, 'eta_s': 4.2}
    assert gr.describe_nav(moving, NAMES) == ('Robot: đang đến trạm B, còn 1.8 m (~4 s)', gr.BLUE)
    assert gr.describe_nav({'state': 'SUCCEEDED', 'station_id': 'B'}, NAMES)[1] == gr.GREEN
    failed = {'state': 'FAILED', 'station_id': 'C', 'reason': 'NAV2_UNAVAILABLE'}
    assert gr.describe_nav(failed, NAMES) == ('Robot: không tới được trạm C (Nav2 chưa chạy)',
                                              gr.RED)
    assert gr.describe_nav({'state': 'IDLE'})[0] == 'Robot: đang chờ lệnh'
    assert gr.describe_nav(moving, NAMES, age_s=10)[0].endswith('mất kết nối Navigation Client')


def test_plan_view_fits_stations_and_robot():
    dests = [{'id': 'A', 'pose': {'x': 0.0, 'y': 0.0, 'yaw': 0.0}},
             {'id': 'B', 'pose': {'x': 4.0, 'y': 2.0, 'yaw': 0.0}},
             {'id': 'C'}]
    assert gr.plan_view([{'id': 'C'}]) is None
    mv = gr.plan_view(dests, robot=(-3.0, 5.0, 0.0))
    w, h = mv.base.size
    for x, y in ((0.0, 0.0), (4.0, 2.0), (-3.0, 5.0)):
        px, py = mv.to_px(x, y)
        assert 0 < px < w and 0 < py < h
    img = gr.render_map_panel(mv, dests, (1.0, 1.0, 0.3), [], 'B')
    assert img.size[1] >= gr.PANEL_H
