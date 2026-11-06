from voice_person_perception.fake_scenarios import LOOP_S, scenario


def test_empty_at_start_and_end():
    assert scenario(1.0, 0.0) == [] and scenario(19.0, 0.0) == []


def test_person_approaches_then_leaves():
    distances = [scenario(t, 0.0)[0]['distance_m'] for t in (4.0, 7.0, 10.0, 11.0, 13.0, 17.9)]
    assert distances[0] > distances[1] > distances[2] == distances[3] == distances[4] < distances[5]
    assert scenario(7.0, 0.0)[0]['approaching'] is True
    assert scenario(11.0, 0.0)[0]['approaching'] is False
    assert LOOP_S == 20.0


def test_bearing_is_passed_through():
    assert scenario(8.0, 12.5)[0]['bearing_deg'] == 12.5
