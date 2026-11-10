"""Navigation Client logic (docs/interfaces.md section 5), without ROS.

    navigate_to(station_id)   -> reply with goal_id, or why it was refused
    cancel_navigation()       -> reply: cancel sent, or why not
    get_navigation_status()   -> IDLE | MOVING | SUCCEEDED | FAILED | CANCELED

The ROS node plugs in a backend that talks to Nav2's /navigate_to_pose and
calls on_accepted / on_feedback / on_result back. Only one goal is active: a
new navigate_to while moving replaces the old goal (Nav2 preempts it) and the
old goal's late result is ignored.
"""

from __future__ import annotations

import itertools

IDLE = 'IDLE'
MOVING = 'MOVING'
SUCCEEDED = 'SUCCEEDED'
FAILED = 'FAILED'
CANCELED = 'CANCELED'
STATES = (IDLE, MOVING, SUCCEEDED, FAILED, CANCELED)

# reasons (docs/interfaces.md section 8)
UNKNOWN_STATION = 'UNKNOWN_STATION'      # not in destinations.yaml
NO_POSE = 'NO_POSE'                      # station not marked on the map yet
NAV2_UNAVAILABLE = 'NAV2_UNAVAILABLE'    # /navigate_to_pose server not running
GOAL_REJECTED = 'GOAL_REJECTED'          # Nav2 refused the goal
NAV2_ABORTED = 'NAV2_ABORTED'            # Nav2 gave up (blocked, no path, ...)
TIMEOUT = 'TIMEOUT'                      # took longer than goal_timeout_s
NOT_MOVING = 'NOT_MOVING'                # cancel with nothing to cancel
CANCEL_REQUESTED = 'CANCEL_REQUESTED'
PREEMPTED = 'PREEMPTED'                  # replaced by a newer navigate_to


class NavBackend:
    """What the core needs from Nav2 (the ROS node implements it)."""

    def available(self):
        raise NotImplementedError

    def send(self, goal_id, pose, frame):
        raise NotImplementedError

    def cancel(self, goal_id):
        raise NotImplementedError


class NavigationCore:

    def __init__(self, stations, backend, clock, goal_timeout_s=0.0, on_change=None):
        self.stations = stations
        self.backend = backend
        self.clock = clock
        self.goal_timeout_s = float(goal_timeout_s)
        self.on_change = on_change
        self._ids = itertools.count(1)
        self.state = IDLE
        self.goal_id = None
        self.station_id = None
        self.request_id = None
        self.reason = None
        self.started_at = None
        self.distance_remaining_m = None
        self.eta_s = None
        self.recoveries = 0
        self._cancel_reason = None   # why we cancelled (TIMEOUT vs user)

    # ---- operations from Mission Manager

    def navigate_to(self, station_id, request_id=None):
        station_id = None if station_id is None else str(station_id)
        if not station_id or not self.stations.has(station_id):
            return self._reply(False, request_id, UNKNOWN_STATION)
        pose = self.stations.pose(station_id)
        if pose is None:
            return self._reply(False, request_id, NO_POSE)
        if not self.backend.available():
            self._set(FAILED, NAV2_UNAVAILABLE, request_id=request_id, station_id=station_id,
                      goal_id=None)
            return self._reply(False, request_id, NAV2_UNAVAILABLE)
        goal_id = f'nav-{next(self._ids)}'
        preempted = self.state == MOVING
        self.started_at = self.clock()
        self.distance_remaining_m = None
        self.eta_s = None
        self.recoveries = 0
        self._cancel_reason = None
        self._set(MOVING, None, request_id=request_id, station_id=station_id, goal_id=goal_id)
        self.backend.send(goal_id, pose, self.stations.frame)
        return self._reply(True, request_id, PREEMPTED if preempted else None, goal_id)

    def cancel_navigation(self, request_id=None):
        if self.state != MOVING:
            return self._reply(False, request_id, NOT_MOVING)
        self._cancel_reason = None
        self.backend.cancel(self.goal_id)
        return self._reply(True, request_id, CANCEL_REQUESTED, self.goal_id)

    def get_navigation_status(self):
        return {
            'request_id': self.request_id,
            'goal_id': self.goal_id,
            'station_id': self.station_id,
            'state': self.state,
            'reason': self.reason,
            'distance_remaining_m': (None if self.distance_remaining_m is None
                                     else round(float(self.distance_remaining_m), 2)),
            'eta_s': None if self.eta_s is None else round(float(self.eta_s), 1),
            'recoveries': int(self.recoveries),
        }

    def tick(self):
        """Call periodically: cancels a goal that runs past goal_timeout_s."""
        if (self.state == MOVING and self.goal_timeout_s > 0 and self._cancel_reason is None
                and self.clock() - self.started_at > self.goal_timeout_s):
            self._cancel_reason = TIMEOUT
            self.backend.cancel(self.goal_id)

    # ---- callbacks from the backend

    def on_accepted(self, goal_id, accepted):
        if goal_id != self.goal_id or self.state != MOVING:
            return
        if not accepted:
            self._set(FAILED, GOAL_REJECTED)

    def on_feedback(self, goal_id, distance_remaining_m=None, eta_s=None, recoveries=None):
        if goal_id != self.goal_id or self.state != MOVING:
            return
        self.distance_remaining_m = distance_remaining_m
        self.eta_s = eta_s
        if recoveries is not None:
            self.recoveries = recoveries

    def on_result(self, goal_id, outcome, reason=None):
        """outcome: SUCCEEDED, FAILED or CANCELED (as reported by Nav2)."""
        if goal_id != self.goal_id or self.state != MOVING:
            return  # result of a goal that was replaced: ignore
        if outcome == SUCCEEDED:
            self.distance_remaining_m = 0.0
            self._set(SUCCEEDED, None)
        elif outcome == CANCELED and self._cancel_reason == TIMEOUT:
            self._set(FAILED, TIMEOUT)
        elif outcome == CANCELED:
            self._set(CANCELED, None)
        else:
            self._set(FAILED, reason or NAV2_ABORTED)

    def set_stations(self, stations):
        self.stations = stations

    # ---- helpers

    def _set(self, state, reason, **fields):
        for key, value in fields.items():
            setattr(self, key, value)
        changed = (state, reason) != (self.state, self.reason) or fields
        self.state, self.reason = state, reason
        if changed and self.on_change:
            self.on_change(self.get_navigation_status())

    def _reply(self, accepted, request_id, reason=None, goal_id=None):
        return {
            'request_id': request_id,
            'accepted': bool(accepted),
            'goal_id': goal_id,
            'state': self.state,
            'reason': reason,
        }
