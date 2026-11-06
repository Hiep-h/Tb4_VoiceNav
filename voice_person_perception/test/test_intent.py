import pathlib

import yaml

from voice_person_perception.intent import (
    load_destinations,
    normalize,
    parse_utterance,
)

CONFIG = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'destinations.yaml'
DESTS = load_destinations(yaml.safe_load(CONFIG.read_text(encoding='utf-8')))


def go(text, **kw):
    return parse_utterance(text, DESTS, **kw)


def test_normalize_handles_d_with_stroke():
    assert normalize('Mang ĐẾN phòng Khách!') == 'mang den phong khach'


def test_exact_destination_is_confident():
    r = go('mang đồ đến phòng khách')
    assert (r.intent, r.destination, r.needs_confirm) == ('GO_TO', 'phong_khach', False)


def test_alias_matches():
    assert go('đi tới chỗ nấu ăn').destination == 'bep'


def test_missing_accents_still_match():
    assert go('mang den phong khach').destination == 'phong_khach'


def test_small_asr_error_still_resolves_but_asks_to_confirm():
    r = go('mang đến phòng khác')
    assert r.destination == 'phong_khach'
    assert r.needs_confirm


def test_room_numbers_must_match_exactly():
    assert go('đến phòng 101').destination == 'phong_101'
    assert go('đến phòng 102').destination == 'phong_102'
    assert go('đến phòng 103').intent == 'UNKNOWN'


def test_spoken_digits_alias():
    assert go('phòng một không hai').destination == 'phong_102'


def test_stop_and_cancel():
    assert go('dừng lại').intent == 'STOP'
    assert go('Dừng!').intent == 'STOP'
    assert go('stop').intent == 'STOP'
    assert go('hủy đi').intent == 'CANCEL'


def test_dung_without_accent_is_not_a_bare_stop():
    # "đúng" / "dùng" lose their accents too; only the phrase counts.
    assert go('dung roi').intent == 'UNKNOWN'
    assert go('dung lai').intent == 'STOP'
    assert go('đúng rồi').intent == 'UNKNOWN'


def test_unknown_sentence():
    r = go('hôm nay trời đẹp quá')
    assert r.intent == 'UNKNOWN' and r.destination is None


def test_low_asr_confidence_needs_confirm_and_lowers_confidence():
    r = go('mang đến phòng khách', asr_conf=0.4)
    assert r.needs_confirm and r.confidence < 0.5


def test_candidates_are_sorted():
    r = go('đến phòng khách')
    scores = [c['score'] for c in r.candidates]
    assert scores == sorted(scores, reverse=True)
