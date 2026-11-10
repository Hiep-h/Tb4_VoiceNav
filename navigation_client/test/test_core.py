import math

import pytest

from navigation_client import core
from navigation_client.protocol import BAD_REQUEST, bad_request, parse_command
from navigation_client.stations import Pose2D, parse_stations

DATA = {
    'frame': 'map',
    'map': 'lab',
    'destinations': [
        {'id': 'A', 'name': 'trạm A', 'pose': {'x': 0.0, 'y': 0.0, 'yaw': 0.0}},
        {'id': 'B', 'name': 'trạm B', 'pose': {'x': 3.0, 'y': 4.0, 'yaw': math.pi / 2}},
        {'id': 'C', 'name': 'trạm C'},  # not marked on the map yet
    ],
}


class FakeBackend(core.NavBackend):
    def __init__(self, up=True):
        self.up = up
        self.sent = []
        self.cancelled = []

    def available(self):
        return self.up

    def send(self, goal_id, pose, frame):
        self.sent.append((goal_id, pose, frame))

    def cancel(self, goal_id):
        self.cancelled.append(goal_id)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(up=True, timeout=0.0):
    changes = []
    clock = Clock()
    backend = FakeBackend(up)
    nav = core.NavigationCore(parse_stations(DATA), backend, clock, goal_timeout_s=timeout,
                              on_change=changes.append)
    return nav, backend, clock, changes


def test_stations_file():
    st = parse_stations(DATA)
    assert st.frame == 'map' and st.map_name == 'lab'
    assert st.pose('B') == Pose2D(3.0, 4.0, math.pi / 2)
    assert st.has('C') and st.pose('C') is None and not st.has('E')
    x, y, z, w = st.pose('B').quaternion()
    assert (x, y) == (0.0, 0.0) and z == pytest.approx(math.sqrt(0.5))
    assert st.pose('A').distance_to(st.pose('B')) == 5.0


def test_navigate_success():
    nav, backend, _, changes = make()
    assert nav.get_navigation_status()['state'] == 'IDLE'
    reply = nav.navigate_to('B', 'req-1')
    assert reply == {'request_id': 'req-1', 'accepted': True, 'goal_id': 'nav-1',
                     'state': 'MOVING', 'reason': None}
    assert backend.sent == [('nav-1', Pose2D(3.0, 4.0, math.pi / 2), 'map')]
    nav.on_accepted('nav-1', True)
    nav.on_feedback('nav-1', 2.5, 6.0, 1)
    status = nav.get_navigation_status()
    assert (status['state'], status['distance_remaining_m'], status['eta_s'],
            status['recoveries']) == ('MOVING', 2.5, 6.0, 1)
    nav.on_result('nav-1', core.SUCCEEDED)
    status = nav.get_navigation_status()
    assert (status['state'], status['station_id'], status['distance_remaining_m']) == \
        ('SUCCEEDED', 'B', 0.0)
    assert [c['state'] for c in changes] == ['MOVING', 'SUCCEEDED']


@pytest.mark.parametrize('station, reason', [('E', 'UNKNOWN_STATION'), (None, 'UNKNOWN_STATION'),
                                             ('C', 'NO_POSE')])
def test_refused_station_keeps_state(station, reason):
    nav, backend, _, changes = make()
    reply = nav.navigate_to(station, 'r')
    assert (reply['accepted'], reply['reason'], reply['state']) == (False, reason, 'IDLE')
    assert backend.sent == [] and changes == []


def test_nav2_not_running():
    nav, backend, _, _ = make(up=False)
    reply = nav.navigate_to('B', 'r')
    assert (reply['accepted'], reply['reason']) == (False, 'NAV2_UNAVAILABLE')
    status = nav.get_navigation_status()
    assert (status['state'], status['reason']) == ('FAILED', 'NAV2_UNAVAILABLE')
    assert backend.sent == []


def test_goal_rejected_and_aborted():
    nav, _, _, _ = make()
    nav.navigate_to('B')
    nav.on_accepted('nav-1', False)
    assert nav.get_navigation_status()['reason'] == 'GOAL_REJECTED'
    nav.navigate_to('A')
    nav.on_accepted('nav-2', True)
    nav.on_result('nav-2', core.FAILED)
    assert (nav.state, nav.reason) == ('FAILED', 'NAV2_ABORTED')


def test_cancel():
    nav, backend, _, _ = make()
    assert nav.cancel_navigation('r0')['reason'] == 'NOT_MOVING'
    nav.navigate_to('B')
    reply = nav.cancel_navigation('r1')
    assert (reply['accepted'], reply['reason'], reply['goal_id']) == \
        (True, 'CANCEL_REQUESTED', 'nav-1')
    assert backend.cancelled == ['nav-1']
    assert nav.state == 'MOVING'               # until Nav2 confirms
    nav.on_result('nav-1', core.CANCELED)
    assert (nav.state, nav.reason) == ('CANCELED', None)


def test_new_goal_replaces_old_and_late_result_is_ignored():
    nav, backend, _, _ = make()
    nav.navigate_to('B', 'r1')
    nav.on_accepted('nav-1', True)
    reply = nav.navigate_to('A', 'r2')        # CHANGE_DESTINATION
    assert (reply['accepted'], reply['reason'], reply['goal_id']) == (True, 'PREEMPTED', 'nav-2')
    nav.on_result('nav-1', core.CANCELED)     # Nav2 ends the old goal: not ours any more
    nav.on_feedback('nav-1', 9.0)
    status = nav.get_navigation_status()
    assert (status['state'], status['station_id'], status['request_id'],
            status['distance_remaining_m']) == ('MOVING', 'A', 'r2', None)
    nav.on_result('nav-2', core.SUCCEEDED)
    assert nav.state == 'SUCCEEDED'


def test_timeout_cancels_and_reports_failed():
    nav, backend, clock, _ = make(timeout=30.0)
    nav.navigate_to('B')
    clock.t += 20
    nav.tick()
    assert backend.cancelled == []
    clock.t += 15
    nav.tick()
    nav.tick()                                 # only one cancel
    assert backend.cancelled == ['nav-1']
    nav.on_result('nav-1', core.CANCELED)
    assert (nav.state, nav.reason) == ('FAILED', 'TIMEOUT')


def test_status_after_reload_keeps_goal():
    nav, _, _, _ = make()
    nav.navigate_to('B')
    nav.set_stations(parse_stations({'destinations': [{'id': 'B', 'pose': {'x': 1, 'y': 1}}]}))
    assert nav.get_navigation_status()['state'] == 'MOVING'
    assert nav.navigate_to('A')['reason'] == 'UNKNOWN_STATION'


@pytest.mark.parametrize('text, ok', [
    ('{"request_id":"r","action":"NAVIGATE_TO","station_id":"B"}', True),
    ('{"action":"navigate_to","station_id":"B"}', True),
    ('{"action":"CANCEL"}', True),
    ('{"action":"GET_STATUS"}', True),
    ('{"action":"NAVIGATE_TO"}', False),
    ('{"action":"FLY"}', False),
    ('[1,2]', False),
    ('trạm B', False),
])
def test_parse_command(text, ok):
    cmd, err = parse_command(text)
    assert (cmd is not None) == ok and (err is None) == ok
    if ok:
        assert cmd['action'] in ('NAVIGATE_TO', 'CANCEL', 'GET_STATUS')


def test_bad_request_reply():
    reply = bad_request('r', 'không phải JSON', 'IDLE')
    assert (reply['accepted'], reply['reason']) == (False, BAD_REQUEST)


def test_sim_robot_reaches_goal_and_heading():
    from navigation_client.sim import SimRobot
    robot = SimRobot(0.0, 0.0, 0.0, speed=1.0)
    steps = 0
    while not robot.step(3.0, 4.0, math.pi / 2, 0.1):
        steps += 1
        assert steps < 200
    assert robot.distance_to(3.0, 4.0) <= robot.tolerance
    assert abs(robot.yaw - math.pi / 2) < 0.05
    assert 45 <= steps <= 70          # 5 m at 1 m/s plus the final turn


def test_nav_cmd_words():
    from navigation_client.nav_cmd import build_command, describe
    assert build_command(['go', 'B'], 'r')[0] == {'request_id': 'r', 'action': 'NAVIGATE_TO',
                                                  'station_id': 'B'}
    assert build_command(['cancel'], 'r')[0]['action'] == 'CANCEL'
    assert build_command(['status'], 'r')[0]['action'] == 'GET_STATUS'
    assert build_command(['go'], 'r')[0] is None
    assert build_command([], 'r')[0] is None
    assert describe({'state': 'MOVING', 'station_id': 'B', 'distance_remaining_m': 1.234,
                     'eta_s': 3.1}) == 'MOVING, trạm B, còn 1.23 m, ~3 s'
    assert describe({'state': 'FAILED', 'reason': 'TIMEOUT'}) == 'FAILED, lý do TIMEOUT'
