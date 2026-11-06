import json
from types import SimpleNamespace

import numpy as np
import pytest

from voice_person_perception import contract
from voice_person_perception.person_math import (
    PersonSmoother,
    bearing_deg,
    depth_median_m,
    fx_from_hfov,
    scale_bbox,
)
from voice_person_perception.ros_image import image_to_numpy


def test_bearing_sign_left_positive():
    fx = fx_from_hfov(640, 69.0)
    assert bearing_deg(320, 320, fx) == pytest.approx(0.0)
    assert bearing_deg(100, 320, fx) > 0      # person on the left of the image
    assert bearing_deg(540, 320, fx) < 0
    assert bearing_deg(640, 320, fx) == pytest.approx(-34.5, abs=0.1)


def test_depth_median_ignores_invalid_pixels():
    depth = np.zeros((100, 100), dtype=np.uint16)
    depth[40:60, 40:60] = 2000
    depth[50, 50] = 0
    assert depth_median_m(depth, (30, 30, 70, 70)) == pytest.approx(2.0)


def test_depth_median_none_when_no_valid_depth():
    assert depth_median_m(np.zeros((50, 50), dtype=np.uint16), (10, 10, 40, 40)) is None


def test_depth_median_float_meters():
    depth = np.full((50, 50), 1.5, dtype=np.float32)
    assert depth_median_m(depth, (10, 10, 40, 40), scale=1.0) == pytest.approx(1.5)


def test_scale_bbox_between_resolutions():
    assert scale_bbox((10, 20, 30, 40), (100, 200), (50, 100)) == (5.0, 10.0, 15.0, 20.0)


def test_smoother_detects_approach_and_not_standing():
    s = PersonSmoother()
    approaching = False
    for i in range(10):
        _, _, approaching = s.update(1, i * 0.1, 3.0 - i * 0.1, 0.0)
    assert approaching
    s2 = PersonSmoother()
    for i in range(10):
        _, _, standing = s2.update(1, i * 0.1, 2.0, 0.0)
    assert not standing


def test_smoother_handles_missing_depth_and_prunes():
    s = PersonSmoother()
    d, _, _ = s.update(7, 0.0, None, 5.0)
    assert d is None
    s.prune(10.0)
    assert 7 not in s._tracks


def make_image(encoding, arr, step_pad=0):
    channels = 1 if arr.ndim == 2 else arr.shape[2]
    raw = arr.tobytes()
    step = arr.shape[1] * channels * arr.itemsize
    if step_pad:
        rows = [raw[i * step:(i + 1) * step] + b'\x00' * step_pad for i in range(arr.shape[0])]
        raw = b''.join(rows)
        step += step_pad
    return SimpleNamespace(encoding=encoding, height=arr.shape[0], width=arr.shape[1],
                           step=step, data=raw)


def test_image_decode_rgb_to_bgr_and_depth_with_padding():
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[..., 0] = 200
    out = image_to_numpy(make_image('rgb8', rgb))
    assert out[0, 0].tolist() == [0, 0, 200]
    depth = np.arange(24, dtype=np.uint16).reshape(4, 6)
    assert np.array_equal(image_to_numpy(make_image('16UC1', depth, step_pad=4)), depth)


def test_contract_roundtrip_is_valid_json_with_vietnamese():
    cmd = contract.make_voice_command(3, 12.34567, 'đến bếp', 'GO_TO', 'bep', 0.91234,
                                      False, [{'destination': 'bep', 'score': 1.0}])
    back = json.loads(contract.dumps(cmd))
    assert back['text'] == 'đến bếp' and back['v'] == 1 and back['confidence'] == 0.912
    msg = contract.make_person_message(1.0, [contract.make_person(2, None, 3.14159, 0.876, True)],
                                       True, 0.0312)
    back = json.loads(contract.dumps(msg))
    assert back['persons'][0]['distance_m'] is None and back['persons'][0]['bearing_deg'] == 3.1
