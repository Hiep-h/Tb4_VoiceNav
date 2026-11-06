import numpy as np

from voice_person_perception.asr_backends import is_hallucination
from voice_person_perception.vad import EnergyVad, resample_to

RATE = 16000
RNG = np.random.default_rng(0)


def noise(seconds, level=40):
    return (RNG.standard_normal(int(RATE * seconds)) * level).astype(np.int16)


def tone(seconds, amp=4000):
    t = np.arange(int(RATE * seconds)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def run(vad, signal, chunk=1600):
    out = []
    for i in range(0, len(signal), chunk):
        out += vad.feed(signal[i:i + chunk])
    return out


def test_noise_only_gives_no_utterance():
    assert run(EnergyVad(), noise(5)) == []


def test_one_utterance_with_preroll_and_length():
    signal = np.concatenate([noise(1), tone(1.0), noise(1.5)])
    utts = run(EnergyVad(), signal)
    assert len(utts) == 1
    seconds = len(utts[0]) / RATE
    assert 1.0 <= seconds <= 1.8


def test_two_utterances_separated_by_silence():
    signal = np.concatenate([noise(1), tone(0.8), noise(1.2), tone(0.8), noise(1.5)])
    assert len(run(EnergyVad(), signal)) == 2


def test_short_click_is_ignored():
    signal = np.concatenate([noise(1), tone(0.1), noise(1.5)])
    assert run(EnergyVad(), signal) == []


def test_long_speech_is_split():
    utts = run(EnergyVad(max_utterance_s=2.0), np.concatenate([noise(1), tone(5), noise(1.5)]))
    assert len(utts) >= 2


def test_threshold_follows_noise_floor():
    vad = EnergyVad()
    run(vad, noise(2, level=400))
    assert vad.threshold > 1000


def test_resample_length():
    audio = tone(1.0)
    assert abs(len(resample_to(audio, 48000, 16000)) - len(audio) // 3) <= 2
    assert resample_to(audio, 16000, 16000) is audio


def test_hallucination_filter():
    assert is_hallucination('Hãy đăng ký kênh để ủng hộ')
    assert not is_hallucination('mang đến phòng khách')
