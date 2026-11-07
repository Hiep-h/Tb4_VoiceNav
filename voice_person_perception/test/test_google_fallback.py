import numpy as np
import pytest

from voice_person_perception.asr_backends import (
    GOOGLE_DEFAULT_CONF,
    FallbackBackend,
    GoogleBackend,
    make_backend,
    pick_alternative,
)

HINTS = ['bếp', 'nhà bếp', 'phòng khách', 'trạm sạc']
AUDIO = np.zeros(1600, dtype=np.int16)


def test_pick_top_guess_when_none_names_a_destination():
    alts = [{'transcript': 'xin chào', 'confidence': 0.91}, {'transcript': 'xin chao'}]
    assert pick_alternative(alts, HINTS) == ('xin chào', 0.91)


def test_pick_guess_that_names_a_destination():
    alts = [{'transcript': 'mang đến phòng khác', 'confidence': 0.7},
            {'transcript': 'mang đến phòng khách'}]
    text, conf = pick_alternative(alts, HINTS)
    assert text == 'mang đến phòng khách'
    assert conf == pytest.approx(0.7)


def test_hint_must_be_whole_words():
    # "bếp" must not match inside another word after accent removal.
    alts = [{'transcript': 'bepxyz', 'confidence': 0.9}, {'transcript': 'ra bếp'}]
    assert pick_alternative(alts, HINTS)[0] == 'ra bếp'


def test_pick_handles_empty_and_missing_confidence():
    assert pick_alternative([], HINTS) is None
    assert pick_alternative([{'transcript': '  '}], HINTS) is None
    assert pick_alternative([{'transcript': 'đi ra bếp'}], HINTS) == (
        'đi ra bếp', GOOGLE_DEFAULT_CONF)


def test_google_backend_uses_vi_vn_and_parses_result():
    calls = []

    def recognize(raw, rate, lang):
        calls.append((len(raw), rate, lang))
        return {'alternative': [{'transcript': 'về trạm sạc', 'confidence': 0.95}],
                'final': True}

    backend = GoogleBackend('vi', 16000, HINTS, recognize=recognize)
    assert backend.transcribe(AUDIO) == ('về trạm sạc', 0.95)
    assert calls == [(3200, 16000, 'vi-VN')]


def test_google_backend_nothing_understood_returns_none():
    backend = GoogleBackend('vi', recognize=lambda *a: [])
    assert backend.transcribe(AUDIO) is None


class _Engine:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def transcribe(self, audio):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_fallback_not_used_when_primary_works():
    primary, backup = _Engine(('đi ra bếp', 0.9)), _Engine(('x', 0.5))
    fb = FallbackBackend(primary, backup, 'google', 'whisper')
    assert fb.transcribe(AUDIO) == ('đi ra bếp', 0.9)
    assert (fb.last_engine, backup.calls) == ('google', 0)


def test_fallback_not_used_when_primary_hears_nothing():
    backup = _Engine(('x', 0.5))
    fb = FallbackBackend(_Engine(None), backup, 'google', 'whisper')
    assert fb.transcribe(AUDIO) is None
    assert backup.calls == 0


def test_fallback_used_when_primary_raises():
    errors = []
    fb = FallbackBackend(_Engine(error=OSError('no network')), _Engine(('đi ra bếp', 0.6)),
                         'google', 'whisper', on_fallback=errors.append)
    assert fb.transcribe(AUDIO) == ('đi ra bếp', 0.6)
    assert fb.last_engine == 'whisper'
    assert len(errors) == 1


def test_make_backend_rejects_unknown_and_none_means_no_fallback(monkeypatch):
    with pytest.raises(RuntimeError):
        make_backend('siri')
    import voice_person_perception.asr_backends as ab
    monkeypatch.setattr(ab, 'GoogleBackend', lambda *a, **k: _Engine(('a', 1.0)))
    monkeypatch.setattr(ab, 'WhisperBackend', lambda *a, **k: _Engine(('b', 1.0)))
    assert isinstance(make_backend('google', fallback='none'), _Engine)
    assert isinstance(make_backend('google', fallback='whisper'), FallbackBackend)
