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
    assert 'đi đến phòng khách' in GRAMMAR
    assert 'dừng lại' in GRAMMAR and 'hủy' in GRAMMAR
    assert GRAMMAR[-1] == vocab.UNK
    assert len(GRAMMAR) == len(set(GRAMMAR))


def test_grammar_skips_digits_but_keeps_spelled_numbers():
    assert not any(c.isdigit() for p in GRAMMAR for c in p)
    assert 'đi đến phòng một không một' in GRAMMAR


@pytest.mark.parametrize('dest', [d for d in vocab.destination_phrases(DATA)
                                  if not any(c.isdigit() for c in d)])
def test_every_grammar_go_phrase_resolves_to_its_destination(dest):
    want = _id_by_phrase()[dest]
    for template in vocab.GO_TEMPLATES:
        r = parse_utterance(template.format(dest), DESTS)
        assert (r.intent, r.destination) == ('GO_TO', want), template.format(dest)


def test_grammar_stop_and_cancel_phrases_match_intent():
    assert all(parse_utterance(p, DESTS).intent == 'STOP' for p in vocab.STOP_PHRASES)
    assert all(parse_utterance(p, DESTS).intent == 'CANCEL' for p in vocab.CANCEL_PHRASES)


def test_whisper_prompt_names_destinations_and_echo_is_filtered():
    prompt = vocab.whisper_prompt(DATA)
    assert 'phòng khách' in prompt and 'trạm sạc' in prompt
    assert is_hallucination(prompt)
    assert not is_hallucination('mang đồ đến phòng khách')


def _case(intent, dest=None):
    return Case('c', 'x', intent, dest)


def _res(intent, dest=None, confirm=False):
    return ParseResult(intent, dest, 0.9, confirm, [])


def test_classify_outcomes():
    go_bep = _case('GO_TO', 'bep')
    assert classify(go_bep, 'x', _res('GO_TO', 'bep')) == CORRECT_AUTO
    assert classify(go_bep, 'x', _res('GO_TO', 'bep', True)) == CORRECT_CONFIRM
    assert classify(go_bep, 'x', _res('GO_TO', 'phong_khach', True)) == WRONG_CONFIRM
    assert classify(go_bep, 'x', _res('UNKNOWN')) == WRONG_CONFIRM
    assert classify(go_bep, 'x', _res('GO_TO', 'phong_khach')) == WRONG_AUTO
    assert classify(go_bep, '', None) == MISSED
    # Unknown place must not make the robot leave without asking.
    assert classify(_case('UNKNOWN'), 'x', _res('GO_TO', 'bep')) == WRONG_AUTO
    assert classify(_case('STOP'), 'x', _res('STOP')) == CORRECT_AUTO
    assert classify(_case('STOP'), 'x', _res('CANCEL')) == WRONG_AUTO


def test_eval_phrases_typed_perfectly_never_act_wrongly():
    cases = load_cases(yaml.safe_load((CONFIG / 'eval_phrases.yaml').read_text(encoding='utf-8')))
    ids = {d.id for d in DESTS}
    for c in cases:
        assert c.expect_destination is None or c.expect_destination in ids
        r = parse_utterance(c.say, DESTS)
        assert classify(c, c.say, r) != WRONG_AUTO, c.say


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
