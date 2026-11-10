import math
import pathlib

import pytest
import yaml

from voice_person_perception import vocab
from voice_person_perception import waypoints as wp
from voice_person_perception.intent import load_destinations, parse_utterance

CONFIG = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'destinations.yaml'


@pytest.mark.parametrize('name, slug', [
    ('bếp', 'bep'), ('Phòng khách', 'phong_khach'), ('phòng 101', 'phong_101'),
    ('Đường đi  - hành lang', 'duong_di_hanh_lang'), ('  ', '')])
def test_slugify(name, slug):
    assert wp.slugify(name) == slug


@pytest.mark.parametrize('yaw', [0.0, 0.5, math.pi / 2, -2.0, 3.0])
def test_quaternion_round_trip(yaw):
    assert wp.yaw_from_quaternion(*wp.quaternion_from_yaw(yaw)) == pytest.approx(yaw)


def test_make_pose_rounds_and_wraps_yaw():
    pose = wp.make_pose(1.23456, -0.0004, 3 * math.pi / 2)
    assert pose == {'x': 1.235, 'y': -0.0, 'yaw': round(-math.pi / 2, 3)}


def test_parse_aliases():
    assert wp.parse_aliases(' nhà bếp,  chỗ   tủ lạnh;nhà bếp, ') == ['nhà bếp', 'chỗ tủ lạnh']
    assert wp.parse_aliases('') == []


def test_upsert_adds_then_updates_keeping_aliases():
    data = {'destinations': []}
    assert wp.upsert(data, 'bep', 'bếp', ['nhà bếp'], wp.make_pose(1, 2, 0)) == 'added'
    assert wp.upsert(data, 'bep', None, ['chỗ tủ lạnh', 'nhà bếp', 'bếp'],
                     wp.make_pose(3, 4, 0)) == 'updated'
    item = wp.find(data, 'bep')
    assert item['name'] == 'bếp'
    assert item['aliases'] == ['nhà bếp', 'chỗ tủ lạnh']  # no duplicate, not the name
    assert item['pose']['x'] == 3.0


def test_remove_and_missing_pose():
    data = {'destinations': [
        {'id': 'a', 'name': 'a'},
        {'id': 'b', 'name': 'b', 'pose': wp.make_pose(0, 0, 0)}]}
    assert wp.missing_pose(data) == ['a']
    assert wp.remove(data, 'a') and not wp.remove(data, 'a')
    assert wp.missing_pose(data) == []


def test_save_load_round_trip_with_backup(tmp_path):
    path = tmp_path / 'destinations.yaml'
    path.write_text(CONFIG.read_text(encoding='utf-8'), encoding='utf-8')
    data = wp.load(str(path))
    original = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    data['map'] = 'lab'
    data['frame'] = 'map'
    wp.upsert(data, 'B', None, ['bếp'], wp.make_pose(1.5, -0.25, 1.571))
    wp.save(str(path), data)
    wp.save(str(path), data)

    assert (tmp_path / 'destinations.yaml.bak').read_text(encoding='utf-8') == \
        CONFIG.read_text(encoding='utf-8')  # backup is the file before the first save
    text = path.read_text(encoding='utf-8')
    assert text.startswith('# ') and 'bếp' in text  # header kept, unicode not escaped
    again = wp.load(str(path))
    assert again['map'] == 'lab'
    assert [d['id'] for d in again['destinations']] == \
        [d['id'] for d in original['destinations']]  # station ids stay "A".."D"
    assert wp.find(again, 'B')['pose'] == {'x': 1.5, 'y': -0.25, 'yaw': 1.571}
    assert 'bếp' in wp.find(again, 'B')['aliases']


def test_file_with_poses_still_works_for_voice(tmp_path):
    data = wp.load(str(CONFIG))
    for item in data['destinations']:
        item['pose'] = wp.make_pose(0, 0, 0)
    wp.upsert(data, 'tu_lanh', 'tủ lạnh', ['chỗ tủ lạnh'], wp.make_pose(2, 1, 0))
    path = tmp_path / 'd.yaml'
    wp.save(str(path), data)
    loaded = yaml.safe_load(path.read_text(encoding='utf-8'))
    dests = load_destinations(loaded)
    assert parse_utterance('mang đồ ra chỗ tủ lạnh', dests).destination == 'tu_lanh'
    assert parse_utterance('từ trạm A mang đến tủ lạnh', dests).source == 'A'
    assert 'đi đến tủ lạnh' in vocab.vosk_grammar(loaded)


def test_nav_goal_command(tmp_path, capsys):
    item = {'id': 'bep', 'pose': {'x': 1.5, 'y': -0.25, 'yaw': math.pi / 2}}
    cmd = wp.nav_goal_command(item)
    assert cmd.startswith('ros2 action send_goal /navigate_to_pose ')
    goal = yaml.safe_load(cmd.split('"')[1])  # the goal is valid YAML for ros2 cli
    assert goal['pose']['header']['frame_id'] == 'map'
    assert goal['pose']['pose']['position'] == {'x': 1.5, 'y': -0.25, 'z': 0.0}
    assert goal['pose']['pose']['orientation']['z'] == pytest.approx(0.7071, abs=1e-4)

    path = tmp_path / 'd.yaml'
    data = {'destinations': [dict(item, name='bếp'), {'id': 'kho', 'name': 'kho'}]}
    wp.save(str(path), data)
    assert wp.goal_main(['--file', str(path)]) == 0
    out = capsys.readouterr().out
    assert 'send_goal' in out and 'kho: chưa có vị trí' in out
    assert wp.goal_main(['khong_co', '--file', str(path)]) == 1
