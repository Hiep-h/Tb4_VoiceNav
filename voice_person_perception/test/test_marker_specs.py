import math

from voice_person_perception.marker_specs import marker_specs


def test_arrow_and_label_per_destination_with_pose():
    data = {'destinations': [
        {'id': 'bep', 'name': 'bếp', 'pose': {'x': 1.5, 'y': -0.25, 'yaw': 1.571}},
        {'id': 'phong_khach', 'name': 'phòng khách'},
        {'id': 'kho', 'pose': {'x': 0, 'y': 2}},
    ]}
    specs, missing = marker_specs(data)
    assert missing == ['phong_khach']
    assert [(s['ns'], s['id']) for s in specs] == [
        ('arrow', 0), ('label', 0), ('arrow', 2), ('label', 2)]
    arrow, label = specs[0], specs[1]
    assert (arrow['x'], arrow['y']) == (1.5, -0.25)
    assert math.isclose(arrow['yaw'], 1.571)
    assert label['text'] == 'bếp (bep)'
    assert specs[3]['text'] == 'kho' and specs[2]['yaw'] == 0.0


def test_empty_file():
    assert marker_specs({}) == ([], [])
