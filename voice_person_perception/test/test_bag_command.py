import datetime

from voice_person_perception.bag_command import (
    PERCEPTION_TOPICS,
    RAW_CAMERA_TOPICS,
    build_record_command,
    default_bag_name,
)

NOW = datetime.datetime(2026, 11, 7, 9, 5, 3)


def test_default_name_uses_timestamp():
    assert default_bag_name(NOW) == 'perception_20261107_090503'


def test_default_command_records_perception_topics_compressed():
    cmd = build_record_command(now=NOW)
    assert cmd[:3] == ['ros2', 'bag', 'record']
    assert cmd[cmd.index('-o') + 1] == 'bags/perception_20261107_090503'
    assert cmd[cmd.index('--compression-format') + 1] == 'zstd'
    assert cmd[-len(PERCEPTION_TOPICS):] == PERCEPTION_TOPICS
    assert not set(RAW_CAMERA_TOPICS) & set(cmd)


def test_raw_adds_camera_topics_and_custom_name():
    cmd = build_record_command(output_dir='/tmp/x', name='test_a', raw=True, compress=False)
    assert cmd[cmd.index('-o') + 1] == '/tmp/x/test_a'
    assert '--compression-mode' not in cmd
    assert set(RAW_CAMERA_TOPICS) <= set(cmd)
