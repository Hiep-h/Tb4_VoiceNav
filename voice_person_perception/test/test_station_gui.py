import math

import numpy as np
import pytest

from voice_person_perception import gui_render as gr
from voice_person_perception import station_gui as sg

STATIONS = [
    {'id': 'A', 'name': 'trạm A', 'aliases': ['cửa lab'],
     'pose': {'x': 0.4, 'y': 0.1, 'yaw': 0.0}},
    {'id': 'B', 'name': 'trạm B', 'aliases': []},
    {'id': 'C', 'name': 'trạm C'},
    {'id': 'D', 'name': 'trạm D'},
]


def test_layout_rows_and_buttons_do_not_overlap():
    rects = sg.layout(['A', 'B', 'C', 'D'])
    order = ['station:A', 'station:B', 'station:C', 'station:D', 'save_pose', 'save_map']
    for upper, lower in zip(order, order[1:]):
        assert rects[upper].y1 < rects[lower].y0
    assert rects['pick'].x1 < rects['clear'].x0
    assert all(r.y1 < sg.PANEL_H - 60 for r in rects.values())


def test_layout_many_stations_still_fits():
    rects = sg.layout([str(i) for i in range(8)])
    assert rects['save_map'].y1 < sg.PANEL_H - 60


def test_hit():
    rects = sg.layout(['A', 'B'])
    r = rects['station:B']
    assert sg.hit(rects, (r.x0 + r.x1) // 2, (r.y0 + r.y1) // 2) == 'station:B'
    assert sg.hit(rects, rects['save_pose'].x0 + 5, rects['save_pose'].y0 + 5) == 'save_pose'
    assert sg.hit(rects, 1, 1) is None


def test_occupancy_to_image_orientation_and_colours():
    w, h = 4, 3
    data = [-1] * (w * h)
    data[0] = 100      # row 0 = bottom-left in the grid
    data[w * h - 1] = 0  # top-right
    img = np.array(sg.occupancy_to_image(data, w, h))
    assert img.shape == (3, 4)
    assert img[2, 0] == 0      # bottom-left in the image
    assert img[0, 3] == 254    # top-right free
    assert img[1, 1] == 205    # unknown


def test_map_view_round_trip():
    from PIL import Image
    mv = gr.MapView(Image.new('L', (200, 100)), 0.05, (-1.0, -2.0), max_w=400, max_h=400)
    for x, y in ((0.0, 0.0), (3.5, 1.25), (-1.0, -2.0)):
        assert mv.to_world(*mv.to_px(x, y)) == pytest.approx((x, y))


def test_drag_yaw():
    assert sg.drag_yaw((1.0, 1.0), (1.05, 1.0)) is None          # a click
    assert sg.drag_yaw((0.0, 0.0), (0.0, 1.0)) == pytest.approx(math.pi / 2)
    assert sg.drag_yaw((0.0, 0.0), (-1.0, 0.0)) == pytest.approx(math.pi)


def test_station_line():
    assert sg.station_line(STATIONS[0]) == ('✓ x=0.40  y=0.10  hướng 0°', gr.GREEN)
    assert sg.station_line(STATIONS[1]) == ('chưa đánh dấu', gr.RED)


@pytest.mark.parametrize('pick, saving', [(False, False), (True, True)])
def test_render(pick, saving):
    left, rects = sg.render_left({'stations': STATIONS, 'selected': 'B', 'robot_ok': True,
                                  'pick_mode': pick, 'saving_map': saving,
                                  'message': 'Đã lưu trạm A', 'message_colour': gr.GREEN,
                                  'map_target': '~/maps/' + 'x' * 80})
    assert left.size == (sg.PANEL_W, sg.PANEL_H) and 'save_pose' in rects
    grid = sg.occupancy_to_image([0] * 100 * 80, 100, 80)
    mv = gr.MapView(grid, 0.05, (0.0, 0.0), max_w=sg.MAP_W, max_h=sg.PANEL_H - 34)
    right = sg.render_right(mv, STATIONS, (1.0, 1.0, 0.3), 'B', preview=(2.0, 2.0, 1.0),
                            note='Bấm vào map')
    assert right.size[1] >= sg.PANEL_H
    assert sg.render_right(None, STATIONS, None, 'B').size == (sg.MAP_W, sg.PANEL_H)
    frame = gr.to_bgr(sg.compose(left, right))
    assert frame.shape[1] == sg.PANEL_W + right.size[0]
