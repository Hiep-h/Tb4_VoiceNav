"""Builds the `ros2 bag record` command line (pure Python, unit-tested)."""

import datetime
import os

from voice_person_perception import contract

# What the executor needs: small, and enough to re-run the intent resolver.
PERCEPTION_TOPICS = [
    contract.SPEECH_TEXT_TOPIC,
    contract.VOICE_INTENT_TOPIC,
    contract.PERSON_TOPIC,
]

# Only for re-testing the person detector offline; large (several MB/s).
RAW_CAMERA_TOPICS = [
    '/oakd/rgb/preview/image_raw',
    '/oakd/rgb/preview/depth',
    '/oakd/rgb/preview/camera_info',
]


def default_bag_name(now=None):
    now = now or datetime.datetime.now()
    return 'perception_' + now.strftime('%Y%m%d_%H%M%S')


def build_record_command(output_dir='bags', name='', raw=False, compress=True,
                         now=None):
    """Return the argv list for `ros2 bag record`."""
    path = os.path.join(output_dir, name or default_bag_name(now))
    command = ['ros2', 'bag', 'record', '-o', path]
    if compress:
        command += ['--compression-mode', 'file', '--compression-format', 'zstd']
    command += PERCEPTION_TOPICS
    if raw:
        command += RAW_CAMERA_TOPICS
    return command
