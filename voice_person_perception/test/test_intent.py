import pathlib

import pytest
import yaml

from voice_person_perception.intent import (
    load_destinations,
    normalize,
    parse_utterance,
)

CONFIG = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'destinations.yaml'
DESTS = load_destinations(yaml.safe_load(CONFIG.read_text(encoding='utf-8')))
ROOMS = load_destinations({'destinations': [
    {'id': 'A', 'name': 'trạm A', 'aliases': ['bếp', 'nhà bếp']},
    {'id': 'B', 'name': 'trạm B', 'aliases': ['phòng khách']},
    {'id': 'P101', 'name': 'phòng 101', 'aliases': ['phòng một không một']},
    {'id': 'P102', 'name': 'phòng 102', 'aliases': ['phòng một không hai']},
]})


def say(text, dests=DESTS, **kw):
    return parse_utterance(text, dests, **kw)


def route(text, dests=DESTS):
    r = say(text, dests)
    return r.intent, r.source, r.destination, r.needs_confirm


def test_normalize_handles_d_with_stroke():
    assert normalize('Mang ĐẾN trạm Bê!') == 'mang den tram be'


@pytest.mark.parametrize('text, src, dst', [
    ('mang hàng từ trạm A đến trạm B', 'A', 'B'),
    ('lấy hàng ở trạm C giao đến trạm D', 'C', 'D'),
    ('từ trạm D mang sang trạm A', 'D', 'A'),
    ('trạm A trạm C', 'A', 'C'),                 # no markers: first is the source
    ('giao đến trạm B', None, 'B'),
    ('mang cái này sang trạm D giúp mình', None, 'D'),
    ('mang đến B', None, 'B'),                   # bare letter after "đến"
    ('đi tới trạm đê', None, 'D'),               # letter as it is read
    ('mang den tram b', None, 'B'),              # no accents
])
def test_create_delivery(text, src, dst):
    assert route(text) == ('CREATE_DELIVERY', src, dst, False)


def test_spoken_letter_without_tram_asks_to_confirm():
    assert route('mang đến bê') == ('CREATE_DELIVERY', None, 'B', True)


def test_source_only_asks_where_to_deliver():
    assert route('lấy hàng ở trạm A') == ('CREATE_DELIVERY', 'A', None, True)


@pytest.mark.parametrize('text, dst', [
    ('đổi sang trạm C', 'C'),
    ('đổi đích từ B sang C', 'C'),
    ('chuyển sang D', 'D'),
    ('thôi đổi sang trạm C', 'C'),   # "thôi" here is not a cancel
])
def test_change_destination(text, dst):
    assert route(text) == ('CHANGE_DESTINATION', None, dst, False)


@pytest.mark.parametrize('text, intent', [
    ('dừng lại', 'PAUSE'), ('Dừng!', 'PAUSE'), ('tạm dừng', 'PAUSE'), ('stop', 'PAUSE'),
    ('dung lai', 'PAUSE'), ('chờ đã', 'PAUSE'),
    ('tiếp tục', 'RESUME'), ('đi tiếp đi', 'RESUME'),
    ('hủy đơn', 'CANCEL'), ('thôi không cần nữa', 'CANCEL'),
    ('đơn hàng đến đâu rồi', 'GET_STATUS'), ('robot đang ở đâu', 'GET_STATUS'),
    ('giao xong chưa', 'GET_STATUS'),
])
def test_keyword_intents(text, intent):
    r = say(text)
    assert (r.intent, r.source, r.destination, r.needs_confirm) == (intent, None, None, False)


def test_pause_wins_over_everything():
    assert say('dừng lại, đừng đi đến trạm B').intent == 'PAUSE'


def test_dung_without_accent_is_not_a_bare_stop():
    # "đúng" / "dùng" lose their accents too; only the phrase counts.
    assert say('dung roi').intent == 'UNKNOWN'
    assert say('đúng rồi').intent == 'UNKNOWN'


@pytest.mark.parametrize('text', [
    'hôm nay trời đẹp quá', 'đi đến nhà vệ sinh', 'mang đến trạm E', 'đến trạm phê',
    'cho đồ vào thùng',
])
def test_not_a_station(text):
    r = say(text)
    assert (r.intent, r.destination) == ('UNKNOWN', None)


def test_room_names_as_aliases():
    assert route('mang đồ ra nhà bếp', ROOMS) == ('CREATE_DELIVERY', None, 'A', False)
    assert route('từ bếp mang sang phòng khách', ROOMS) == ('CREATE_DELIVERY', 'A', 'B', False)


def test_small_asr_error_still_resolves_but_asks_to_confirm():
    assert route('mang đến phòng khác', ROOMS) == ('CREATE_DELIVERY', None, 'B', True)


def test_numbers_must_match_exactly():
    assert say('đến phòng 101', ROOMS).destination == 'P101'
    assert say('đến phòng 102', ROOMS).destination == 'P102'
    assert say('đến phòng 103', ROOMS).intent == 'UNKNOWN'
    assert say('phòng một không hai', ROOMS).destination == 'P102'


def test_low_asr_confidence_asks_and_lowers_confidence():
    r = say('mang đến trạm B', asr_conf=0.4)
    assert r.needs_confirm and r.confidence < 0.5
    assert say('dừng lại', asr_conf=0.4).needs_confirm is False  # never delay a stop


def test_candidates_are_sorted_and_named():
    r = say('mang đến trạm B')
    assert r.candidates[0]['station'] == 'B'
    scores = [c['score'] for c in r.candidates]
    assert scores == sorted(scores, reverse=True)
