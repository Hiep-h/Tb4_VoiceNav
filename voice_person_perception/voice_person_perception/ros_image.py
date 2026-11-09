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


def numpy_to_image(arr, encoding='bgr8', frame_id='', stamp=None):
    """Build a sensor_msgs/Image from a uint8 HxWx3 (bgr8) or HxW (mono8) array."""
    from sensor_msgs.msg import Image
    arr = np.ascontiguousarray(arr)
    msg = Image()
    if stamp is not None:
        msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.height, msg.width = int(arr.shape[0]), int(arr.shape[1])
    msg.encoding = encoding
    msg.is_bigendian = 0
    msg.step = int(arr.strides[0])
    msg.data = arr.tobytes()
    return msg
