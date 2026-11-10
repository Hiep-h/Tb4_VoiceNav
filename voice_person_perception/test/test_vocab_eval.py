import pathlib

import numpy as np
import pytest
import yaml

from voice_person_perception import vocab
from voice_person_perception.asr_backends import is_hallucination
from voice_person_perception.eval_voice import (
    CORRECT_AUTO,
    CORRECT_CONFIRM,
    MISSED,
    WRONG_AUTO,
    WRONG_CONFIRM,
    Case,
    classify,
    cut_utterance,
    load_cases,
    summarize,
)
from voice_person_perception.intent import ParseResult, load_destinations, parse_utterance

CONFIG = pathlib.Path(__file__).resolve().parents[1] / 'config'
DATA = yaml.safe_load((CONFIG / 'destinations.yaml').read_text(encoding='utf-8'))
DESTS = load_destinations(DATA)
GRAMMAR = vocab.vosk_grammar(DATA)


def _id_by_phrase():
    out = {}
    for item in DATA['destinations']:
        for p in [item.get('name', item['id'])] + item.get('aliases', []):
            out[p.lower()] = item['id']
    return out


def test_grammar_has_commands_and_ends_with_unk():
    assert 'đi đến trạm a' in GRAMMAR
    assert 'mang hàng từ trạm a đến trạm b' in GRAMMAR
    assert 'đổi sang trạm c' in GRAMMAR
    for phrase in ('dừng lại', 'tiếp tục', 'hủy', 'trạng thái'):
        assert phrase in GRAMMAR
    assert GRAMMAR[-1] == vocab.UNK
    assert len(GRAMMAR) == len(set(GRAMMAR))


def test_grammar_skips_digits_but_keeps_spelled_numbers():
    data = {'destinations': [{'id': 'P101', 'name': 'phòng 101',
                              'aliases': ['phòng một không một']}]}
    grammar = vocab.vosk_grammar(data)
    assert not any(c.isdigit() for p in grammar for c in p)
    assert 'đi đến phòng một không một' in grammar


@pytest.mark.parametrize('dest', [d for d in vocab.destination_phrases(DATA)
                                  if not any(c.isdigit() for c in d)])
def test_every_grammar_phrase_resolves_to_its_station(dest):
    want = _id_by_phrase()[dest]
    for template in vocab.GO_TEMPLATES:
        r = parse_utterance(template.format(dest), DESTS)
        assert (r.intent, r.destination) == ('CREATE_DELIVERY', want), template.format(dest)
    for template in vocab.CHANGE_TEMPLATES:
        r = parse_utterance(template.format(dest), DESTS)
        assert (r.intent, r.destination) == ('CHANGE_DESTINATION', want), template.format(dest)


def test_grammar_route_phrases_give_source_and_destination():
    for template in vocab.ROUTE_TEMPLATES:
        r = parse_utterance(template.format('trạm a', 'trạm d'), DESTS)
        assert (r.intent, r.source, r.destination) == ('CREATE_DELIVERY', 'A', 'D'), template


@pytest.mark.parametrize('phrases, intent', [
    (vocab.PAUSE_PHRASES, 'PAUSE'), (vocab.RESUME_PHRASES, 'RESUME'),
    (vocab.CANCEL_PHRASES, 'CANCEL'), (vocab.STATUS_PHRASES, 'GET_STATUS')])
def test_grammar_keyword_phrases_match_intent(phrases, intent):
    for p in phrases:
        assert parse_utterance(p, DESTS).intent == intent, p


def test_whisper_prompt_names_stations_and_echo_is_filtered():
    prompt = vocab.whisper_prompt(DATA)
    assert 'trạm A' in prompt and 'trạm D' in prompt
    assert is_hallucination(prompt)
    assert not is_hallucination('mang hàng đến trạm B')


def _case(intent, dest=None, source=None):
    return Case('c', 'x', intent, dest, source)


def _res(intent, dest=None, confirm=False, source=None):
    return ParseResult(intent, dest, 0.9, confirm, [], source)


def test_classify_outcomes():
    to_b = _case('CREATE_DELIVERY', 'B')
    assert classify(to_b, 'x', _res('CREATE_DELIVERY', 'B')) == CORRECT_AUTO
    assert classify(to_b, 'x', _res('CREATE_DELIVERY', 'B', True)) == CORRECT_CONFIRM
    assert classify(to_b, 'x', _res('CREATE_DELIVERY', 'C', True)) == WRONG_CONFIRM
    assert classify(to_b, 'x', _res('UNKNOWN')) == WRONG_CONFIRM
    assert classify(to_b, 'x', _res('CREATE_DELIVERY', 'C')) == WRONG_AUTO
    assert classify(to_b, '', None) == MISSED
    a_to_b = _case('CREATE_DELIVERY', 'B', 'A')
    assert classify(a_to_b, 'x', _res('CREATE_DELIVERY', 'B', source='A')) == CORRECT_AUTO
    assert classify(a_to_b, 'x', _res('CREATE_DELIVERY', 'B', source='C')) == WRONG_AUTO
    # A place that is not a station must not make the robot leave without asking.
    assert classify(_case('UNKNOWN'), 'x', _res('CREATE_DELIVERY', 'B')) == WRONG_AUTO
    assert classify(_case('PAUSE'), 'x', _res('PAUSE')) == CORRECT_AUTO
    assert classify(_case('PAUSE'), 'x', _res('CANCEL')) == WRONG_AUTO
    assert classify(_case('CHANGE_DESTINATION', 'C'), 'x',
                    _res('CHANGE_DESTINATION', 'C')) == CORRECT_AUTO


def test_eval_phrases_typed_perfectly_are_all_right():
    cases = load_cases(yaml.safe_load((CONFIG / 'eval_phrases.yaml').read_text(encoding='utf-8')))
    ids = {d.id for d in DESTS}
    for c in cases:
        assert c.expect_destination is None or c.expect_destination in ids
        assert c.expect_source is None or c.expect_source in ids
        r = parse_utterance(c.say, DESTS)
        assert classify(c, c.say, r) == CORRECT_AUTO, c.say


def test_summarize():
    rows = [{'outcome': CORRECT_AUTO, 'asr_s': 0.5},
            {'outcome': CORRECT_CONFIRM, 'asr_s': 1.0},
            {'outcome': MISSED, 'asr_s': 2.0},
            {'outcome': WRONG_AUTO, 'asr_s': 1.5}]
    s = summarize(rows)
    assert s['accuracy'] == 0.5
    assert s['counts'][WRONG_AUTO] == 1
    assert s['latency_mean_s'] == pytest.approx(1.25)


def test_cut_utterance_keeps_speech_and_drops_lead_in():
    rate = 16000
    rng = np.random.default_rng(0)
    noise = lambda s: rng.normal(0, 30, int(s * rate))  # noqa: E731
    t = np.arange(int(0.8 * rate)) / rate
    speech = 4000 * np.sin(2 * np.pi * 300 * t)
    audio = np.concatenate([noise(1.0), speech, noise(1.0)]).astype(np.int16)
    utt = cut_utterance(audio, rate)
    assert 0.7 * rate <= len(utt) <= 1.6 * rate
