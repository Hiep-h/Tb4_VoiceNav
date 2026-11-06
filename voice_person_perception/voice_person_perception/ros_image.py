"""Decode sensor_msgs/Image to numpy without cv_bridge (avoids its numpy ABI issues)."""

import numpy as np

_DTYPES = {
    'bgr8': (np.uint8, 3), 'rgb8': (np.uint8, 3), 'mono8': (np.uint8, 1),
    '8UC1': (np.uint8, 1), 'mono16': (np.uint16, 1), '16UC1': (np.uint16, 1),
    '32FC1': (np.float32, 1),
}


def image_to_numpy(msg):
    """Return (array, encoding). Colour images are returned as BGR."""
    if msg.encoding not in _DTYPES:
        raise ValueError(f'Không hỗ trợ encoding {msg.encoding}')
    dtype, channels = _DTYPES[msg.encoding]
    itemsize = np.dtype(dtype).itemsize
    row = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
    row = row[:, :msg.width * channels * itemsize]
    arr = np.ascontiguousarray(row).view(dtype)
    arr = arr.reshape(msg.height, msg.width, channels) if channels > 1 else \
        arr.reshape(msg.height, msg.width)
    if msg.encoding == 'rgb8':
        arr = arr[:, :, ::-1].copy()
    return arr
