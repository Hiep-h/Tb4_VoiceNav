"""Pure scenario for the fake person publisher (testable without ROS)."""

from voice_person_perception import contract

LOOP_S = 20.0


def scenario(t, bearing):
    """Return a list of persons for time t (seconds) within the loop."""
    if t < 4.0 or t >= 18.0:
        return []
    if t < 10.0:
        distance, approaching = 3.0 - 2.4 * (t - 4.0) / 6.0, True
    elif t < 13.0:
        distance, approaching = 0.6, False
    else:
        distance, approaching = 0.6 + 2.4 * (t - 13.0) / 5.0, False
    return [contract.make_person(1, distance, bearing, 0.9, approaching)]
