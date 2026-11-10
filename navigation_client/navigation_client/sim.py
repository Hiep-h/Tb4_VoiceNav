"""Motion of the fake robot used by fake_nav2_server (no ROS)."""

import math


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class SimRobot:
    """Drives in a straight line at `speed` m/s, then turns to the goal heading."""

    def __init__(self, x=0.0, y=0.0, yaw=0.0, speed=0.4, turn_rate=1.5, tolerance=0.05):
        self.x, self.y, self.yaw = x, y, yaw
        self.speed = speed
        self.turn_rate = turn_rate
        self.tolerance = tolerance

    def distance_to(self, gx, gy):
        return math.hypot(gx - self.x, gy - self.y)

    def step(self, gx, gy, gyaw, dt):
        """Move for dt seconds towards (gx, gy, gyaw). Returns True when there."""
        dist = self.distance_to(gx, gy)
        if dist > self.tolerance:
            heading = math.atan2(gy - self.y, gx - self.x)
            self.yaw = heading
            move = min(dist, self.speed * dt)
            self.x += move * math.cos(heading)
            self.y += move * math.sin(heading)
            return False
        err = wrap(gyaw - self.yaw)
        turn = max(-self.turn_rate * dt, min(self.turn_rate * dt, err))
        self.yaw = wrap(self.yaw + turn)
        return abs(wrap(gyaw - self.yaw)) < 0.05
