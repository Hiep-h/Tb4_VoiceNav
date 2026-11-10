"""Messages between Mission Manager and Navigation Client (JSON in std_msgs/String).

Temporary until ARCH-01 fixes the message types; the operations follow
docs/interfaces.md section 5.

/navigation/command   Mission Manager -> Navigation Client
    {"request_id": "req-001", "action": "NAVIGATE_TO", "station_id": "B"}
    {"request_id": "req-002", "action": "CANCEL"}
    {"request_id": "req-003", "action": "GET_STATUS"}

/navigation/response  Navigation Client -> Mission Manager, one per command
    {"request_id": "req-001", "accepted": true, "goal_id": "nav-1",
     "state": "MOVING", "reason": null}

/navigation/status    Navigation Client -> everyone, on every change and every second
    {"request_id": "req-001", "goal_id": "nav-1", "station_id": "B",
     "state": "MOVING", "reason": null, "distance_remaining_m": 2.4,
     "eta_s": 8.0, "recoveries": 0, "stamp": 12.3}
"""

from __future__ import annotations

import json

COMMAND_TOPIC = '/navigation/command'
RESPONSE_TOPIC = '/navigation/response'
STATUS_TOPIC = '/navigation/status'

NAVIGATE_TO = 'NAVIGATE_TO'
CANCEL = 'CANCEL'
GET_STATUS = 'GET_STATUS'
ACTIONS = (NAVIGATE_TO, CANCEL, GET_STATUS)

BAD_REQUEST = 'BAD_REQUEST'


def dumps(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def parse_command(text):
    """(command dict, None) or (None, error message)."""
    try:
        cmd = json.loads(text)
    except (TypeError, ValueError):
        return None, 'không phải JSON'
    if not isinstance(cmd, dict):
        return None, 'cần một object JSON'
    action = str(cmd.get('action', '')).upper()
    if action not in ACTIONS:
        return None, f"action phải là {', '.join(ACTIONS)}"
    cmd['action'] = action
    if action == NAVIGATE_TO and not cmd.get('station_id'):
        return None, 'NAVIGATE_TO cần station_id'
    return cmd, None


def bad_request(request_id, message, state):
    return {'request_id': request_id, 'accepted': False, 'goal_id': None, 'state': state,
            'reason': BAD_REQUEST, 'detail': message}


def with_stamp(payload, stamp):
    out = dict(payload)
    out['stamp'] = round(float(stamp), 3)
    return out
